"""Settings used by pytest: tasks run inline and the webhook secret is fixed."""
from .settings import *  # noqa: F401,F403

CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = "memory://"
WEBHOOK_SECRET = "test-secret"
API_KEY = ""
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
