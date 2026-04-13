"""Structured logging configuration using structlog with stdlib bridge."""

import logging

import structlog


_SENSITIVE_KEYS = frozenset({"api_key", "password", "token", "secret", "authorization"})


def _redact_sensitive_keys(
    _logger: object, _method: str, event_dict: dict[str, object]
) -> dict[str, object]:
    """Replace values of sensitive keys with '***'."""
    for key in _SENSITIVE_KEYS & event_dict.keys():
        event_dict[key] = "***"
    return event_dict


def setup_logging(json_logs: bool = False, log_level: str = "INFO") -> None:
    """Configure structlog + stdlib logging with shared processor chain.

    Args:
        json_logs: If True, render logs as JSON (production). Otherwise use
            colored console output (development).
        log_level: Root log level (e.g. "DEBUG", "INFO", "WARNING").
    """
    shared_processors: list[structlog.types.Processor] = [
        _redact_sensitive_keys,
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.stdlib.ExtraAdder(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]

    if json_logs:
        # In JSON mode, format exceptions as strings inside the JSON object.
        # ConsoleRenderer handles tracebacks itself in dev mode.
        shared_processors.append(structlog.processors.format_exc_info)

    structlog.configure(
        processors=shared_processors
        + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    log_renderer: structlog.types.Processor
    if json_logs:
        log_renderer = structlog.processors.JSONRenderer()
    else:
        log_renderer = structlog.dev.ConsoleRenderer()

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            log_renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    # Route uvicorn and uvicorn.error through root logger
    for _log in ("uvicorn", "uvicorn.error"):
        logging.getLogger(_log).handlers.clear()
        logging.getLogger(_log).propagate = True

    # Suppress uvicorn.access entirely -- our middleware replaces it
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
