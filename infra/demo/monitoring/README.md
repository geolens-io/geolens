# Demo VM: log retention + alert delivery

Install notes for two ops gaps found during the 2026-08-23 v1.15.0 redeploy audit:
container logs were lost on container re-creation, and Prometheus `ALERTS` were
never wired to a notification channel.

**Why this file, and not `infra/demo/README.md`:** the top-level demo README
carries the VM's public IP, admin-credential pointer, and other operational
narrative and is explicitly marked "do not commit to the public repo" (it is
not tracked in git — only `infra/monitoring/*`, the generic self-host reference
config, is). The two scripts below and this note contain no VM-identifying
secrets — subscription id is read from IMDS at runtime, nothing is hardcoded
beyond the already-public demo resource *names* (`rg-geolens-demo`,
`geolens-demo`, `ag-geolens-demo-ops` — not credentials) — so they're tracked
here rather than folded into the private file. If you also want this content
merged into the top-level README, that edit has to happen by hand on the VM
operator's own checkout; nothing in this PR touches that file.

## Part 1 — Log retention survives container re-creation

`infra/demo/logging-override.yml` switches every service in the root
`docker-compose.prod.yml` from the default `json-file` driver (tied to the
container, deleted on re-creation) to `journald` (tied to the host, survives
`docker compose up -d --build` / `--force-recreate` / any image bump).

Install on the VM:

```bash
# 1. Copy the override alongside docker-compose.prod.yml.
scp infra/demo/logging-override.yml azureuser@<vm>:/opt/geolens/logging-override.yml

# 2. Point bare `docker compose` at both files (add to /opt/geolens/.env):
echo 'COMPOSE_FILE=docker-compose.prod.yml:logging-override.yml' >> /opt/geolens/.env

# 3. Recreate the stack so the new log driver takes effect (log driver is
#    set at container-create time, not live-reloadable):
cd /opt/geolens && docker compose up -d

# 4. Verify.
docker inspect --format '{{.HostConfig.LogConfig.Type}}' geolens-api-1   # -> journald
docker logs geolens-api-1 --tail 20                                      # still works
journalctl CONTAINER_NAME=geolens-api-1 --since "-1 hour"                # survives recreation
```

Re-run `docker compose -f docker-compose.prod.yml -f infra/demo/logging-override.yml
config --quiet` after editing either compose file — an override entry that
doesn't match an existing base-file service name creates a *new* service
instead of overriding one, and `--quiet` only tells you the YAML parsed, not
that the service set is unchanged (diff `config --services` for that).

## Part 2 — Prometheus alerts reach the on-call inbox

`infra/demo/monitoring/prom-alert-bridge.sh` polls the VM's local Prometheus
(`:9090/api/v1/alerts`) every 5 minutes, counts alerts with `state=="firing"`,
and pushes the count as an Azure Monitor custom metric
(`geolens/prometheus` / `alerts_firing`) on the VM's own resource, using the
VM's system-assigned managed identity via IMDS — no stored credential on the
box. `prom-guard.sh` (same directory) is a separate, older path: local-log +
optional dead-man's-switch ping. This bridge is additive, not a replacement.

Install on the VM:

```bash
# 1. Ship the script + cron file (matches how the monitoring stack itself
#    deploys to /opt/geolens-monitoring — see docker-compose.monitoring.yml).
scp infra/demo/monitoring/prom-alert-bridge.sh azureuser@<vm>:/opt/geolens-monitoring/prom-alert-bridge.sh
ssh azureuser@<vm> 'sudo chmod +x /opt/geolens-monitoring/prom-alert-bridge.sh'
scp infra/demo/monitoring/prom-alert-bridge.cron azureuser@<vm>:/tmp/prom-alert-bridge.cron
ssh azureuser@<vm> 'sudo install -o root -g root -m 0644 /tmp/prom-alert-bridge.cron /etc/cron.d/geolens-prom-bridge'

# 2. Smoke-test manually before waiting on cron.
ssh azureuser@<vm> 'sudo /opt/geolens-monitoring/prom-alert-bridge.sh && tail -3 /var/log/geolens-prom-bridge.log'
```

### Azure side — already provisioned, nothing to run here

- **No role assignment needed.** Validated live: an IMDS token for
  `https://monitoring.azure.com/` scoped to the VM's own managed identity is
  sufficient to POST a custom metric against that same VM's resource ID — a
  VM may emit metrics about itself without `Monitoring Metrics Publisher`.
  (Earlier drafts of this doc assumed that role assignment was required; it
  is not, and the credential available to provision this couldn't grant one
  anyway.)
- **Metric alert rule already exists**: `geolens-demo-prom-alerts` — average
  of `alerts_firing` (namespace `geolens/prometheus`) `> 0` over a 15-minute
  window, evaluated every 5 minutes, action group `ag-geolens-demo-ops`
  (the existing email channel already used by `geolens-demo-disk-90`). A
  zero-value sample has already been seeded so "no data" reads as "bridge is
  down", not "steady state".

Read-only checks (no state change):

```bash
az monitor metrics alert show -g rg-geolens-demo -n geolens-demo-prom-alerts -o table
az monitor metrics list -g rg-geolens-demo --resource geolens-demo \
  --resource-type Microsoft.Compute/virtualMachines \
  --namespace geolens/prometheus --metric alerts_firing --interval PT5M
```

## Redeploy checklist note

Neither `logging-override.yml` nor the `prom-alert-bridge.*` files are picked
up by an image/release redeploy — they're demo-VM ops files, not shipped
product artifacts. They sync to the VM the same way `infra/demo/monitoring/
alerts.yml` already does relative to the tracked `infra/monitoring/alerts.yml`:
by hand, on demand. After merging a change to any of the three files here,
re-run the copy steps above on the VM — a `git pull` on the VM checkout alone
does not restart the cron job or recreate the containers.
