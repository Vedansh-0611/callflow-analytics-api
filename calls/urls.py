from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.HealthView.as_view(), name="health"),
    path("webhooks/calls/", views.CallWebhookView.as_view(), name="call-webhook"),
    path("calls/", views.CallListView.as_view(), name="call-list"),
    path("calls/<str:call_id>/", views.CallDetailView.as_view(), name="call-detail"),
    path("stats/", views.StatsView.as_view(), name="stats"),
]
