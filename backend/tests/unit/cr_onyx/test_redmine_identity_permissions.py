from unittest.mock import MagicMock, patch

import pytest
from cr_onyx.connectors.redmine.permissions import tenant_wiki_access

from onyx.connectors.exceptions import ConnectorValidationError


def _catalog_context(
    *,
    bound_group_id: str = "42",
    include_identity: bool = True,
    service_account_emails: list[str] | None = None,
) -> MagicMock:
    tenant_result = MagicMock()
    tenant_result.scalar_one_or_none.return_value = "tenant-uuid"
    snapshot_result = MagicMock()
    snapshot_result.mappings.return_value.one_or_none.return_value = {
        "redmine_group_id": 42,
        "bound_group_id": bound_group_id,
    }
    identity_result = (
        [
            MagicMock(email="member@example.com"),
            MagicMock(email="not-an-email"),
        ]
        if include_identity
        else []
    )
    session = MagicMock()
    session.execute.side_effect = [
        tenant_result,
        MagicMock(),
        snapshot_result,
        identity_result,
        MagicMock(
            scalar_one_or_none=MagicMock(return_value=service_account_emails or [])
        ),
    ]
    context = MagicMock()
    context.__enter__.return_value = session
    return context


def test_acl_contains_only_explicit_identity_intersection() -> None:
    with (
        patch(
            "cr_onyx.db.redmine.get_current_tenant_id",
            return_value="tenant_schema",
        ),
        patch(
            "cr_onyx.db.redmine.get_catalog_session",
            return_value=_catalog_context(),
        ),
    ):
        access = tenant_wiki_access([1])

    assert access.external_user_emails == {"member@example.com"}
    assert access.external_user_group_ids == set()
    assert access.is_public is False


def test_empty_synchronized_identity_snapshot_revokes_everyone() -> None:
    context = _catalog_context(include_identity=False)
    with (
        patch(
            "cr_onyx.db.redmine.get_current_tenant_id",
            return_value="tenant_schema",
        ),
        patch(
            "cr_onyx.db.redmine.get_catalog_session",
            return_value=context,
        ),
    ):
        access = tenant_wiki_access([1])

    assert access.external_user_emails == set()
    assert access.is_public is False


def test_identity_snapshot_must_match_bound_redmine_group() -> None:
    with (
        patch(
            "cr_onyx.db.redmine.get_current_tenant_id",
            return_value="tenant_schema",
        ),
        patch(
            "cr_onyx.db.redmine.get_catalog_session",
            return_value=_catalog_context(bound_group_id="99"),
        ),
        pytest.raises(ConnectorValidationError, match="does not match"),
    ):
        tenant_wiki_access([1])


def test_acl_includes_only_validated_service_account() -> None:
    service_account = "api_key__agent@example.onyxapikey.ai"
    tenant_session = MagicMock()
    tenant_session.scalars.return_value = [service_account]
    tenant_context = MagicMock()
    tenant_context.__enter__.return_value = tenant_session
    with (
        patch(
            "cr_onyx.db.redmine.get_current_tenant_id",
            return_value="tenant_schema",
        ),
        patch(
            "cr_onyx.db.redmine.get_catalog_session",
            return_value=_catalog_context(service_account_emails=[service_account]),
        ),
        patch(
            "cr_onyx.db.redmine.get_session_with_current_tenant",
            return_value=tenant_context,
        ),
    ):
        access = tenant_wiki_access([1])

    assert access.external_user_emails == {
        "member@example.com",
        service_account,
    }


def test_invalid_service_account_fails_closed() -> None:
    tenant_session = MagicMock()
    tenant_session.scalars.return_value = []
    tenant_context = MagicMock()
    tenant_context.__enter__.return_value = tenant_session
    with (
        patch(
            "cr_onyx.db.redmine.get_current_tenant_id",
            return_value="tenant_schema",
        ),
        patch(
            "cr_onyx.db.redmine.get_catalog_session",
            return_value=_catalog_context(
                service_account_emails=["ordinary-user@example.com"]
            ),
        ),
        patch(
            "cr_onyx.db.redmine.get_session_with_current_tenant",
            return_value=tenant_context,
        ),
        pytest.raises(ConnectorValidationError, match="active Onyx service account"),
    ):
        tenant_wiki_access([1])
