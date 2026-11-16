import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

API_KEY_PREFIX = "cf"
WEBHOOK_SECRET_PREFIX = "whsec_"


def generate_webhook_secret():
    return WEBHOOK_SECRET_PREFIX + secrets.token_hex(24)


def hash_api_key(raw_key):
    # API keys are 160 random bits, so a fast hash is enough: there is nothing to
    # brute force. bcrypt/argon2 are for low-entropy, human-chosen passwords.
    return hashlib.sha256(raw_key.encode()).hexdigest()


class Organization(models.Model):
    """A customer workspace. Every call, event, key and endpoint belongs to one."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=64, unique=True)

    # Secret the telephony provider uses to sign the webhooks it sends us. It is
    # stored in plain text because HMAC verification needs the original value.
    webhook_secret = models.CharField(max_length=80, default=generate_webhook_secret)
    # After a rotation the old secret keeps working for a grace period, so the
    # provider can be reconfigured without dropping webhooks.
    previous_webhook_secret = models.CharField(max_length=80, blank=True, default="")
    previous_secret_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def rotate_webhook_secret(self, grace=timedelta(hours=24)):
        self.previous_webhook_secret = self.webhook_secret
        self.previous_secret_expires_at = timezone.now() + grace
        self.webhook_secret = generate_webhook_secret()
        self.save(update_fields=["webhook_secret", "previous_webhook_secret", "previous_secret_expires_at"])
        return self.webhook_secret

    def active_webhook_secrets(self, now=None):
        now = now or timezone.now()
        active = [self.webhook_secret]
        if self.previous_webhook_secret and self.previous_secret_expires_at and self.previous_secret_expires_at > now:
            active.append(self.previous_webhook_secret)
        return active


class Membership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    ADMIN_ROLES = (Role.OWNER, Role.ADMIN)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "organization"], name="unique_membership"),
        ]

    def __str__(self):
        return f"{self.user} in {self.organization} ({self.role})"


class ApiKeyQuerySet(models.QuerySet):
    def active(self):
        return self.filter(revoked_at__isnull=True)

    def create_key(self, organization, name, created_by=None):
        """Create a key and return (api_key, raw_key). The raw key is never stored."""
        public = secrets.token_hex(4)
        raw_key = f"{API_KEY_PREFIX}_{public}_{secrets.token_hex(20)}"
        api_key = self.create(
            organization=organization,
            name=name,
            prefix=f"{API_KEY_PREFIX}_{public}",
            key_hash=hash_api_key(raw_key),
            created_by=created_by,
        )
        return api_key, raw_key

    def verify(self, raw_key):
        """Return the active key matching raw_key, or None."""
        parts = (raw_key or "").split("_")
        if len(parts) != 3 or parts[0] != API_KEY_PREFIX:
            return None
        # The prefix is indexed, so this is a single-row lookup; then compare the
        # hash in constant time.
        key = (
            self.active()
            .select_related("organization__subscription__plan")
            .filter(prefix=f"{parts[0]}_{parts[1]}")
            .first()
        )
        if key and hmac.compare_digest(key.key_hash, hash_api_key(raw_key)):
            return key
        return None


class ApiKey(models.Model):
    """Server-to-server credential for one organization."""

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=80)
    # The first part of the key, safe to show in the UI so people can tell keys apart.
    prefix = models.CharField(max_length=16, unique=True)
    key_hash = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    objects = ApiKeyQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.prefix}... ({self.name})"

    @property
    def is_active(self):
        return self.revoked_at is None

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])

    def mark_used(self, now=None):
        # Writing on every request would turn each read into a write. Once a
        # minute is precise enough for a "last used" column.
        now = now or timezone.now()
        if self.last_used_at is None or now - self.last_used_at > timedelta(minutes=1):
            ApiKey.objects.filter(pk=self.pk).update(last_used_at=now)
            self.last_used_at = now
