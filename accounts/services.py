from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.crypto import get_random_string
from django.utils.text import slugify

from .models import Membership, Organization

User = get_user_model()


def unique_slug(name):
    base = slugify(name)[:50] or "org"
    slug = base
    while Organization.objects.filter(slug=slug).exists():
        slug = f"{base}-{get_random_string(4, 'abcdefghijklmnopqrstuvwxyz0123456789')}"
    return slug


@transaction.atomic
def create_organization(name, owner):
    org = Organization.objects.create(name=name, slug=unique_slug(name))
    Membership.objects.create(user=owner, organization=org, role=Membership.Role.OWNER)
    return org


@transaction.atomic
def sign_up(email, password, organization_name, name=""):
    """Create a user and their first organization, with the user as owner."""
    email = email.strip().lower()
    # The email doubles as the username, so the default User model works as is.
    user = User.objects.create_user(username=email, email=email, password=password, first_name=name[:150])
    org = create_organization(organization_name, owner=user)
    return user, org
