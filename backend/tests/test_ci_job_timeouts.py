"""Every CI job and every apt/Playwright install step must cap its own runtime.

Runner apt-get and npm-mirror installs have blackholed nine times across
geolens-io repos in the two days before 2026-08-19, sitting 40min-6h until
someone cancelled them by hand (e.g. runs 32158035509, 32172191527,
32175407198, 32229174137). A job with no `timeout-minutes` inherits GitHub's
360-minute default; a step with none inherits whatever is left of its job's
budget. Pin both so a future job, or a future apt-get/Playwright-install
step, can't reopen the hole silently.

Deliberately broad on the step predicate: ANY step whose `run:` contains
`apt-get` gets checked, including one embedded inside a `docker build
... <<DOCKERFILE` heredoc — the base-image apt-get there is the same hang
class as a runner-level `sudo apt-get`, just one layer down.

A follow-up incident showed the step-level timeout above is necessary but
not sufficient: playwright's own `install-deps` shells out to an internal
`apt-get update && apt-get install` for font/library packages, with no
timeout of its own. On 2026-08-19 two "Install Playwright Browsers" runs
(jobs 96101445154 and 96108423519) each burned the full 10-minute step cap
stalled inside that inner apt-get, fetching fonts-freefont-ttf and
fonts-wqy-zenhei from a degraded azure.archive.ubuntu.com mirror at a few
KB/s. The retry loop around the whole step never got a second attempt,
because the step-level timeout killed it first. apt-get always reads
/etc/apt/apt.conf.d/ on startup (confirmed by reading playwright-core's
dependencies.js: it spawns a plain `apt-get update && apt-get install`
with no custom config path), so every Playwright-install step must write
per-request timeouts there before invoking `playwright install`.

The apt.conf.d write alone is still not sufficient: `Acquire::http::Timeout`
is a socket INACTIVITY timeout, not a minimum-transfer-rate one. Job
96108423519's stall was a mirror trickling a few KB/s, not a dead
connection — fonts-freefont-ttf (5.6 MB) took 5m26s to arrive, continuously,
which never trips an inactivity timeout. So every Playwright-install
invocation must ALSO be wrapped in coreutils `timeout <N>` (optionally
`timeout -k <K> <N>` for a SIGKILL grace period), with the retry loop's
total worst case kept under the step's own `timeout-minutes`, or a
slow-but-alive mirror burns the whole step on attempt 1 and the loop never
gets a second try either.

A third incident (2026-08-19, job 96120667995) showed `timeout` alone is
still not enough: it only signals its DIRECT child, and playwright's real
apt-get is a grandchild (npx -> node -> sudo -> sh -c -> apt-get) that sudo
places outside its reach. A cut attempt leaves that apt-get running and
holding the dpkg lock, so every subsequent attempt in the SAME retry loop
dies instantly with "Could not get lock /var/lib/dpkg/lock-frontend" —
observed for real: attempts 2 and 3 both failed within about a second of
starting. Every Playwright-install step must therefore clean up an orphaned
apt-get/dpkg before retrying (kill it, then wait for it to actually exit —
psmisc/fuser isn't confirmed installed on this runner image, so the wait
polls with pgrep/pkill from procps instead), and the retry budget must
account for the worst-case cost of that cleanup too.

The same mirror degradation hit the runner's OWN direct `sudo apt-get`
steps too (2026-08-19, job 96122006694, "Install system dependencies"):
apt fell back from a failing http mirror to an https one, then produced
ZERO further output for the rest of the 10-minute step cap. Our existing
`-o Acquire::http::Timeout=30` only covers the http method; the https
fallback was unbounded. Every direct apt-get invocation (update and
install, each wrapped separately) now also sets
`Acquire::https::Timeout`, and is wrapped in its own `sudo timeout -k <K>
<N>` — apt-get is timeout's DIRECT child here (no sudo/shell layer between
them), but the same orphan risk still exists one level down if timeout
kills apt-get mid-unpack of a dpkg child, so these steps get the same
cleanup-between-attempts block as the Playwright-install steps.
"""

import pathlib
import re

import yaml

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
PROD_SMOKE = (
    pathlib.Path(__file__).resolve().parents[2]
    / ".github"
    / "workflows"
    / "prod-smoke.yml"
)

