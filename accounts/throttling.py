"""Rate limits. Counters live in the Django cache, which is Redis in production,
so every gunicorn worker and every instance shares the same budget."""
from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from billing.services import get_plan

from .models import ApiKey


class ApiKeyRateThrottle(SimpleRateThrottle):
    """Requests per minute for each API key, as allowed by the org's plan.

    Requests made without an API key are not counted here.
    """

    scope = "api_key"

    def get_rate(self):
        # Placeholder; the real rate depends on the request (see allow_request).
        return settings.API_KEY_THROTTLE_RATE or "60/min"

    def allow_request(self, request, view):
        if not isinstance(request.auth, ApiKey):
            return True
        plan = get_plan(request.auth.organization)
        # Settings are read per request so an override applies without a restart.
        self.rate = settings.API_KEY_THROTTLE_RATE or f"{plan.api_requests_per_minute}/min"
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
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
