import logging
import time

from .request_id import HEADER, clean_incoming, new_request_id, reset_request_id, set_request_id

access_log = logging.getLogger("callflow.access")


class RequestIdMiddleware:
    """Tag every log line with a request id, echo it back in X-Request-ID,
    and write one structured access log line per request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = clean_incoming(request.headers.get(HEADER)) or new_request_id()
        token = set_request_id(request_id)
        started = time.perf_counter()
        try:
            response = self.get_response(request)
            response[HEADER] = request_id
            org = getattr(request, "organization_id_for_logs", None)
            access_log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "org": org,
                },
            )
            return response
        finally:
            reset_request_id(token)