_PLAYWRIGHT_INSTALL = re.compile(r"playwright\s+install", re.IGNORECASE)
# Captures the echoed apt.conf directives (group 1) and the target path
# (group 2), not just a bare mention of the directory — a step could
# reference /etc/apt/apt.conf.d/ in passing without actually writing a
# useful file there.
_APT_CONF_D_WRITE = re.compile(r"echo\s+'([^']*)'\s*\\?\s*\|\s*sudo\s+tee\s+(\S+)")
_REQUIRED_APT_CONF_DIRECTIVES = (
    "Acquire::http::Timeout",
    "Acquire::https::Timeout",
    "Acquire::Retries",
)
# Optional `-k <K>` grace period ahead of the required `<N>` duration.
_TIMEOUT_WRAPPED_PLAYWRIGHT_INSTALL = re.compile(
    r"\btimeout\s+(?:-k\s+(\d+)\s+)?(\d+)\s+\S.*playwright\s+install", re.IGNORECASE
)
# Flat character class, not `(?:\d+\s*)+` — a nested quantifier over an
# optional-whitespace group backtracks exponentially on adversarial input
# (CodeQL py/redos, alert 80). `[\d\s]+` is linear: a single top-level `+`.
# `.search()` returns the FIRST match, i.e. the outer retry loop
# (`for i in ...`) — the cleanup poll loop uses a distinct variable name
# and is matched separately by _CLEANUP_POLL_LOOP below.
_FOR_LOOP_ATTEMPTS = re.compile(r"for\s+\w+\s+in\s+([\d\s]+);\s*do")
# The bounded lock-wait loop inside the cleanup block: `for _ in ...; do
# ... done`. DOTALL so `.` spans the loop body's newlines; captures both
# the iteration count and the body text (to find its own `sleep <N>`,
# distinct from the cleanup block's two FIXED sleeps outside the loop).
_CLEANUP_POLL_LOOP = re.compile(
    r"for\s+_\s+in\s+([\d\s]+);\s*do(.*?)\bdone\b", re.IGNORECASE | re.DOTALL
)
_SLEEP_SECONDS = re.compile(r"\bsleep\s+(\d+)\b")
_PKILL_APT_GET = re.compile(r"\bpkill\b[^\n]*-x\s+apt-get\b")
_PKILL_DPKG = re.compile(r"\bpkill\b[^\n]*-x\s+dpkg\b")
# Separate patterns, not one apt-get|dpkg alternation: the real poll line
# checks BOTH process names independently (`pgrep -x apt-get >/dev/null ||
# pgrep -x dpkg >/dev/null || break`), and an alternation would still
# match with either branch deleted.
_PGREP_APT_GET = re.compile(r"\bpgrep\b[^\n]*-x\s+apt-get\b")
_PGREP_DPKG = re.compile(r"\bpgrep\b[^\n]*-x\s+dpkg\b")
_DPKG_CONFIGURE_TIMEOUT_WRAPPED = re.compile(
    r"\btimeout\s+(?:-k\s+(\d+)\s+)?(\d+)\s+dpkg\s+--configure\s+-a\b"
)

# A REAL apt-get invocation — "update"/"install" as the immediate
# subcommand, only preceded by `-o <opt>` flags — as opposed to a bare
# mention of the string "apt-get" as a `pkill -x apt-get` / `pgrep -x
# apt-get` process-name argument (which the Playwright-install steps'
# cleanup block also contains, but never actually runs apt-get itself).
_APT_GET_INVOCATION = re.compile(r"\bapt-get(?:\s+-o\s+\S+)*\s+(?:update|install)\b")
# Same, but requires a `timeout [-k <K>] <N>` immediately in front, and
# captures the whole invocation (including its -o flags) in group(3) so
# the caller can check which Acquire options it carries.
_APT_GET_TIMEOUT_WRAPPED = re.compile(
    r"\btimeout\s+(?:-k\s+(\d+)\s+)?(\d+)\s+(apt-get(?:\s+-o\s+\S+)*\s+(?:update|install))\b"
)


def _workflow(path: pathlib.Path = CI) -> dict:
    return yaml.safe_load(path.read_text())


def _without_comment_lines(run: str) -> str:
    """Drop full-line `#` comments before counting real invocations.

    The incident write-ups in these steps' own comments say things like
    "apt-get update" and "apt-get install" in prose, which would otherwise
    look like actual invocations to a naive substring/regex scan. Every
    comment in these steps is its own line (no trailing `# ...` after real
    code), so a strip-by-line is exact for this file, not a general bash
    parser.
    """
    return "\n".join(
        line for line in run.splitlines() if not line.strip().startswith("#")
    )


def test_every_job_has_a_timeout():
    jobs = _workflow()["jobs"]
    missing = sorted(name for name, job in jobs.items() if "timeout-minutes" not in job)
    assert not missing, f"jobs missing timeout-minutes: {missing}"


