"""Rules for a caller's filename before it becomes part of a storage key or path.

In ``platform/`` because the catalog's re-upload doors and the ingest doors
both key staging objects on the name.
"""

from pathlib import Path

from fastapi import HTTPException, status


def safe_upload_basename(filename: str | None) -> str:
    """The filename stripped to a basename, which is the only form safe to key on.

    A name carrying path separators would otherwise split the derivation: the
    logical URI would keep the directory while the write basenamed it, so
    cleanup would track a key nobody wrote.
    """
    return Path(filename or "").name or "upload"


def refuse_control_characters(filename: str) -> None:
    """422 for a filename holding NUL or another control character.

    Such a name passes every suffix and allowlist check and fails only when
    storage or the filesystem is asked to open it, after the job exists.
    """
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "filename_control_characters",
                "message": "Filename contains control characters that are not allowed.",
            },
        )
