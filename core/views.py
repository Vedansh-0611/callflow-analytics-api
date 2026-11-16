import logging

from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

StatusSerializer = inline_serializer("HealthStatus", {"status": serializers.CharField()})


class HealthView(APIView):
    """Liveness: the process is up and serving. Checks nothing else, so a
    database blip does not get every instance restarted at once."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(responses=StatusSerializer, tags=["ops"])
    def get(self, request):
        return Response({"status": "ok"})


class ReadyView(APIView):
    """Readiness: can this instance do real work? Checks the database and the
    cache (Redis in production). 503 tells the load balancer to hold traffic."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []

    @extend_schema(
        responses={200: inline_serializer("ReadyStatus", {"status": serializers.CharField(),
                                                          "checks": serializers.DictField()})},
        tags=["ops"],
    )
    def get(self, request):
        checks = {"database": self.check(self.database), "cache": self.check(self.cache)}
        ready = all(value == "ok" for value in checks.values())
        return Response({"status": "ok" if ready else "unavailable", "checks": checks}, status=200 if ready else 503)

    @staticmethod
    def check(probe):
        try:
            probe()
            return "ok"
        except Exception as exc:  # any failure means "not ready"
            logger.warning("readiness check failed", extra={"check": probe.__name__, "error": str(exc)})
            return "error"

    @staticmethod
    def database():
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

    @staticmethod
    def cache():
        cache.set("readiness-probe", "1", timeout=5)
        if cache.get("readiness-probe") != "1":
            raise RuntimeError("cache read-back failed")
