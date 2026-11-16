from django.contrib import admin

from .models import Call, CallEvent


class CallEventInline(admin.TabularInline):
    model = CallEvent
    extra = 0
    readonly_fields = ("event_id", "type", "occurred_at", "data")


@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
    list_display = ("provider_call_id", "agent_id", "status", "started_at", "duration_seconds", "cost_usd")
    list_filter = ("status", "direction", "agent_id")
    search_fields = ("provider_call_id", "from_number", "to_number")
    inlines = [CallEventInline]


@admin.register(CallEvent)
class CallEventAdmin(admin.ModelAdmin):
    list_display = ("event_id", "type", "call", "occurred_at")
    list_filter = ("type",)
