from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cr_onyx.background.celery.tasks.redmine_permissions.tasks import (
    _authoritative_access,
    redmine_permission_reconciliation,
)
from cr_onyx.db.redmine_connector_targets import RedminePermissionTarget
from cr_onyx.db.redmine_permission_reconciliation import (
    RedminePermissionReconciliationResult,
)

from onyx.access.models import ExternalAccess
from onyx.connectors.interfaces import SlimConnectorWithPermSync
from onyx.connectors.models import HierarchyNode, SlimDocument
from onyx.db.enums import HierarchyNodeType


class _PermissionConnector(SlimConnectorWithPermSync):
    def __init__(self, batches: list[list[SlimDocument | HierarchyNode]]) -> None:
        self.batches = batches

    def load_credentials(self, credentials: dict[str, Any]) -> None:  # noqa: ARG002
        return None

    def retrieve_all_slim_docs_perm_sync(
        self, *_args: Any, **_kwargs: Any
    ) -> Iterator[list[SlimDocument | HierarchyNode]]:
        return iter(self.batches)


def test_authoritative_access_collects_documents_and_nodes() -> None:
    access = ExternalAccess(
        external_user_emails={"member@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    connector = _PermissionConnector(
        [
            [SlimDocument(id="redmine:wiki:1:Home", external_access=access)],
            [
                HierarchyNode(
                    raw_node_id="redmine:project:1",
                    display_name="Project",
                    node_type=HierarchyNodeType.PROJECT,
                    external_access=access,
                )
            ],
        ]
    )

    document_ids, node_ids, actual_access = _authoritative_access(connector)

    assert document_ids == {"redmine:wiki:1:Home"}
    assert node_ids == {"redmine:project:1"}
    assert actual_access == access


def test_authoritative_access_fails_closed_on_acl_change() -> None:
    first_access = ExternalAccess(
        external_user_emails={"first@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    second_access = ExternalAccess(
        external_user_emails={"second@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    connector = _PermissionConnector(
        [
            [SlimDocument(id="one", external_access=first_access)],
            [SlimDocument(id="two", external_access=second_access)],
        ]
    )

    with pytest.raises(RuntimeError, match="ACL changed"):
        _authoritative_access(connector)


def test_authoritative_access_fails_closed_on_empty_snapshot() -> None:
    with pytest.raises(RuntimeError, match="returned no ACL"):
        _authoritative_access(_PermissionConnector([]))


def test_periodic_task_reconciles_each_active_connector() -> None:
    access = ExternalAccess(
        external_user_emails={"member@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    connector = _PermissionConnector(
        [[SlimDocument(id="redmine:wiki:1:Home", external_access=access)]]
    )
    target = RedminePermissionTarget(
        connector_id=7,
        credential_id=8,
        connector=connector,
    )
    redis_lock = MagicMock()
    redis_lock.acquire.return_value = True
    redis_lock.owned.return_value = True
    redis = MagicMock()
    redis.lock.return_value = redis_lock
    session = MagicMock()

    @contextmanager
    def session_context():
        yield session

    result = RedminePermissionReconciliationResult(1, 2, 3, 4)
    with (
        patch(
            "cr_onyx.background.celery.tasks.redmine_permissions.tasks.get_redis_client",
            return_value=redis,
        ),
        patch(
            "cr_onyx.background.celery.tasks.redmine_permissions.tasks.redmine_sync_connectors",
            return_value=[target],
        ),
        patch(
            "cr_onyx.background.celery.tasks.redmine_permissions.tasks.get_session_with_current_tenant",
            side_effect=session_context,
        ),
        patch(
            "cr_onyx.background.celery.tasks.redmine_permissions.tasks.reconcile_redmine_permissions",
            return_value=result,
        ) as reconcile,
    ):
        actual = redmine_permission_reconciliation.run(tenant_id="tenant_example")

    assert actual == [
        {
            "documents_updated": 1,
            "documents_revoked": 2,
            "nodes_updated": 3,
            "nodes_revoked": 4,
        }
    ]
    reconcile.assert_called_once_with(
        session,
        7,
        8,
        {"redmine:wiki:1:Home"},
        set(),
        access,
    )
    redis_lock.release.assert_called_once_with()


def test_periodic_task_skips_when_tenant_lock_is_held() -> None:
    redis_lock = MagicMock()
    redis_lock.acquire.return_value = False
    redis = MagicMock()
    redis.lock.return_value = redis_lock

    with (
        patch(
            "cr_onyx.background.celery.tasks.redmine_permissions.tasks.get_redis_client",
            return_value=redis,
        ),
        patch(
            "cr_onyx.background.celery.tasks.redmine_permissions.tasks.redmine_sync_connectors"
        ) as connectors,
    ):
        actual = redmine_permission_reconciliation.run(tenant_id="tenant_example")

    assert actual == []
    connectors.assert_not_called()
    redis_lock.release.assert_not_called()
