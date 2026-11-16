from django.contrib import admin

from .models import Plan, Subscription, UsageCounter


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "price_cents_per_month", "monthly_call_limit", "monthly_minute_limit")


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("organization", "plan", "status", "provider", "updated_at")
    list_filter = ("plan", "status")


@admin.register(UsageCounter)
class UsageCounterAdmin(admin.ModelAdmin):
    list_display = ("organization", "period", "calls", "billed_minutes")
    list_filter = ("period",)
