"""Settings used by pytest: tasks run inline, passwords hash fast."""
from .settings import *  # noqa: F401,F403

CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
