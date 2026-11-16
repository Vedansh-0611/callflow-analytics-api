from django.urls import path

from . import views

urlpatterns = [
    path("billing/", views.BillingView.as_view(), name="billing"),
    path("billing/change-plan/", views.ChangePlanView.as_view(), name="billing-change-plan"),
]
