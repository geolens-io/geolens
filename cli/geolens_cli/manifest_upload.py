# SPDX-License-Identifier: Apache-2.0
"""Upload the local files a version 2 manifest names, before `geolens apply`."""

from __future__ import annotations

import copy
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID
from urllib.parse import urlsplit

import typer

from ._sdk_helpers import EXIT_USAGE, call_sdk, detail_text, unwrap
from .manifest.schema import names_unuploaded_source

_REMOTE_URI_SCHEMES = frozenset({"http", "https", "s3"})
_READ_CHUNK = 1024 * 1024


class ManifestUploadError(Exception):
    """A local source can't be uploaded; nothing has been sent yet."""

    def __init__(
        self, message: str, *, exit_code: int = EXIT_USAGE, printed: bool = False
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        # True when the message is already on stderr.
        self.printed = printed


@dataclass(frozen=True)
class LocalUpload:
    """A source to upload: its place in the manifest, and the file it names."""

    dataset_index: int
    source_index: int
    path: Path
    checksum: str


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_CHUNK):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def plan_local_uploads(
    document: Mapping[str, Any], base_dir: Path
) -> list[LocalUpload]:
    """Find every local file the document names and check it before any upload.

    Paths resolve against ``base_dir`` (the manifest's folder) and must stay
    inside it once symlinks are resolved: an absolute path or a `..` escape is
    refused, so a manifest from someone else can't send files from elsewhere.
    Remote URLs are sent as they are. A declared checksum that disagrees with the file is
    refused, since the server would refuse the upload for the same reason.
    """

    uploads: list[LocalUpload] = []
    root = base_dir.resolve()
    datasets = document.get("datasets")
    if not isinstance(datasets, list):
        return uploads
    for d_index, dataset in enumerate(datasets):
        sources = dataset.get("sources") if isinstance(dataset, Mapping) else None
        if not isinstance(sources, list):
            continue
        for s_index, source in enumerate(sources):
            if not isinstance(source, Mapping) or not names_unuploaded_source(source):
                continue
            uri = source["uri"]
            where = f"dataset {dataset.get('key')!r} source {s_index}"
            try:
                scheme = urlsplit(uri).scheme.lower()
            except ValueError as exc:
                raise ManifestUploadError(
                    f"{where}: {uri!r} is not a valid URI ({exc})."
                ) from exc
            if scheme in _REMOTE_URI_SCHEMES:
                continue
            try:
                path = (root / uri).resolve()
            except (OSError, RuntimeError) as exc:
                # Before Python 3.13 a symlink loop raises RuntimeError here.
                raise ManifestUploadError(
                    f"{where}: could not resolve {uri!r} ({exc})."
                ) from exc
            if Path(uri).is_absolute() or not path.is_relative_to(root):
                raise ManifestUploadError(
                    f"{where}: {uri!r} is outside the manifest folder {root}. "
                    "Move the file into that folder or point to it with a "
                    "relative path inside it."
                )
            if not path.is_file():
                raise ManifestUploadError(
                    f"Source file not found: {path} "
                    f"(datasets[{d_index}].sources[{s_index}].uri)."
                )
            try:
                checksum = file_checksum(path)
            except OSError as exc:
                raise ManifestUploadError(f"Could not read {path}: {exc}") from exc
            declared = source.get("checksum")
            if declared is not None and declared != checksum:
                raise ManifestUploadError(
                    f"{path} does not match the checksum declared in "
                    f"datasets[{d_index}].sources[{s_index}] "
                    f"(declared {declared}, file is {checksum}). "
                    "Remove the checksum or update it."
                )
            uploads.append(LocalUpload(d_index, s_index, path, checksum))
    return uploads


