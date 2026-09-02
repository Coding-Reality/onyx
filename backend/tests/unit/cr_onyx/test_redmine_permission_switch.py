from unittest.mock import patch

from cr_onyx.external_permissions.sync_params import (
    source_should_fetch_permissions_during_indexing,
)

from onyx.configs.constants import DocumentSource


def test_cr_permission_switch_is_redmine_only() -> None:
    assert source_should_fetch_permissions_during_indexing(DocumentSource.REDMINE)
    assert not source_should_fetch_permissions_during_indexing(DocumentSource.WEB)


def test_core_permission_switch_uses_ce_extension() -> None:
    from onyx.access.access import source_should_fetch_permissions_during_indexing

    with patch(
        "onyx.access.access.fetch_ce_extension_implementation_with_fallback",
        return_value=lambda source: source == DocumentSource.REDMINE,
    ):
        assert source_should_fetch_permissions_during_indexing(DocumentSource.REDMINE)
        assert not source_should_fetch_permissions_during_indexing(DocumentSource.WEB)
