import json
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEV_SECRET_KEY = "dev-only-insecure-key-do-not-use-in-production"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
DEBUG = env_bool("DJANGO_DEBUG", True)
if not DEBUG and SECRET_KEY == DEV_SECRET_KEY:
    raise RuntimeError("Set DJANGO_SECRET_KEY when DJANGO_DEBUG is false.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
# Render tells each service its public hostname.
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "django_filters",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "core",
    "accounts",
    "billing",
    "calls",
    "outbound",
]

MIDDLEWARE = [
    "core.middleware.RequestIdMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Postgres in docker / CI, SQLite when DATABASE_URL is not set.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=60,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# whitenoise serves the admin and API docs assets straight from gunicorn.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        if DEBUG
        else "whitenoise.storage.CompressedManifestStaticFilesStorage"
    },
}

# Security headers. In production everything is https behind a proxy that sets
# X-Forwarded-Proto. DJANGO_SECURE_SSL=false turns the https-only parts off for
# running the production image locally over plain http.
SECURE_SSL = env_bool("DJANGO_SECURE_SSL", not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = SECURE_SSL
SECURE_REDIRECT_EXEMPT = [r"^api/health/$", r"^api/ready/$"]  # platform probes use http
SESSION_COOKIE_SECURE = SECURE_SSL
CSRF_COOKIE_SECURE = SECURE_SSL
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30 if SECURE_SSL else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_SSL
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS", "")

REST_FRAMEWORK = {
    # Dashboard users send a JWT; servers send an organization API key.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "accounts.authentication.ApiKeyAuthentication",
    ],
    # Deny by default: every endpoint needs a resolved organization unless it
    # opts out explicitly (signup, login, health).
    "DEFAULT_PERMISSION_CLASSES": ["accounts.tenancy.IsOrgMember"],
    "DEFAULT_PAGINATION_CLASS": "calls.pagination.StandardPagination",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": [
        "accounts.throttling.ApiKeyRateThrottle",
        "accounts.throttling.DashboardUserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "user": os.environ.get("USER_THROTTLE_RATE", "300/min"),
    },
    # How many proxies sit in front of the app (Render: 1). Used to read the
    # client IP for per-IP limits without trusting a spoofed X-Forwarded-For.
    "NUM_PROXIES": int(os.environ.get("NUM_PROXIES", "0")),
}

# Per-key limits come from the org's plan. Set this to override them for every
# key (handy for load tests).
API_KEY_THROTTLE_RATE = os.environ.get("API_KEY_THROTTLE_RATE", "")
AUTH_THROTTLE_RATE = os.environ.get("AUTH_THROTTLE_RATE", "10/min")

# Redis when available, so rate-limit counters are shared by all workers.
REDIS_URL = os.environ.get("REDIS_URL", "")
if REDIS_URL:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Largest request body Django will read at all, and the stricter webhook limit.
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
WEBHOOK_MAX_BODY_BYTES = int(os.environ.get("WEBHOOK_MAX_BODY_BYTES", str(64 * 1024)))

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(os.environ.get("JWT_ACCESS_MINUTES", "15"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(os.environ.get("JWT_REFRESH_DAYS", "7"))),
    "UPDATE_LAST_LOGIN": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "CallFlow API",
    "DESCRIPTION": (
        "Multi-tenant call analytics for voice agents. Dashboard users authenticate with a JWT "
        "(`Authorization: Bearer ...`, plus `X-Organization: <slug>` to pick a workspace). "
        "Servers use an organization API key (`X-API-Key`). Webhooks must also be HMAC-signed."
    ),
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "CallStatusEnum": "calls.models.Call.Status",
        "DeliveryStatusEnum": "outbound.models.WebhookDelivery.Status",
        "SubscriptionStatusEnum": "billing.models.Subscription.Status",
        "WebhookAckStatusEnum": ["accepted", "duplicate"],
    },
}

# The dashboard runs on another origin (localhost:5173, GitHub Pages). It sends
# Authorization and X-Organization headers, never cookies.
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_HEADERS = ["accept", "authorization", "content-type", "x-organization", "x-request-id"]
CORS_EXPOSE_HEADERS = ["x-request-id", "retry-after"]

# Celery
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL or "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

# Inbound webhooks. Each organization has its own signing secret (in the DB).
WEBHOOK_TOLERANCE_SECONDS = int(os.environ.get("WEBHOOK_TOLERANCE_SECONDS", "300"))

# Pricing: USD per 1M tokens. "default" is used for unknown models.
MODEL_PRICING = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "claude-haiku": {"input": 0.80, "output": 4.00},
    "default": {"input": 1.00, "output": 3.00},
}
if os.environ.get("MODEL_PRICING_JSON"):
    MODEL_PRICING.update(json.loads(os.environ["MODEL_PRICING_JSON"]))

TELEPHONY_COST_PER_MINUTE = os.environ.get("TELEPHONY_COST_PER_MINUTE", "0.010")

# Outbound webhooks (call.summarized and friends).
OUTBOUND_WEBHOOK_TIMEOUT_SECONDS = 5
OUTBOUND_WEBHOOK_MAX_RETRIES = int(os.environ.get("OUTBOUND_WEBHOOK_MAX_RETRIES", "5"))
OUTBOUND_WEBHOOK_BACKOFF_BASE = 30  # seconds; doubles on every retry
OUTBOUND_WEBHOOK_BACKOFF_CAP = 60 * 60
# Plain http and internal hosts are only allowed in development.
ALLOW_INSECURE_WEBHOOK_URLS = env_bool("ALLOW_INSECURE_WEBHOOK_URLS", DEBUG)

# Billing. New organizations start on this plan; see billing/providers.py for
# where a real payment provider plugs in.
DEFAULT_PLAN_CODE = "free"
BILLING_PROVIDER = os.environ.get("BILLING_PROVIDER", "billing.providers.FakeBillingProvider")

# Logging: JSON lines in production (one object per line, with request_id),
# readable text in development. LOG_FORMAT overrides either way.
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text" if DEBUG else "json")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "core.logging.RequestIdFilter"}},
    "formatters": {
        "json": {"()": "core.logging.JsonFormatter"},
        "text": {"format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "filters": ["request_id"], "formatter": LOG_FORMAT},
    },
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    "loggers": {
        # Our access log replaces Django's own per-request warnings.
        "django.request": {"level": "ERROR"},
        "django.server": {"level": "ERROR"},
    },
}

# Error tracking. Off unless SENTRY_DSN is set; no personal data is sent.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
        send_default_pii=False,
    )
