"""gunicorn settings, read from the environment so each platform can tune them."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# Render free instances have 512 MB; two sync workers fit comfortably.
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "2"))
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "30"))
graceful_timeout = 20
keepalive = 5
# Recycle workers now and then so a slow memory leak cannot grow forever.
max_requests = 1000
max_requests_jitter = 100
# The app writes its own structured access log (core.middleware).
accesslog = None
errorlog = "-"
# Trust X-Forwarded-* from the platform's proxy.
forwarded_allow_ips = "*"
