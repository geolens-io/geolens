#!/bin/bash
# Demo-VM Prometheus -> Azure Monitor alert bridge — cron every 5 min.
#
# prom-guard.sh (this dir) already logs firing alerts locally and can ping an
# optional dead-man's-switch URL. This script is a DIFFERENT delivery path:
# it turns "firing alert count" into an Azure Monitor custom metric on the VM
# resource, so the VM's existing action group (ag-geolens-demo-ops, email —
# already wired to the geolens-demo-disk-90 disk alert) can also fire on
# Prometheus alerts without the VM needing its own SMTP/webhook credentials.
#
# jq is NOT guaranteed on the VM; python3 IS. All JSON handling below goes
# through python3 instead.
#
# Auth: the VM's system-assigned managed identity requests a token from IMDS
# scoped to https://monitoring.azure.com/ and POSTs the metric as itself
# against its own resource ID — no stored credential, no extra role
# assignment needed (validated live: a VM's managed identity may emit custom
# metrics against itself without Monitoring Metrics Publisher).
set -u

LOG=${LOG:-/var/log/geolens-prom-bridge.log}
PROMETHEUS_URL=${PROMETHEUS_URL:-http://127.0.0.1:9090/api/v1/alerts}

# Azure resource coordinates. Overridable so this script isn't tied to one VM;
# defaults match the current demo (rg-geolens-demo / geolens-demo / centralus).
SUBSCRIPTION_ID_URL=${SUBSCRIPTION_ID_URL:-"http://169.254.169.254/metadata/instance/compute/subscriptionId?api-version=2021-02-01&format=text"}
IMDS_TOKEN_URL=${IMDS_TOKEN_URL:-"http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https%3A%2F%2Fmonitoring.azure.com%2F"}
RESOURCE_GROUP=${RESOURCE_GROUP:-rg-geolens-demo}
VM_NAME=${VM_NAME:-geolens-demo}
REGION=${REGION:-centralus}
METRIC_NAMESPACE=${METRIC_NAMESPACE:-geolens/prometheus}
METRIC_NAME=${METRIC_NAME:-alerts_firing}
# Set to point the POST at a local mock for a dry run; empty derives the real
# per-VM endpoint below from RESOURCE_GROUP/VM_NAME/REGION.
METRICS_URL_OVERRIDE=${METRICS_URL_OVERRIDE:-}

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# --- 1. Count firing alerts -------------------------------------------------
ALERTS_JSON=$(curl -fsS --max-time 10 "$PROMETHEUS_URL" 2>>"$LOG") || {
    echo "$(ts) ERROR prometheus unreachable at $PROMETHEUS_URL" >>"$LOG"
    exit 0
}

# Prints "<count>\t<comma-joined alertnames>" on success, "ERROR\t<msg>" on
# failure — read as a single tab-delimited line to avoid multi-line parsing.
PARSED=$(printf '%s' "$ALERTS_JSON" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    alerts = [a for a in data.get("data", {}).get("alerts", []) if a.get("state") == "firing"]
    names = ",".join(a.get("labels", {}).get("alertname", "unknown") for a in alerts)
    print(f"{len(alerts)}\t{names}")
except Exception as exc:
    print(f"ERROR\t{exc}")
')
IFS=$'\t' read -r COUNT NAMES <<<"$PARSED"

if [ "$COUNT" = "ERROR" ] || ! [[ "$COUNT" =~ ^[0-9]+$ ]]; then
    echo "$(ts) ERROR could not parse prometheus alerts response: ${NAMES:-unknown}" >>"$LOG"
    exit 0
fi

# --- 2. Managed-identity token + subscription id (IMDS) ---------------------
TOKEN_RESPONSE=$(curl -fsS --max-time 10 --noproxy '*' -H "Metadata:true" "$IMDS_TOKEN_URL" 2>>"$LOG") || {
    echo "$(ts) ERROR IMDS token request failed (count=$COUNT firing=${NAMES:-none})" >>"$LOG"
    exit 0
}
TOKEN=$(printf '%s' "$TOKEN_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("access_token",""))' 2>>"$LOG")
if [ -z "$TOKEN" ]; then
    echo "$(ts) ERROR IMDS token response missing access_token (count=$COUNT firing=${NAMES:-none})" >>"$LOG"
    exit 0
fi

SUBSCRIPTION_ID=$(curl -fsS --max-time 10 --noproxy '*' -H "Metadata:true" "$SUBSCRIPTION_ID_URL" 2>>"$LOG") || {
    echo "$(ts) ERROR IMDS subscriptionId request failed (count=$COUNT firing=${NAMES:-none})" >>"$LOG"
    exit 0
}
if [ -z "$SUBSCRIPTION_ID" ]; then
    echo "$(ts) ERROR IMDS subscriptionId response empty (count=$COUNT firing=${NAMES:-none})" >>"$LOG"
    exit 0
fi

# --- 3. POST the custom metric -----------------------------------------------
# ALWAYS runs, even at count=0 — a zero-valued series is what lets the alert
# rule's "no data" state mean "bridge is down/silent" instead of overloading
# it to also mean "all quiet". min/max/sum all equal count, count=1 (a single
# sample per 5-minute run) — this is the exact body shape validated live
# against the metrics endpoint below.
RESOURCE_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Compute/virtualMachines/${VM_NAME}"
METRICS_URL="${METRICS_URL_OVERRIDE:-https://${REGION}.monitoring.azure.com${RESOURCE_ID}/metrics}"

POST_RESULT=$(COUNT="$COUNT" TOKEN="$TOKEN" METRICS_URL="$METRICS_URL" \
    METRIC_NAME="$METRIC_NAME" METRIC_NAMESPACE="$METRIC_NAMESPACE" python3 - <<'PYEOF'
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

count = int(os.environ["COUNT"])
body = {
    "time": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="milliseconds"),
    "data": {
        "baseData": {
            "metric": os.environ["METRIC_NAME"],
            "namespace": os.environ["METRIC_NAMESPACE"],
            "dimNames": [],
            "series": [
                {"dimValues": [], "min": count, "max": count, "sum": count, "count": 1}
            ],
        }
    },
}
payload = json.dumps(body).encode("utf-8")
req = urllib.request.Request(
    os.environ["METRICS_URL"],
    data=payload,
    method="POST",
    headers={
        "Authorization": "Bearer " + os.environ["TOKEN"],
        "Content-Type": "application/json",
    },
)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"OK\t{resp.status}\t")
except urllib.error.HTTPError as exc:
    detail = exc.read().decode("utf-8", "replace")[:300].replace("\n", " ").replace("\t", " ")
    print(f"ERROR\t{exc.code}\t{detail}")
except Exception as exc:
    print(f"ERROR\t-\t{exc}")
PYEOF
)
IFS=$'\t' read -r STATUS CODE DETAIL <<<"$POST_RESULT"

if [ "$STATUS" = "OK" ]; then
    echo "$(ts) OK count=$COUNT firing=${NAMES:-none} metric_post=$CODE" >>"$LOG"
else
    echo "$(ts) ERROR count=$COUNT firing=${NAMES:-none} metric_post_failed status=$CODE detail=$DETAIL" >>"$LOG"
fi
exit 0
