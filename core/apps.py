from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        from . import celery_signals, schema  # noqa: F401  (signal handlers, OpenAPI auth extension)
