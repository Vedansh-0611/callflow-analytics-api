import hmac

from django.conf import settings
from rest_framework.permissions import BasePermission


class HasApiKeyOrOpen(BasePermission):
    """If API_KEY is configured, require it in the X-API-Key header.

    Leaving API_KEY empty keeps the read API open, which is convenient for
    local development and the demo dashboard.
    """

    def has_permission(self, request, view):
        expected = settings.API_KEY
        if not expected:
            return True
        provided = request.headers.get("X-API-Key", "")
        return hmac.compare_digest(provided, expected)
