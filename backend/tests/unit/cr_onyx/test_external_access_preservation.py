from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from onyx.access.models import DocumentAccess


def test_external_email_acl_is_preserved_for_opensearch_enrichment() -> None:
    from cr_onyx.access.access import _get_access_for_documents

    base = DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=False,
    )
    document = SimpleNamespace(
        id="redmine:wiki:1:Private",
        external_user_emails=["member@example.com"],
        external_user_group_ids=[],
        is_public=False,
    )
    with (
        patch(
            "cr_onyx.access.access.get_access_for_documents_without_external_access",
            return_value={document.id: base},
        ),
        patch("cr_onyx.access.access.get_documents_by_ids", return_value=[document]),
    ):
        access = _get_access_for_documents([document.id], MagicMock())[document.id]

    assert access.external_user_emails == {"member@example.com"}
    assert access.is_public is False
    assert access.to_acl() == {"user_email:member@example.com"}
