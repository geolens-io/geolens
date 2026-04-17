"""Compatibility shim — real code moved to app.platform.jobs.worker."""

from app.platform.jobs.worker import *  # noqa: F403

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
