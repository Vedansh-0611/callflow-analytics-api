"""A request id that follows one request through the logs, including into the
Celery tasks it enqueues."""
import contextvars
import uuid

_request_id = contextvars.ContextVar("request_id", default="-")

HEADER = "X-Request-ID"


def get_request_id():
    return _request_id.get()


def set_request_id(value):
    return _request_id.set(value)


def reset_request_id(token):
    _request_id.reset(token)


def new_request_id():
    return uuid.uuid4().hex


def clean_incoming(value):
    """Accept the caller's id (e.g. from a load balancer) if it looks sane."""
    if value and len(value) <= 64 and all(c.isalnum() or c in "-_." for c in value):
        return value
    return None