def upload_local_sources(
    client: Any,
    document: Mapping[str, Any],
    uploads: list[LocalUpload],
    *,
    on_progress: Callable[[int, int, Path], None] | None = None,
    created: list[UUID] | None = None,
    owners: dict[UUID, str] | None = None,
) -> dict[str, Any]:
    """Upload each file and return a copy of the document naming the uploads.

    Each source becomes ``upload:<job_id>`` with the file's checksum. A failed
    upload exits with the code `publish` uses for the same failure. Each upload's
    job id is appended to ``created`` as it is made, and ``owners`` maps it to the
    dataset key whose entry uses it, so a caller can tell which the apply used.
    """

    if created is None:
        created = []
    if owners is None:
        owners = {}

    from . import publish as _publish

    staged = copy.deepcopy(dict(document))
    # YAML aliases load as one shared object, and deepcopy keeps the sharing, so
    # rewriting one entry's source would rewrite every entry that aliases it.
    for dataset in staged.get("datasets", []):
        if isinstance(dataset, dict) and isinstance(dataset.get("sources"), list):
            dataset["sources"] = [copy.deepcopy(item) for item in dataset["sources"]]
    for number, upload in enumerate(uploads, start=1):
        if on_progress is not None:
            on_progress(number, len(uploads), upload.path)
        response = call_sdk(_publish.upload_file, client=client, path=upload.path)
        try:
            parsed = unwrap(response, expected=_publish.UPLOAD_OK_STATUS)
        except typer.Exit as exc:
            # unwrap printed the reason; a JSON report needs it too.
            detail = getattr(response.parsed, "detail", None)
            reason = f": {detail_text(detail)}" if detail is not None else ""
            raise ManifestUploadError(
                f"Upload of {upload.path.name} failed "
                f"({int(response.status_code)}){reason}",
                exit_code=exc.exit_code,
                printed=True,
            ) from None
        job_id = getattr(parsed, "job_id", None)
        if job_id is None:
            raise ManifestUploadError(
                f"Upload of {upload.path} did not return a job_id.", exit_code=1
            )
        source = staged["datasets"][upload.dataset_index]["sources"][
            upload.source_index
        ]
        source["uri"] = f"upload:{job_id}"
        source["checksum"] = upload.checksum
        created.append(UUID(str(job_id)))
        owners[created[-1]] = str(staged["datasets"][upload.dataset_index].get("key"))
    return staged


_UNUSED_UPLOAD_MARKER = "cancel the unused upload"


def sort_uploads(
    response: Mapping[str, Any],
    created: list[UUID],
    owners: Mapping[UUID, str],
    *,
    dry_run: bool,
) -> tuple[list[UUID], list[UUID]]:
    """Split the uploads this run made into (to cancel, to keep and report).

    An upload is cancelled only when the outcome proves the server never used
    it: a dry run, or an entry answered `skip` with the server's unused-upload
    message. An upload an entry queued is in use and is neither. Everything
    else, an `error` included, is kept and listed, since a lost queue
    acknowledgement can answer `error` for an upload a worker already runs.
    """

    if dry_run:
        return list(created), []
    results = {
        str(r.get("dataset_key")): r
        for r in response.get("results") or []
        if isinstance(r, Mapping)
    }
    cancel: list[UUID] = []
    keep: list[UUID] = []
    for job_id in created:
        result = results.get(owners.get(job_id, ""))
        if result is None:
            keep.append(job_id)
        elif result.get("action") in {"create", "update"} and str(
            result.get("job_id")
        ) == str(job_id):
            continue
        elif (
            result.get("action") == "skip"
            and _UNUSED_UPLOAD_MARKER in str(result.get("message", "")).lower()
        ):
            cancel.append(job_id)
        else:
            keep.append(job_id)
    return cancel, keep


def cancel_uploads(client: Any, job_ids: list[UUID]) -> tuple[list[UUID], list[UUID]]:
    """Cancel unused uploads. Returns (cancelled, failed); never raises."""

    from geolens.api.admin import cancel_job_jobs_job_id_cancel_post as _cancel

    cancelled: list[UUID] = []
    failed: list[UUID] = []
    for job_id in job_ids:
        try:
            response = call_sdk(_cancel.sync_detailed, client=client, job_id=job_id)
            ok = int(response.status_code) == 200
        except (
            Exception
        ):  # broad: cleanup is best-effort and must not change the apply outcome
            ok = False
        (cancelled if ok else failed).append(job_id)
    return cancelled, failed