def test_every_apt_or_playwright_install_step_has_a_step_timeout():
    jobs = _workflow()["jobs"]
    offenders = []
    for job_name, job in jobs.items():
        for step in job.get("steps", []):
            run = step.get("run")
            if not run:
                continue
            if "apt-get" in run or _PLAYWRIGHT_INSTALL.search(run):
                if "timeout-minutes" not in step:
                    offenders.append(f"{job_name}: {step.get('name', '<unnamed>')}")
    assert not offenders, (
        f"apt/Playwright install steps missing a step-level timeout-minutes: {offenders}"
    )


def test_every_playwright_install_step_bounds_its_inner_apt_get():
    offenders = []
    for path in (CI, PROD_SMOKE):
        jobs = _workflow(path)["jobs"]
        for job_name, job in jobs.items():
            for step in job.get("steps", []):
                run = step.get("run")
                if not run or not _PLAYWRIGHT_INSTALL.search(run):
                    continue
                label = f"{path.name}/{job_name}: {step.get('name', '<unnamed>')}"
                code = _without_comment_lines(run)

                write_match = _APT_CONF_D_WRITE.search(code)
                if not write_match:
                    offenders.append(f"{label}: no apt.conf.d file write found")
                    continue
                write_target = write_match.group(2)
                if not write_target.startswith("/etc/apt/apt.conf.d/"):
                    offenders.append(
                        f"{label}: write target `{write_target}` is not under "
                        "/etc/apt/apt.conf.d/"
                    )
                    continue
                directives = write_match.group(1)
                missing = [
                    d for d in _REQUIRED_APT_CONF_DIRECTIVES if d not in directives
                ]
                if missing:
                    offenders.append(
                        f"{label}: apt.conf.d write is missing directive(s) {missing}"
                    )
                    continue

                playwright_match = _PLAYWRIGHT_INSTALL.search(code)
                if playwright_match and write_match.start() >= playwright_match.start():
                    offenders.append(
                        f"{label}: apt.conf.d write does not precede `playwright install`"
                    )
    assert not offenders, (
        f"Playwright-install steps not correctly bounding their inner apt-get: {offenders}"
    )


def _cleanup_budget_seconds(run: str) -> tuple[int | None, str | None]:
    """Worst-case seconds a single cleanup-between-attempts block can take.

    Returns (seconds, None) on success, or (None, reason) if the run text
    doesn't have the expected shape. Requires actual evidence of the
    orphan-kill sequence, not just any bounded loop with a sleep: a
    `pkill` targeting apt-get, one targeting dpkg, a bounded poll loop
    that itself checks apt-get/dpkg via `pgrep`, and a timeout-wrapped
    `dpkg --configure -a` (whose own -k grace counts toward the budget
    the same way a Playwright-install attempt's does). A cleanup block
    that dropped the kill commands but kept an unrelated bounded loop
    would otherwise still look bounded to a looser check.

    The two FIXED sleeps (post-TERM, before the final retry) are whatever
    text is left in `run` once the poll loop's own span AND the
    dpkg-configure invocation are cut out, so a stray unrelated `sleep`
    elsewhere in the step would corrupt this — none of the seven steps
    this covers has one, but a future edit that adds one should widen
    this rather than trust the subtraction blindly.
    """
    if not _PKILL_APT_GET.search(run):
        return None, "cleanup has no `pkill ... -x apt-get`"
    if not _PKILL_DPKG.search(run):
        return None, "cleanup has no `pkill ... -x dpkg`"

    poll_match = _CLEANUP_POLL_LOOP.search(run)
    if not poll_match:
        return None, "no bounded cleanup poll loop (`for _ in ...; do ... done`)"
    if not _PGREP_APT_GET.search(poll_match.group(2)):
        return None, "cleanup poll loop doesn't check apt-get via `pgrep`"
    if not _PGREP_DPKG.search(poll_match.group(2)):
        return None, "cleanup poll loop doesn't check dpkg via `pgrep`"
    poll_iterations = len(poll_match.group(1).split())
    poll_sleep_match = _SLEEP_SECONDS.search(poll_match.group(2))
    if not poll_sleep_match:
        return None, "cleanup poll loop has no `sleep <N>`"
    poll_sleep_seconds = int(poll_sleep_match.group(1))

    configure_match = _DPKG_CONFIGURE_TIMEOUT_WRAPPED.search(run)
    if not configure_match:
        return None, "cleanup has no timeout-wrapped `dpkg --configure -a`"
    configure_seconds = int(configure_match.group(2)) + int(
        configure_match.group(1) or 0
    )

    outside_text = run[: poll_match.start()] + run[poll_match.end() :]
    fixed_sleep_seconds = sum(int(m) for m in _SLEEP_SECONDS.findall(outside_text))

    return (
        fixed_sleep_seconds + poll_iterations * poll_sleep_seconds + configure_seconds,
        None,
    )


