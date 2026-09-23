"""A queued replacement job resolves to the same task and binds the same arguments."""

import inspect
from dataclasses import dataclass

import pytest

# The worker builds its task registry through this import.
from app.processing.ingest.tasks import task_app

_REQUIRED = inspect.Parameter.empty
_ARG = inspect.Parameter.POSITIONAL_OR_KEYWORD
_KWARGS = ("kwargs", inspect.Parameter.VAR_KEYWORD, _REQUIRED)

_SERVICE_PARAMETERS = (
    ("job_id", _ARG, _REQUIRED),
    ("dataset_id", _ARG, _REQUIRED),
    ("source_url", _ARG, _REQUIRED),
    ("source_layer", _ARG, _REQUIRED),
    ("user_id", _ARG, _REQUIRED),
    ("attempt_id", _ARG, None),
    ("token", _ARG, None),
    ("credential_ref", _ARG, None),
    _KWARGS,
)


@dataclass(frozen=True)
class _Contract:
    aliases: tuple[str, ...]
    queue: str
    pass_context: bool
    parameters: tuple[tuple[str, object, object], ...]


_CONTRACTS = {
    "app.processing.ingest.tasks_reupload.reupload_file": _Contract(
        aliases=("app.ingest.tasks.reupload_file",),
        queue="ingest",
        pass_context=False,
        parameters=(
            ("job_id", _ARG, _REQUIRED),
            ("dataset_id", _ARG, _REQUIRED),
            ("file_path", _ARG, _REQUIRED),
            ("user_id", _ARG, _REQUIRED),
            ("attempt_id", _ARG, None),
            _KWARGS,
        ),
    ),
    "app.processing.ingest.tasks_reupload.reupload_service": _Contract(
        aliases=("app.ingest.tasks.reupload_service",),
        queue="ingest",
        pass_context=True,
        parameters=_SERVICE_PARAMETERS,
    ),
    "app.ingest.tasks.reupload_verified_refresh": _Contract(
        aliases=(),
        queue="ingest",
        pass_context=True,
        parameters=_SERVICE_PARAMETERS,
    ),
    "app.processing.ingest.tasks_raster_replace.reupload_raster": _Contract(
        aliases=(),
        queue="raster",
        pass_context=False,
        parameters=(
            ("job_id", _ARG, _REQUIRED),
            ("dataset_id", _ARG, _REQUIRED),
            ("file_path", _ARG, _REQUIRED),
            ("user_id", _ARG, _REQUIRED),
            ("attempt_id", _ARG, None),
            _KWARGS,
        ),
    ),
    "app.processing.ingest.tasks_postgis_refresh.refresh_postgis": _Contract(
        aliases=(),
        queue="ingest",
        pass_context=False,
        parameters=(
            ("job_id", _ARG, _REQUIRED),
            ("dataset_id", _ARG, _REQUIRED),
            ("attempt_id", _ARG, None),
            _KWARGS,
        ),
    ),
    "app.processing.ingest.tasks_stac_refresh.refresh_stac": _Contract(
        aliases=(),
        queue="ingest",
        pass_context=False,
        parameters=(
            ("job_id", _ARG, _REQUIRED),
            ("dataset_id", _ARG, _REQUIRED),
            ("attempt_id", _ARG, None),
            ("credential_ref", _ARG, None),
            _KWARGS,
        ),
    ),
}

_NAMES = pytest.mark.parametrize(
    "name", sorted(_CONTRACTS), ids=lambda name: name.rsplit(".", 1)[-1]
)


@_NAMES
def test_every_registered_key_resolves_to_its_task(name: str) -> None:
    """The task's name and each alias it registers resolve to that one task."""
    task = task_app.tasks[name]
    assert task.name == name
    assert tuple(task.aliases) == _CONTRACTS[name].aliases
    for alias in task.aliases:
        assert task_app.tasks[alias] is task


@_NAMES
def test_each_task_keeps_its_queue_retry_and_context(name: str) -> None:
    """Each task keeps its queue, runs once without retry and keeps its context flag."""
    task = task_app.tasks[name]
    contract = _CONTRACTS[name]
    assert task.queue == contract.queue
    assert task.retry_strategy is None
    assert task.pass_context is contract.pass_context


@_NAMES
def test_each_task_accepts_the_same_arguments(name: str) -> None:
    """Each task binds the same parameter names, kinds and defaults."""
    # Follows __wrapped__ through the task decorators to the function that
    # binds the queued row's kwargs.
    signature = inspect.signature(task_app.tasks[name].func)
    assert (
        tuple((p.name, p.kind, p.default) for p in signature.parameters.values())
        == _CONTRACTS[name].parameters
    )


def test_the_verified_refresh_name_runs_the_service_task() -> None:
    """The verified-refresh name runs the same function as the service re-upload."""
    verified = task_app.tasks["app.ingest.tasks.reupload_verified_refresh"]
    service = task_app.tasks["app.processing.ingest.tasks_reupload.reupload_service"]
    assert verified.func is service.func
