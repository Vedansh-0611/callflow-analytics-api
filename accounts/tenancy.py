"""Which organization is this request acting for?

- API key requests: the key's organization. Keys belong to exactly one org.
- Dashboard users (JWT): the org named in the X-Organization header (its slug),
  or their oldest membership when the header is missing. The user must be a
  member, otherwise the request is rejected.

Views get `request.organization` and `request.org_role` from the permission
classes below, and OrgScopedQuerysetMixin filters every queryset by it. A view
that forgets the permission fails closed: `request.organization` does not
exist, so the queryset raises instead of returning another tenant's rows.
"""
from rest_framework.exceptions import NotAuthenticated, PermissionDenied
from rest_framework.permissions import BasePermission

from .models import ApiKey, Membership

ORG_HEADER = "X-Organization"
API_KEY_ROLE = "api_key"


def resolve_tenant(request):
    """Return (organization, role) for the request, or raise a DRF error."""
    if isinstance(request.auth, ApiKey):
        return request.auth.organization, API_KEY_ROLE

    user = request.user
    if not user or not user.is_authenticated:
        raise NotAuthenticated()

    memberships = Membership.objects.select_related("organization").filter(user=user)
    slug = request.headers.get(ORG_HEADER)
    if slug:
        membership = memberships.filter(organization__slug=slug).first()
        if membership is None:
            raise PermissionDenied("You are not a member of this organization.")
    else:
        membership = memberships.first()
        if membership is None:
            raise PermissionDenied("You do not belong to any organization yet.")
    return membership.organization, membership.role


def attach_tenant(request):
    if not hasattr(request, "organization"):
        request.organization, request.org_role = resolve_tenant(request)
        # For the access log line (it only sees Django's request object).
        request._request.organization_id_for_logs = request.organization.slug
    return request.organization


class IsOrgMember(BasePermission):
    """Any member of the org, or an API key of the org."""

    def has_permission(self, request, view):
        attach_tenant(request)
        return True


class IsOrgAdmin(BasePermission):
    """Owners and admins, signed in as themselves. API keys cannot manage the org."""

    message = "Only organization owners and admins can do this."

    def has_permission(self, request, view):
        attach_tenant(request)
        return request.org_role in Membership.ADMIN_ROLES


class IsSignedInUser(BasePermission):
    """A real user (JWT), not an API key. Used for account-level endpoints."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class OrgScopedQuerysetMixin:
    """Limit a generic view's queryset to the request's organization."""

    def get_queryset(self):
        return super().get_queryset().filter(organization=self.request.organization)
