"""Carry the request id from the web process into Celery tasks, so the logs of
a webhook and of the task it triggered share one id."""
from celery.signals import before_task_publish, task_postrun, task_prerun

from .request_id import get_request_id, new_request_id, reset_request_id, set_request_id

_tokens = {}


@before_task_publish.connect
def add_request_id_header(headers=None, **kwargs):
    if headers is not None and get_request_id() != "-":
        headers["request_id"] = get_request_id()


@task_prerun.connect
def restore_request_id(task_id=None, task=None, **kwargs):
    current = get_request_id()
    # Workers get it from the message header; eager tasks already have it.
    request_id = getattr(task.request, "request_id", None) or (current if current != "-" else new_request_id())
    _tokens[task_id] = set_request_id(request_id)


@task_postrun.connect
def clear_request_id(task_id=None, **kwargs):
    token = _tokens.pop(task_id, None)
    if token is not None:
        reset_request_id(token)