def test_every_playwright_install_attempt_fits_the_step_timeout_budget():
    offenders = []
    for path in (CI, PROD_SMOKE):
        jobs = _workflow(path)["jobs"]
        for job_name, job in jobs.items():
            for step in job.get("steps", []):
                run = step.get("run")
                if not run or not _PLAYWRIGHT_INSTALL.search(run):
                    continue
                label = f"{path.name}/{job_name}: {step.get('name', '<unnamed>')}"
                code = _without_comment_lines(run)

                timeout_match = _TIMEOUT_WRAPPED_PLAYWRIGHT_INSTALL.search(code)
                if not timeout_match:
                    offenders.append(
                        f"{label}: no `timeout <N>` wraps the playwright install"
                    )
                    continue
                kill_grace_seconds = int(timeout_match.group(1) or 0)
                base_timeout_seconds = int(timeout_match.group(2))
                per_attempt_seconds = base_timeout_seconds + kill_grace_seconds

                attempts_match = _FOR_LOOP_ATTEMPTS.search(code)
                attempts = len(attempts_match.group(1).split()) if attempts_match else 1

                cleanup_seconds, cleanup_error = _cleanup_budget_seconds(code)
                if cleanup_error:
                    offenders.append(f"{label}: {cleanup_error}")
                    continue

                worst_case_seconds = (
                    attempts * per_attempt_seconds
                    + max(attempts - 1, 0) * cleanup_seconds
                )
                step_cap_seconds = step.get("timeout-minutes", 0) * 60
                if worst_case_seconds >= step_cap_seconds:
                    offenders.append(
                        f"{label}: {attempts} attempts * {per_attempt_seconds}s + "
                        f"{max(attempts - 1, 0)} cleanups * {cleanup_seconds}s = "
                        f"{worst_case_seconds}s >= step cap {step_cap_seconds}s"
                    )
    assert not offenders, (
        f"Playwright-install retry budget does not fit its step cap: {offenders}"
    )


def test_every_direct_apt_get_invocation_is_bounded_and_fits_its_step_cap():
    """Runner-level `sudo apt-get` steps: excludes the Dockerfile-heredoc
    ones (`docker build ... <<'DOCKERFILE'`), which have no retry loop of
    their own and aren't in scope here — they stay on the step-level-only
    guarantee from test_every_apt_or_playwright_install_step_has_a_step_timeout.
    """
    offenders = []
    jobs = _workflow(CI)["jobs"]
    for job_name, job in jobs.items():
        for step in job.get("steps", []):
            run = step.get("run")
            if not run or "<<'DOCKERFILE'" in run:
                continue
            code = _without_comment_lines(run)
            invocations = _APT_GET_INVOCATION.findall(code)
            if not invocations:
                continue
            label = f"{job_name}: {step.get('name', '<unnamed>')}"

            wrapped = _APT_GET_TIMEOUT_WRAPPED.findall(code)
            if len(wrapped) != len(invocations):
                offenders.append(
                    f"{label}: {len(invocations)} apt-get invocation(s), only "
                    f"{len(wrapped)} wrapped in `timeout <N>`"
                )
                continue

            per_attempt_seconds = 0
            missing_acquire_flag = False
            for kill_grace, base_timeout, invocation_text in wrapped:
                if "Acquire::http::Timeout" not in invocation_text:
                    offenders.append(
                        f"{label}: `{invocation_text}` has no Acquire::http::Timeout"
                    )
                    missing_acquire_flag = True
                if "Acquire::https::Timeout" not in invocation_text:
                    offenders.append(
                        f"{label}: `{invocation_text}` has no Acquire::https::Timeout"
                    )
                    missing_acquire_flag = True
                per_attempt_seconds += int(base_timeout) + int(kill_grace or 0)
            if missing_acquire_flag:
                continue

            attempts_match = _FOR_LOOP_ATTEMPTS.search(code)
            attempts = len(attempts_match.group(1).split()) if attempts_match else 1

            cleanup_seconds, cleanup_error = _cleanup_budget_seconds(code)
            if cleanup_error:
                offenders.append(f"{label}: {cleanup_error}")
                continue

            worst_case_seconds = (
                attempts * per_attempt_seconds + max(attempts - 1, 0) * cleanup_seconds
            )
            step_cap_seconds = step.get("timeout-minutes", 0) * 60
            if worst_case_seconds >= step_cap_seconds:
                offenders.append(
                    f"{label}: {attempts} attempts * {per_attempt_seconds}s + "
                    f"{max(attempts - 1, 0)} cleanups * {cleanup_seconds}s = "
                    f"{worst_case_seconds}s >= step cap {step_cap_seconds}s"
                )
    assert not offenders, f"direct apt-get retry budget/coverage problem: {offenders}"
