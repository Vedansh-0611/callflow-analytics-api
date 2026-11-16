from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import ApiKey, Membership, Organization

User = get_user_model()


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})
    name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    organization_name = serializers.CharField(max_length=120)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "created_at"]
        read_only_fields = ["id", "slug", "created_at"]


class MembershipOrgSerializer(serializers.ModelSerializer):
    """One of the current user's organizations, with their role in it."""

    id = serializers.IntegerField(source="organization.id")
    name = serializers.CharField(source="organization.name")
    slug = serializers.CharField(source="organization.slug")

    class Meta:
        model = Membership
        fields = ["id", "name", "slug", "role"]


class UserSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="first_name")
    organizations = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "name", "organizations"]

    def get_organizations(self, user):
        memberships = user.memberships.select_related("organization")
        return MembershipOrgSerializer(memberships, many=True).data


class MemberSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email")
    name = serializers.CharField(source="user.first_name")

    class Meta:
        model = Membership
        fields = ["email", "name", "role", "created_at"]


class CurrentOrganizationSerializer(serializers.ModelSerializer):
    members = MemberSerializer(source="memberships", many=True, read_only=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "created_at", "members"]


class ApiKeySerializer(serializers.ModelSerializer):
    created_by = serializers.EmailField(source="created_by.email", read_only=True, default=None)

    class Meta:
        model = ApiKey
        fields = ["id", "name", "prefix", "created_by", "created_at", "last_used_at", "revoked_at"]
        read_only_fields = ["id", "prefix", "created_by", "created_at", "last_used_at", "revoked_at"]


class NewApiKeySerializer(ApiKeySerializer):
    """Returned once, right after creation. It is the only time `key` is visible."""

    key = serializers.CharField(read_only=True)

    class Meta(ApiKeySerializer.Meta):
        fields = ApiKeySerializer.Meta.fields + ["key"]


class WebhookSecretSerializer(serializers.Serializer):
    webhook_secret = serializers.CharField()
    previous_secret_expires_at = serializers.DateTimeField(allow_null=True)
