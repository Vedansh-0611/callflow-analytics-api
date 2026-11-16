from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import ApiKey

API_KEY_HEADER = "X-API-Key"


class ApiKeyAuthentication(BaseAuthentication):
    """Authenticates server-to-server requests with an organization API key.

    request.user stays anonymous (a key is not a person) and request.auth is the
    ApiKey, which is what the tenancy code uses to find the organization.
    """

    def authenticate(self, request):
        raw_key = request.headers.get(API_KEY_HEADER)
        if not raw_key:
            return None
        api_key = ApiKey.objects.verify(raw_key)
        if api_key is None:
            raise AuthenticationFailed("Invalid or revoked API key.")
        api_key.mark_used()
        return AnonymousUser(), api_key

    def authenticate_header(self, request):
        return API_KEY_HEADER
