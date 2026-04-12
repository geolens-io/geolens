"""Request body size limit middleware.

Rejects requests whose body exceeds the configured maximum, returning
413 Payload Too Large. Handles both Content-Length and chunked
Transfer-Encoding requests via stream byte counting.
"""

from starlette.responses import JSONResponse


class RequestBodyLimitMiddleware:
    """Enforce body size limit on both Content-Length and chunked-encoding requests."""

    def __init__(self, app, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Fast path: Content-Length header present — reject before reading the body
        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                length = int(content_length)
            except ValueError:
                pass  # Malformed Content-Length — let downstream handle it
            else:
                if length > self.max_bytes:
                    response = JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                f"Request body too large. "
                                f"Maximum allowed size is {self.max_bytes} bytes."
                            )
                        },
                    )
                    await response(scope, receive, send)
                    return

        # Stream-counting path: chunked Transfer-Encoding or missing Content-Length.
        # Wrap the receive callable to count bytes as they arrive.
        total_read = 0
        max_bytes = self.max_bytes
        limit_exceeded = False

        async def limited_receive():
            nonlocal total_read, limit_exceeded
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                total_read += len(body)
                if total_read > max_bytes:
                    limit_exceeded = True
                    # Return an empty final chunk so the app sees EOF
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def sending(message):
            if limit_exceeded and message.get("type") == "http.response.start":
                # Override the response with 413 before headers are sent
                error_response = JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large. "
                            f"Maximum allowed size is {self.max_bytes} bytes."
                        )
                    },
                )
                await error_response(scope, receive, send)
                return
            if not limit_exceeded:
                await send(message)

        await self.app(scope, limited_receive, sending)
