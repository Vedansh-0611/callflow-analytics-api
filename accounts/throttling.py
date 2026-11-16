"""Rate limits. Counters live in the Django cache, which is Redis in production,
so every gunicorn worker and every instance shares the same budget."""
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from .models import ApiKey


class ApiKeyRateThrottle(SimpleRateThrottle):
    """Requests per minute for each API key. Other requests are not counted here."""

    scope = "api_key"

    def get_rate(self):
        # Read at request time (DRF caches its settings at import), so the
        # limit can be changed per environment and per test.
        return settings.API_KEY_THROTTLE_RATE

    def get_cache_key(self, request, view):
        if not isinstance(request.auth, ApiKey):
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.auth.pk}


class DashboardUserRateThrottle(UserRateThrottle):
    """Per-user limit for dashboard traffic. API key traffic has its own throttle."""

    def get_cache_key(self, request, view):
        if isinstance(request.auth, ApiKey):
            return None
        return super().get_cache_key(request, view)


class AuthRateThrottle(SimpleRateThrottle):
    """Per-IP limit on signup and login, to slow down password guessing."""

    scope = "auth"

    def get_rate(self):
        return settings.AUTH_THROTTLE_RATE

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
