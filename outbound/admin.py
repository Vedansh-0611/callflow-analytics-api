from django.contrib import admin

from .models import WebhookDelivery, WebhookEndpoint


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    list_display = ("url", "organization", "is_active", "created_at")
    list_filter = ("organization", "is_active")
    exclude = ("secret",)


@admin.register(WebhookDelivery)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    list_display = ("event_id", "event_type", "endpoint", "status", "attempts", "last_status_code", "created_at")
    list_filter = ("status", "event_type")
