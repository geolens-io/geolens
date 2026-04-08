"""Storage provider abstraction.

Pluggable file storage with `local` (filesystem) and `s3` (S3-compatible)
implementations selected by the `STORAGE_PROVIDER` environment variable. Used
for uploaded source files, exports, and the raster asset store.
"""

from app.storage.provider import StorageProvider, get_storage, init_storage

__all__ = ["StorageProvider", "get_storage", "init_storage"]
