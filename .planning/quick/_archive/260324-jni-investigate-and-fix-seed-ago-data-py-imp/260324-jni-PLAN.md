---
phase: quick-260324-jni
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/nginx.conf
  - scripts/seed-ago-data.py
autonomous: true
requirements: [SEED-FIX-502, SEED-FIX-TIMEOUT, SEED-RETRY]

must_haves:
  truths:
    - "nginx no longer returns 502 for long-running service preview requests"
    - "Seed script defaults to concurrency 1, preventing backend overload"
    - "Seed script retries on 5xx errors with exponential backoff + jitter"
    - "Seed script poll timeout defaults to 1200s, configurable via --timeout flag"
    - "httpx client timeout exceeds nginx proxy_read_timeout so nginx is never the bottleneck"
    - "Admin Jobs dashboard already exists — no new UI work needed"
  artifacts:
    - path: "frontend/nginx.conf"
      provides: "proxy_read_timeout 600s on /api/ location"
      contains: "proxy_read_timeout 600s"
    - path: "scripts/seed-ago-data.py"
      provides: "Hardened seed script with retry, lower concurrency, configurable timeout"
      contains: "--timeout"
  key_links:
    - from: "frontend/nginx.conf"
      to: "backend (uvicorn)"
      via: "proxy_pass with 600s read timeout"
      pattern: "proxy_read_timeout 600s"
    - from: "scripts/seed-ago-data.py"
      to: "/api/services/preview/"
      via: "httpx POST with retry on 5xx"
      pattern: "retry.*5[0-9]{2}"
---

<objective>
Fix seed-ago-data.py import failures caused by nginx 502 Bad Gateway and job poll timeouts.

Purpose: The seed script fails ~20+ out of 78 layers due to (1) nginx timing out before the backend finishes service preview ogrinfo calls, and (2) the script's 600s poll timeout being shorter than backend's 3600s job timeout.

Output: Updated nginx.conf with proxy timeouts, hardened seed script with retry logic, lower default concurrency, and configurable timeout.

Note: Research confirmed the Admin Jobs dashboard already exists at /admin/jobs with full filtering, search, and retry — no new UI work is needed.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@frontend/nginx.conf
@scripts/seed-ago-data.py
@.planning/quick/260324-jni-investigate-and-fix-seed-ago-data-py-imp/260324-jni-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add nginx proxy timeouts for /api/ location block</name>
  <files>frontend/nginx.conf</files>
  <action>
Add three proxy timeout directives to the `/api/` location block (after the existing `client_max_body_size 500m;` line):

```nginx
proxy_read_timeout 600s;
proxy_send_timeout 600s;
proxy_connect_timeout 30s;
```

Why 600s read/send: The service preview endpoint runs ogrinfo with a 60s subprocess timeout, but file uploads and large responses can take minutes. 600s gives ample headroom while the backend's own timeouts (60s ogrinfo, 3600s job processing) remain the real guards. nginx should not be the bottleneck.

Why 30s connect: Connection to the upstream should be fast; 30s catches a truly dead backend without masking slow requests.

Do NOT change any other location blocks (titiler, static, etc.) — only `/api/`.
  </action>
  <verify>
    <automated>grep -c "proxy_read_timeout 600s" frontend/nginx.conf | grep -q "1" && grep -c "proxy_send_timeout 600s" frontend/nginx.conf | grep -q "1" && grep -c "proxy_connect_timeout 30s" frontend/nginx.conf | grep -q "1" && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>nginx.conf /api/ block has proxy_read_timeout 600s, proxy_send_timeout 600s, proxy_connect_timeout 30s</done>
</task>

<task type="auto">
  <name>Task 2: Harden seed script — retry, concurrency, timeout, httpx timeout</name>
  <files>scripts/seed-ago-data.py</files>
  <action>
Five changes to `scripts/seed-ago-data.py`:

**A. Add `--timeout` CLI flag (in the argparse section, ~line 693):**
Add after the `--concurrency` argument:
```python
parser.add_argument(
    "--timeout",
    type=int,
    default=1200,
    help="Job poll timeout in seconds (default: 1200)",
)
```

**B. Change default concurrency from 3 to 1 (~line 691):**
Change `default=3` to `default=1` on the `--concurrency` argument.

**C. Thread timeout through the entire call chain:**

The current call chain is: `main()` → `process_one()` → `ingest_via_service()`/`update_via_service()` → `poll_job()`. The `timeout` parameter must be explicitly passed at every level:

1. `poll_job()` (~line 255): Change signature default from `timeout: int = 600` to `timeout: int = 1200`
2. `ingest_via_service()` (~line 285): Add `timeout: int = 1200` parameter to signature. Change line 332 from `return await poll_job(client, base_url, api_key, job_id)` to `return await poll_job(client, base_url, api_key, job_id, timeout=timeout)`
3. `update_via_service()` (~line 340): Add `timeout: int = 1200` parameter to signature. Change line 380 from `return await poll_job(client, base_url, api_key, job_id)` to `return await poll_job(client, base_url, api_key, job_id, timeout=timeout)`
4. `process_one()` (~line 444): Add `timeout: int = 1200` parameter to signature. Pass `timeout=timeout` to every call to `ingest_via_service()` and `update_via_service()` within the function body.
5. `main()` (~line 767-780): In the `tg.create_task(process_one(...))` call, add `timeout=args.timeout` as a keyword argument.

