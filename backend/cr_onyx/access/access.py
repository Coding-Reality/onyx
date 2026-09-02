from sqlalchemy.orm import Session

from onyx.access.access import (
    _get_access_for_documents as get_access_for_documents_without_external_access,
)
from onyx.access.models import DocumentAccess
from onyx.db.document import get_documents_by_ids


def _get_access_for_document(
    document_id: str,
    db_session: Session,
) -> DocumentAccess:
    return _get_access_for_documents([document_id], db_session)[document_id]


def _get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    """Preserve connector external identities in the CE OpenSearch ACL."""
    base_access = get_access_for_documents_without_external_access(
        document_ids, db_session
    )
    db_documents = {
        document.id: document
        for document in get_documents_by_ids(db_session, document_ids)
    }
    access: dict[str, DocumentAccess] = {}
    for document_id in document_ids:
        base = base_access[document_id]
        document = db_documents.get(document_id)
        access[document_id] = DocumentAccess.build(
            user_emails=list(base.user_emails),
            user_groups=list(base.user_groups),
            external_user_emails=(
                list(document.external_user_emails or []) if document else []
            ),
            external_user_group_ids=(
                list(document.external_user_group_ids or []) if document else []
            ),
            is_public=base.is_public or bool(document and document.is_public),
        )
    return access
