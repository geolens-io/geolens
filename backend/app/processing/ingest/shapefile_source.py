"""Facts about a Shapefile source that GDAL needs the caller to supply."""

import os
import zipfile
from pathlib import PurePosixPath


def zip_single_folder(file_path: str) -> str | None:
    """The one top-level folder every member of a zip lives in, else None.

    GDAL opens ``/vsizip/<archive>`` as a directory listing of its root, so a
    Shapefile set packaged inside one folder is only found through that folder.
    A ``.gdb`` folder is itself the dataset and is left at the root.
    """
    try:
        with zipfile.ZipFile(file_path) as archive:
            names = [
                n.replace("\\", "/")
                for n in archive.namelist()
                if not n.startswith("__MACOSX/")
            ]
    except (OSError, zipfile.BadZipFile):
        return None
    tops = {n.split("/", 1)[0] for n in names if n}
    if len(tops) != 1 or any("/" not in n for n in names if n):
        return None
    (top,) = tops
    return None if top.lower().endswith(".gdb") else top


def declares_dbf_encoding(file_path: str, layer_name: str | None = None) -> bool:
    """Whether a zipped or loose Shapefile states its text encoding.

    A ``.cpg`` with content, or a nonzero language-driver byte in the ``.dbf``
    header, lets GDAL recode attribute text to UTF-8 itself.
    """
    try:
        if file_path.lower().endswith(".zip"):
            with zipfile.ZipFile(file_path) as archive:
                members = {
                    n.replace("\\", "/").lower(): n
                    for n in archive.namelist()
                    if not n.endswith("/")
                }
                for lower, name in members.items():
                    stem = PurePosixPath(lower).stem
                    if lower.startswith("__macosx/") or stem.startswith("._"):
                        continue
                    if layer_name and stem != layer_name.lower():
                        continue
                    if lower.endswith((".cpg", ".dbf")):
                        with archive.open(name) as member:
                            head = member.read(32)
                        if _head_declares_encoding(lower, head):
                            return True
            return False
        base = os.path.splitext(file_path)[0]
        for ext in (".cpg", ".dbf"):
            if os.path.isfile(base + ext):
                with open(base + ext, "rb") as member:
                    if _head_declares_encoding(ext, member.read(32)):
                        return True
    except (OSError, zipfile.BadZipFile):
        return False
    return False


def _head_declares_encoding(name: str, head: bytes) -> bool:
    if name.endswith(".cpg"):
        return bool(head.strip())
    return len(head) > 29 and head[29] != 0
