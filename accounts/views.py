from django.contrib.auth import authenticate
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from billing import services as billing

from . import services
from .models import ApiKey, Membership
from .serializers import (
    ApiKeySerializer,
    CurrentOrganizationWithRoleSerializer,
    LoginSerializer,
    MembershipOrgSerializer,
    NewApiKeySerializer,
    OrganizationSerializer,
    SignupSerializer,
    TokenResponseSerializer,
    UserSerializer,
    WebhookSecretSerializer,
)
from .tenancy import IsOrgAdmin, IsOrgMember, IsSignedInUser, OrgScopedQuerysetMixin
from .throttling import AuthRateThrottle


def token_response(user, status_code=status.HTTP_200_OK):
    refresh = RefreshToken.for_user(user)
    return Response(
        {"access": str(refresh.access_token), "refresh": str(refresh), "user": UserSerializer(user).data},
        status=status_code,
    )


class SignupView(APIView):
    """Create an account and its first organization. Returns JWTs."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=SignupSerializer, responses={201: TokenResponseSerializer}, tags=["auth"])
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, _ = services.sign_up(**serializer.validated_data)
        return token_response(user, status.HTTP_201_CREATED)


class LoginView(APIView):
    """Exchange email and password for an access and a refresh token."""

    permission_classes = [AllowAny]
    throttle_classes = [AuthRateThrottle]

    @extend_schema(request=LoginSerializer, responses=TokenResponseSerializer, tags=["auth"])
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=serializer.validated_data["email"].strip().lower(),
            password=serializer.validated_data["password"],
        )
        if user is None:
            # Same message for unknown email and wrong password.
            raise AuthenticationFailed("Invalid email or password.")
        return token_response(user)


class MeView(APIView):
    permission_classes = [IsSignedInUser]

    @extend_schema(responses=UserSerializer, tags=["auth"])
    def get(self, request):
        return Response(UserSerializer(request.user).data)


@extend_schema(tags=["organizations"])
class OrganizationListCreateView(generics.ListCreateAPIView):
    """The signed-in user's organizations. POST creates a new one they own."""

    permission_classes = [IsSignedInUser]
    pagination_class = None

    def get_serializer_class(self):
        return OrganizationSerializer if self.request.method == "POST" else MembershipOrgSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):  # schema generation has no user
            return Membership.objects.none()
        return self.request.user.memberships.select_related("organization")

    def create(self, request, *args, **kwargs):
        serializer = OrganizationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org = services.create_organization(serializer.validated_data["name"], owner=request.user)
        return Response(OrganizationSerializer(org).data, status=status.HTTP_201_CREATED)


class CurrentOrganizationView(APIView):
    """The organization this request is acting for, with its members."""

    permission_classes = [IsOrgMember]

    @extend_schema(responses=CurrentOrganizationWithRoleSerializer, tags=["organizations"])
    def get(self, request):
        request.organization.role = request.org_role
        return Response(CurrentOrganizationWithRoleSerializer(request.organization).data)


class WebhookSecretView(APIView):
    """GET shows the inbound signing secret. POST rotates it.

    After a rotation the previous secret stays valid for 24 hours so the
    provider can be switched over without losing events.
    """

    permission_classes = [IsOrgAdmin]

    @extend_schema(responses=WebhookSecretSerializer, tags=["organizations"])
    def get(self, request):
        return Response(self.payload(request.organization))

    @extend_schema(request=None, responses=WebhookSecretSerializer, tags=["organizations"])
    def post(self, request):
        request.organization.rotate_webhook_secret()
        return Response(self.payload(request.organization))

    @staticmethod
    def payload(org):
        return WebhookSecretSerializer(
            {"webhook_secret": org.webhook_secret, "previous_secret_expires_at": org.previous_secret_expires_at}
        ).data


@extend_schema(tags=["api keys"])
class ApiKeyListCreateView(OrgScopedQuerysetMixin, generics.ListCreateAPIView):
    permission_classes = [IsOrgAdmin]
    queryset = ApiKey.objects.select_related("created_by")
    serializer_class = ApiKeySerializer
    pagination_class = None

    @extend_schema(responses={201: NewApiKeySerializer})
    def create(self, request, *args, **kwargs):
        serializer = ApiKeySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        billing.check_resource_limit(
            request.organization, "api_keys", ApiKey.objects.active().filter(organization=request.organization).count()
        )
        api_key, raw_key = ApiKey.objects.create_key(
            organization=request.organization,
            name=serializer.validated_data["name"],
            created_by=request.user,
        )
        api_key.key = raw_key
        return Response(NewApiKeySerializer(api_key).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["api keys"])
class ApiKeyDetailView(OrgScopedQuerysetMixin, generics.RetrieveDestroyAPIView):
    """DELETE revokes the key. The row is kept so audit history stays intact."""

    permission_classes = [IsOrgAdmin]
    queryset = ApiKey.objects.select_related("created_by")
    serializer_class = ApiKeySerializer

    def perform_destroy(self, instance):
        instance.revoke()
