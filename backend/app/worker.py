"""Compatibility shim — real code moved to app.platform.jobs.worker."""

from app.platform.jobs.worker import main  # noqa: F401

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
