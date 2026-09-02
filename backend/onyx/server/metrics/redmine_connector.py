from prometheus_client import Counter, Histogram

from onyx.utils.logger import setup_logger

logger = setup_logger()

REDMINE_API_REQUESTS = Counter(
    "onyx_redmine_api_requests_total",
    "Redmine connector HTTP requests",
    ["operation", "outcome"],
)
REDMINE_API_DURATION = Histogram(
    "onyx_redmine_api_request_duration_seconds",
    "Redmine connector HTTP request duration",
    ["operation"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30],
)
REDMINE_RATE_LIMIT_EVENTS = Counter(
    "onyx_redmine_api_rate_limit_events_total",
    "Final Redmine connector responses with HTTP 429",
)
REDMINE_ATTACHMENTS = Counter(
    "onyx_redmine_attachments_processed_total",
    "Redmine attachments accepted by the connector",
    ["outcome"],
)
REDMINE_PERMISSION_RECONCILIATIONS = Counter(
    "onyx_redmine_permission_reconciliations_total",
    "Redmine permission reconciliation runs",
    ["outcome"],
)
REDMINE_PERMISSION_CHANGES = Counter(
    "onyx_redmine_permission_changes_total",
    "Redmine permission rows changed by resource and action",
    ["resource", "action"],
)


def observe_api_request(operation: str, outcome: str, duration: float) -> None:
    try:
        REDMINE_API_REQUESTS.labels(operation=operation, outcome=outcome).inc()
        REDMINE_API_DURATION.labels(operation=operation).observe(duration)
        if outcome == "429":
            REDMINE_RATE_LIMIT_EVENTS.inc()
    except Exception:
        logger.debug("Failed to record Redmine API metrics", exc_info=True)


def inc_attachment(outcome: str) -> None:
    try:
        REDMINE_ATTACHMENTS.labels(outcome=outcome).inc()
    except Exception:
        logger.debug("Failed to record Redmine attachment metric", exc_info=True)


def inc_permission_reconciliation(outcome: str) -> None:
    try:
        REDMINE_PERMISSION_RECONCILIATIONS.labels(outcome=outcome).inc()
    except Exception:
        logger.debug("Failed to record Redmine permission metric", exc_info=True)


def inc_permission_changes(
    *, documents_updated: int, documents_revoked: int, nodes_updated: int, nodes_revoked: int
) -> None:
    try:
        for resource, action, amount in (
            ("document", "updated", documents_updated),
            ("document", "revoked", documents_revoked),
            ("hierarchy_node", "updated", nodes_updated),
            ("hierarchy_node", "revoked", nodes_revoked),
        ):
            if amount:
                REDMINE_PERMISSION_CHANGES.labels(
                    resource=resource, action=action
                ).inc(amount)
    except Exception:
        logger.debug("Failed to record Redmine permission changes", exc_info=True)
