"""OpenTelemetry setup — tracing, metrics, and auto-instrumentation.

Guarded by settings.OTEL_ENABLED. When disabled, all functions are no-ops.
"""

import structlog

from app.config import settings

logger = structlog.stdlib.get_logger()

_tracer = None
_meter = None
_initialized = False


def setup_telemetry(service_name: str | None = None) -> None:
    """Initialize OpenTelemetry providers, exporters, and auto-instrumentation.

    Safe to call multiple times — only the first call has effect.
    """
    global _tracer, _meter, _initialized

    if _initialized or not settings.OTEL_ENABLED:
        return

    from opentelemetry import metrics, trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    name = service_name or settings.OTEL_SERVICE_NAME
    resource = Resource.create({"service.name": name})

    # Tracing
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = OTLPSpanExporter(endpoint=settings.OTEL_EXPORTER_ENDPOINT, insecure=True)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)
    _tracer = trace.get_tracer(name)

    # Metrics
    metric_exporter = OTLPMetricExporter(endpoint=settings.OTEL_EXPORTER_ENDPOINT, insecure=True)
    metric_reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=15000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    _meter = metrics.get_meter(name)

    # Auto-instrumentation
    _instrument_libraries()

    _initialized = True
    logger.info("otel_initialized", service_name=name, endpoint=settings.OTEL_EXPORTER_ENDPOINT)


def _instrument_libraries() -> None:
    """Auto-instrument supported libraries."""
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument()
    except Exception:
        logger.debug("otel_fastapi_instrumentation_skipped")

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor

        RedisInstrumentor().instrument()
    except Exception:
        logger.debug("otel_redis_instrumentation_skipped")

    try:
        from opentelemetry.instrumentation.celery import CeleryInstrumentor

        CeleryInstrumentor().instrument()
    except Exception:
        logger.debug("otel_celery_instrumentation_skipped")


def get_tracer():
    """Return the application tracer (or a no-op tracer if OTEL is disabled)."""
    if _tracer is not None:
        return _tracer
    from opentelemetry import trace

    return trace.get_tracer("cadprice")


def get_meter():
    """Return the application meter (or a no-op meter if OTEL is disabled)."""
    if _meter is not None:
        return _meter
    from opentelemetry import metrics

    return metrics.get_meter("cadprice")