This ensures `args.timeout` flows: `main(args.timeout)` → `process_one(timeout=)` → `ingest_via_service(timeout=)` / `update_via_service(timeout=)` → `poll_job(timeout=timeout)`.

**D. Raise httpx client timeout to 660s (~line 706-708):**
The existing `httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))` has a 300s read timeout, which is lower than the nginx proxy_read_timeout (600s). This means httpx will raise `ReadTimeout` before nginx times out, and the retry wrapper only catches `HTTPStatusError` for 5xx — not `ReadTimeout`. Change to:
```python
async with httpx.AsyncClient(
    timeout=httpx.Timeout(660.0, connect=30.0),
    follow_redirects=True,
) as client:
```
Why 660s: 10% above nginx's 600s proxy_read_timeout, ensuring nginx is always the timeout bottleneck rather than the httpx client. The poll_job loop has its own independent timeout (default 1200s) via `time.monotonic()`, so the httpx timeout only governs individual HTTP round-trips.

**E. Add retry with exponential backoff in `process_one()` (~line 478-533):**
Wrap the `async with sem:` body in a retry loop. Specifically:

```python
import random  # add to imports at top if not present

MAX_RETRIES = 3
BACKOFF_BASE = 5  # seconds

async with sem:
    last_exc = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # ... existing try body (preview, commit, poll, enrich, append result) ...
            break  # success, exit retry loop
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500 and attempt < MAX_RETRIES:
                delay = BACKOFF_BASE * (3 ** (attempt - 1))  # 5s, 15s, 45s
                jitter = delay * (0.5 + random.random())  # 50-150% of delay
                print(f"  {tag} Retry {attempt}/{MAX_RETRIES} for {layer_name} after {exc.response.status_code} (waiting {jitter:.0f}s)")
                last_exc = exc
                await asyncio.sleep(jitter)
                continue
            # Non-5xx or exhausted retries — fall through to error handling
            raise
        except Exception:
            raise  # Don't retry non-HTTP errors
    else:
        # All retries exhausted
        results.append(
            {"name": layer_name, "status": "failed", "error": f"Failed after {MAX_RETRIES} retries: {last_exc}"}
        )
        print(f"  {tag} Failed {layer_name} after {MAX_RETRIES} retries: {last_exc}")
        return
```

Keep the existing outer `except Exception as exc:` handler for non-retryable errors.

Important: Only retry on 5xx HTTP errors. Do NOT retry on 4xx (client errors) or non-HTTP exceptions. Add jitter to prevent thundering herd per research pitfall #3.
  </action>
  <verify>
    <automated>python3 -c "
import ast, sys
with open('scripts/seed-ago-data.py') as f:
    source = f.read()
tree = ast.parse(source)
checks = {
    'timeout_flag': '--timeout' in source,
    'default_concurrency_1': 'default=1' in source.split('--concurrency')[1].split('--')[0] if '--concurrency' in source else False,
    'default_timeout_1200': 'default=1200' in source,
    'retry_logic': 'MAX_RETRIES' in source and 'BACKOFF_BASE' in source,
    'jitter': 'random.random()' in source or 'random()' in source,
    'timeout_threaded_to_poll_job': 'timeout=timeout' in source,
    'timeout_in_process_one_call': 'timeout=args.timeout' in source,
    'httpx_timeout_660': '660.0' in source or 'Timeout(660' in source,
}
for k, v in checks.items():
    status = 'PASS' if v else 'FAIL'
    print(f'  {status}: {k}')
sys.exit(0 if all(checks.values()) else 1)
"</automated>
  </verify>
  <done>
- Default concurrency is 1 (was 3)
- --timeout flag exists with default 1200s
- timeout is threaded through the full call chain: main(args.timeout) -> process_one(timeout=) -> ingest_via_service(timeout=)/update_via_service(timeout=) -> poll_job(timeout=timeout)
- httpx client timeout raised to 660s (was 300s), exceeding nginx proxy_read_timeout of 600s
- 5xx errors retried up to 3 times with exponential backoff (5s, 15s, 45s base) plus random jitter
- Non-5xx and non-HTTP errors are NOT retried
- poll_job default timeout is 1200s (was 600s)
  </done>
</task>

</tasks>

<verification>
1. `grep "proxy_read_timeout" frontend/nginx.conf` shows 600s in /api/ block
2. `python3 scripts/seed-ago-data.py --help` shows --timeout and --concurrency flags with correct defaults
3. No syntax errors: `python3 -c "import ast; ast.parse(open('scripts/seed-ago-data.py').read())"`
4. `grep "timeout=timeout" scripts/seed-ago-data.py` confirms timeout threading in poll_job calls
5. `grep "timeout=args.timeout" scripts/seed-ago-data.py` confirms main passes CLI timeout to process_one
6. `grep "Timeout(660" scripts/seed-ago-data.py` confirms httpx client timeout raised
</verification>

<success_criteria>
- nginx /api/ block has proxy_read_timeout 600s, proxy_send_timeout 600s, proxy_connect_timeout 30s
- Seed script defaults: concurrency=1, timeout=1200s
- Seed script retries 5xx errors with exponential backoff + jitter (3 attempts)
- Both --timeout and --concurrency CLI flags work
- timeout is explicitly passed through every function in the call chain (no reliance on defaults)
- httpx client timeout (660s) exceeds nginx proxy_read_timeout (600s)
- No new admin UI work (dashboard already exists)
</success_criteria>

<output>
After completion, create `.planning/quick/260324-jni-investigate-and-fix-seed-ago-data-py-imp/260324-jni-SUMMARY.md`
</output>
