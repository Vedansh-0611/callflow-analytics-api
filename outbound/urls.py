from rest_framework.routers import SimpleRouter

from .views import WebhookEndpointViewSet

router = SimpleRouter()
router.register("webhook-endpoints", WebhookEndpointViewSet, basename="webhook-endpoint")

urlpatterns = router.urls
