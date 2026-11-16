from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("auth/signup/", views.SignupView.as_view(), name="signup"),
    path("auth/login/", views.LoginView.as_view(), name="login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", views.MeView.as_view(), name="me"),
    path("orgs/", views.OrganizationListCreateView.as_view(), name="org-list"),
    path("orgs/current/", views.CurrentOrganizationView.as_view(), name="org-current"),
    path("orgs/current/webhook-secret/", views.WebhookSecretView.as_view(), name="org-webhook-secret"),
    path("api-keys/", views.ApiKeyListCreateView.as_view(), name="api-key-list"),
    path("api-keys/<int:pk>/", views.ApiKeyDetailView.as_view(), name="api-key-detail"),
]
