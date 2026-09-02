from unittest.mock import MagicMock, patch

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource
from onyx.db.enums import HierarchyNodeType
from onyx.db.models import Document, HierarchyNode


def test_reconciliation_updates_current_and_revokes_missing_elements() -> None:
    from cr_onyx.db.redmine_permission_reconciliation import (
        reconcile_redmine_permissions,
    )

    current = Document(id="redmine:wiki:1:Current")
    missing = Document(id="redmine:wiki:1:Deleted")
    for document in (current, missing):
        document.external_user_emails = ["old@example.com"]
        document.external_user_group_ids = []
        document.is_public = False
    current_node = HierarchyNode(
        raw_node_id="redmine:project:1",
        display_name="Project",
        source=DocumentSource.REDMINE,
        node_type=HierarchyNodeType.PROJECT,
    )
    missing_node = HierarchyNode(
        raw_node_id="redmine:wiki:1:Deleted",
        display_name="Deleted",
        source=DocumentSource.REDMINE,
        node_type=HierarchyNodeType.PAGE,
    )
    for node in (current_node, missing_node):
        node.external_user_emails = ["old@example.com"]
        node.external_user_group_ids = []
        node.is_public = False

    document_result = MagicMock()
    document_result.all.return_value = [current, missing]
    node_result = MagicMock()
    node_result.all.return_value = [current_node, missing_node]
    session = MagicMock()
    session.scalars.side_effect = [document_result, node_result]
    access = ExternalAccess(
        external_user_emails={"member@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )

    with patch(
        "cr_onyx.db.redmine_permission_reconciliation.get_document_ids_for_connector_credential_pair",
        return_value=[current.id, missing.id],
    ):
        result = reconcile_redmine_permissions(
            session,
            connector_id=1,
            credential_id=2,
            authoritative_document_ids={current.id},
            authoritative_node_ids={current_node.raw_node_id},
            access=access,
        )

    assert current.external_user_emails == ["member@example.com"]
    assert missing.external_user_emails == []
    assert current_node.external_user_emails == ["member@example.com"]
    assert missing_node.external_user_emails == []
    assert current.last_modified is not None
    assert missing.last_modified is not None
    assert result.documents_updated == 1
    assert result.documents_revoked == 1
    assert result.nodes_updated == 1
    assert result.nodes_revoked == 1
    session.commit.assert_called_once()
