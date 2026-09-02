from celery import shared_task

from cr_onyx.db.redmine_connector_targets import (
    redmine_sync_connectors,
)
from cr_onyx.db.redmine_permission_reconciliation import (
    RedminePermissionReconciliationResult,
    reconcile_redmine_permissions,
)
from onyx.access.models import ExternalAccess
from onyx.configs.constants import OnyxCeleryTask
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import HierarchyNode, SlimDocument
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.redis.redis_pool import get_redis_client
from onyx.server.metrics.redmine_connector import (
    inc_permission_changes,
    inc_permission_reconciliation,
)


def _authoritative_access(
    connector: SlimConnectorWithPermSync,
) -> tuple[set[str], set[str], ExternalAccess]:
    document_ids: set[str] = set()
    node_ids: set[str] = set()
    access: ExternalAccess | None = None
    for batch in connector.retrieve_all_slim_docs_perm_sync():
        for item in batch:
            item_access = item.external_access
            if item_access is None:
                raise RuntimeError("Redmine permission item has no ACL")
            if access is not None and item_access != access:
                raise RuntimeError(
                    "Redmine tenant-wide ACL changed during reconciliation"
                )
            access = item_access
            if isinstance(item, SlimDocument):
                document_ids.add(item.id)
            elif isinstance(item, HierarchyNode):
                node_ids.add(item.raw_node_id)
    if access is None:
        raise RuntimeError("Redmine permission reconciliation returned no ACL")
    return document_ids, node_ids, access


@shared_task(
    name=OnyxCeleryTask.REDMINE_PERMISSION_RECONCILIATION,
    ignore_result=True,
)
def redmine_permission_reconciliation(*, tenant_id: str) -> list[dict[str, int]]:
    """Refresh and revoke Redmine ACLs independently of content updates."""
    redis = get_redis_client()
    lock = redis.lock(
        f"redmine_permission_reconciliation:{tenant_id}",
        timeout=5 * 60,
    )
    if not lock.acquire(blocking=False):
        inc_permission_reconciliation("lock_held")
        return []
    try:
        results: list[dict[str, int]] = []
        for target in redmine_sync_connectors():
            document_ids, node_ids, access = _authoritative_access(target.connector)
            with get_session_with_current_tenant() as db_session:
                result: RedminePermissionReconciliationResult = (
                    reconcile_redmine_permissions(
                        db_session,
                        target.connector_id,
                        target.credential_id,
                        document_ids,
                        node_ids,
                        access,
                    )
                )
            results.append(
                {
                    "documents_updated": result.documents_updated,
                    "documents_revoked": result.documents_revoked,
                    "nodes_updated": result.nodes_updated,
                    "nodes_revoked": result.nodes_revoked,
                }
            )
            inc_permission_changes(
                documents_updated=result.documents_updated,
                documents_revoked=result.documents_revoked,
                nodes_updated=result.nodes_updated,
                nodes_revoked=result.nodes_revoked,
            )
        inc_permission_reconciliation("success")
        return results
    except Exception:
        inc_permission_reconciliation("failure")
        raise
    finally:
        if lock.owned():
            lock.release()
