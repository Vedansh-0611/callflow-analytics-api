import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import WebhookDelivery
from .services import attempt_delivery, backoff_seconds

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=settings.OUTBOUND_WEBHOOK_MAX_RETRIES)
def deliver_webhook(self, delivery_id):
    """Send one delivery; on failure, retry later with exponential backoff.

    Safe to run twice: a delivery that already succeeded is not sent again.
    """
    delivery = WebhookDelivery.objects.select_related("endpoint").get(pk=delivery_id)
    if delivery.status != WebhookDelivery.Status.PENDING or not delivery.endpoint.is_active:
        return delivery.status

    if attempt_delivery(delivery):
        logger.info("webhook delivered", extra={"delivery_id": delivery.pk, "attempts": delivery.attempts})
        return delivery.status

    if self.request.retries >= self.max_retries:
        delivery.status = WebhookDelivery.Status.FAILED
        delivery.next_retry_at = None
        delivery.save(update_fields=["status", "next_retry_at"])
        logger.warning("webhook gave up", extra={"delivery_id": delivery.pk, "error": delivery.last_error})
        return delivery.status

    countdown = backoff_seconds(self.request.retries)
    delivery.next_retry_at = timezone.now() + timedelta(seconds=countdown)
    delivery.save(update_fields=["next_retry_at"])
    logger.info("webhook retry scheduled", extra={"delivery_id": delivery.pk, "countdown": round(countdown)})
    raise self.retry(countdown=countdown)
