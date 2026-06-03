"""Prometheus HTTP request instrumentator factory."""

from prometheus_fastapi_instrumentator import Instrumentator


def create_instrumentator() -> Instrumentator:
    """Create a configured Instrumentator instance.

    Excludes /metrics and /health from instrumentation to avoid
    polluting histograms with scrape/probe traffic.
    """
    return Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/health"],
        inprogress_name="http_requests_inprogress",
        inprogress_labels=True,
    )
