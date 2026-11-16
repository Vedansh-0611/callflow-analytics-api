from django.contrib import admin

from .models import ApiKey, Membership, Organization


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    search_fields = ("name", "slug")
    exclude = ("webhook_secret", "previous_webhook_secret")
    inlines = [MembershipInline]


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ("prefix", "name", "organization", "created_at", "last_used_at", "revoked_at")
    list_filter = ("organization",)
    readonly_fields = ("prefix", "key_hash", "created_at", "last_used_at")
