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
"""

import pathlib
import re

import yaml

CI = pathlib.Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"

_PLAYWRIGHT_INSTALL = re.compile(r"playwright\s+install", re.IGNORECASE)


def _workflow() -> dict:
    return yaml.safe_load(CI.read_text())


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
