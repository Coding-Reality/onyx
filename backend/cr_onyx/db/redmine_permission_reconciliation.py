from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.db.document import get_document_ids_for_connector_credential_pair
from onyx.db.models import Document, HierarchyNode


@dataclass(frozen=True)
class RedminePermissionReconciliationResult:
    documents_updated: int
    documents_revoked: int
    nodes_updated: int
    nodes_revoked: int


def _apply_access(element: Document | HierarchyNode, access: ExternalAccess) -> bool:
    emails = sorted(access.external_user_emails)
    groups = sorted(access.external_user_group_ids)
    if (
        sorted(element.external_user_emails or []) == emails
        and sorted(element.external_user_group_ids or []) == groups
        and element.is_public == access.is_public
    ):
        return False
    element.external_user_emails = emails
    element.external_user_group_ids = groups
    element.is_public = access.is_public
    if isinstance(element, Document):
        element.last_modified = datetime.now(timezone.utc)
    return True


def reconcile_redmine_permissions(
    db_session: Session,
    connector_id: int,
    credential_id: int,
    authoritative_document_ids: set[str],
    authoritative_node_ids: set[str],
    access: ExternalAccess,
) -> RedminePermissionReconciliationResult:
    """Apply one tenant-wide Redmine ACL and revoke disappeared source objects."""
    existing_ids = set(
        get_document_ids_for_connector_credential_pair(
            db_session, connector_id, credential_id
        )
    )
    documents = list(
        db_session.scalars(select(Document).where(Document.id.in_(existing_ids))).all()
    )
    private = ExternalAccess.empty()
    documents_updated = 0
    documents_revoked = 0
    for document in documents:
        exists_at_source = document.id in authoritative_document_ids
        if _apply_access(document, access if exists_at_source else private):
            if exists_at_source:
                documents_updated += 1
            else:
                documents_revoked += 1

    nodes = list(
        db_session.scalars(
            select(HierarchyNode).where(HierarchyNode.source == DocumentSource.REDMINE)
        ).all()
    )
    nodes_updated = 0
    nodes_revoked = 0
    for node in nodes:
        exists_at_source = node.raw_node_id in authoritative_node_ids
        if _apply_access(node, access if exists_at_source else private):
            if exists_at_source:
                nodes_updated += 1
            else:
                nodes_revoked += 1

    db_session.commit()
    return RedminePermissionReconciliationResult(
        documents_updated=documents_updated,
        documents_revoked=documents_revoked,
        nodes_updated=nodes_updated,
        nodes_revoked=nodes_revoked,
    )
