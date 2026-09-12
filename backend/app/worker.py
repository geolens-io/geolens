"""Container worker entry point delegating to the jobs runtime."""

from app.platform.jobs.worker import main

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
