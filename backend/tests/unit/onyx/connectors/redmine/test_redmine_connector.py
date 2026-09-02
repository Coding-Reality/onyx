from collections.abc import Generator
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import patch

import pytest
from cr_onyx.tenancy.integrations import RedmineTenantBinding
from pydantic import ValidationError

from onyx.access.models import ExternalAccess
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.models import (
    ConnectorFailure,
    Document,
    HierarchyNode,
    SlimDocument,
)
from onyx.connectors.redmine.client import RedmineClient, RedmineClientError
from onyx.connectors.redmine.connector import (
    RedmineConnector,
)
from onyx.connectors.redmine.models import (
    RedmineAttachment,
    RedmineCheckpoint,
    RedmineProject,
    RedmineWikiPage,
    RedmineWikiPageSummary,
)
from onyx.connectors.redmine.wiki import (
    attachment_document_id,
    project_node_id,
    split_commonmark_sections,
    wiki_page_id,
)

NOW = datetime(2026, 9, 2, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def enable_redmine_feature_flags() -> Generator[None, None, None]:
    with (
        patch("onyx.connectors.redmine.connector.REDMINE_CONNECTOR_ENABLED", True),
        patch("onyx.connectors.redmine.connector.REDMINE_ATTACHMENTS_ENABLED", True),
        patch(
            "onyx.connectors.redmine.connector.REDMINE_PERMISSION_SYNC_ENABLED", True
        ),
    ):
        yield


class FakeRedmineClient:
    def __init__(self) -> None:
        self.projects = [
            RedmineProject(id=1, identifier="tenant-a", name="Tenant A"),
            RedmineProject(
                id=2,
                identifier="project-a",
                name="Project A",
                parent_id=1,
            ),
        ]
        self.summaries = {
            "tenant-a": [],
            "project-a": [
                RedmineWikiPageSummary(
                    title="Parent",
                    version=2,
                    created_on=NOW,
                    updated_on=NOW,
                ),
                RedmineWikiPageSummary(
                    title="Child",
                    parent_title="Parent",
                    version=3,
                    created_on=NOW,
                    updated_on=NOW,
                ),
            ],
        }
        self.pages = {
            "Parent": RedmineWikiPage(
                title="Parent",
                text="# Purpose\nUseful text",
                version=2,
                author_name="Author",
                created_on=NOW,
                updated_on=NOW,
            ),
            "Child": RedmineWikiPage(
                title="Child",
                text="Child text",
                version=3,
                created_on=NOW,
                updated_on=NOW,
                attachments=[
                    RedmineAttachment(
                        id=9,
                        filename="notes.md",
                        filesize=5,
                        content_type="text/markdown",
                        content_url="https://redmine.example/attachments/download/9",
                        created_on=NOW,
                    )
                ],
            ),
        }

    def list_projects(self) -> list[RedmineProject]:
        return self.projects

    def list_wiki_pages(self, project_identifier: str) -> list[RedmineWikiPageSummary]:
        return self.summaries[project_identifier]

    def get_wiki_page(
        self,
        _project_identifier: str,
        page_title: str,
    ) -> RedmineWikiPage:
        return self.pages[page_title]

    def download_attachment(self, content_url: str) -> bytes:  # noqa: ARG002
        return b"notes"


def configured_connector(include_attachments: bool = False) -> RedmineConnector:
    connector = RedmineConnector(
        base_url="https://redmine.example",
        root_project_id=1,
        include_attachments=include_attachments,
        batch_size=1,
    )
    connector.load_credentials({"redmine_api_key": "secret"})
    cast(Any, connector)._client = FakeRedmineClient()
    return connector


def drain_checkpoint(
    generator: Generator[Any, None, RedmineCheckpoint],
) -> tuple[list[Any], RedmineCheckpoint]:
    values = []
    while True:
        try:
            values.append(next(generator))
        except StopIteration as stop:
            return values, stop.value


def test_split_commonmark_sections_keeps_fenced_heading_text() -> None:
    sections = split_commonmark_sections(
        "Runbook",
        "Operations",
        "# Deploy\nStep one\n```text\n# not a heading\n```\n## Check\nDone",
        "https://redmine.example/wiki/Runbook",
    )

    assert [section.heading for section in sections] == ["Deploy", "Check"]
    assert "# not a heading" in sections[0].text
    assert sections[1].text.startswith("Operations / Runbook / Check")


def test_checkpoint_is_bounded_and_preserves_page_hierarchy() -> None:
    connector = configured_connector()
    first_values, first_checkpoint = drain_checkpoint(
        connector.load_from_checkpoint(
            NOW.timestamp() - 60,
            NOW.timestamp() + 60,
            RedmineCheckpoint(has_more=True, project_index=1),
        )
    )

    assert first_checkpoint == RedmineCheckpoint(
        has_more=True, project_index=1, page_offset=1
    )
    assert any(
        isinstance(value, HierarchyNode)
        and value.raw_node_id == wiki_page_id(2, "Parent")
        for value in first_values
    )
    parent_document = next(
        value for value in first_values if isinstance(value, Document)
    )
    assert parent_document.parent_hierarchy_raw_node_id == project_node_id(2)

    second_values, second_checkpoint = drain_checkpoint(
        connector.load_from_checkpoint(
            NOW.timestamp() - 60,
            NOW.timestamp() + 60,
            first_checkpoint,
        )
    )
    assert second_checkpoint.has_more is False
    child_document = next(
        value for value in second_values if isinstance(value, Document)
    )
    assert child_document.parent_hierarchy_raw_node_id == wiki_page_id(2, "Parent")


def test_page_failure_does_not_abort_checkpoint() -> None:
    connector = configured_connector()
    fake_client = connector._client
    assert isinstance(fake_client, FakeRedmineClient)

    def fail_page(_project_identifier: str, _page_title: str) -> RedmineWikiPage:
        raise RedmineClientError("bad page")

    cast(Any, fake_client).get_wiki_page = fail_page
    values, checkpoint = drain_checkpoint(
        connector.load_from_checkpoint(
            NOW.timestamp() - 60,
            NOW.timestamp() + 60,
            RedmineCheckpoint(has_more=True, project_index=1),
        )
    )

    assert any(isinstance(value, ConnectorFailure) for value in values)
    assert checkpoint.page_offset == 1


def test_visible_foreign_project_fails_closed() -> None:
    connector = configured_connector()
    fake_client = connector._client
    assert isinstance(fake_client, FakeRedmineClient)
    fake_client.projects.append(
        RedmineProject(id=99, identifier="tenant-b", name="Tenant B")
    )

    with pytest.raises(ConnectorValidationError, match="outside the approved root"):
        connector.validate_connector_settings()


def test_disabled_feature_flag_fails_closed() -> None:
    connector = configured_connector()

    with (
        patch("onyx.connectors.redmine.connector.REDMINE_CONNECTOR_ENABLED", False),
        pytest.raises(ConnectorValidationError, match="disabled"),
    ):
        connector.validate_connector_settings()


def test_permission_sync_validation_requires_feature_and_acl_snapshot() -> None:
    connector = configured_connector()
    with (
        patch(
            "onyx.connectors.redmine.connector.REDMINE_PERMISSION_SYNC_ENABLED", False
        ),
        pytest.raises(ConnectorValidationError, match="permission sync is disabled"),
    ):
        connector.validate_redmine_permission_sync()

    with (
        patch(
            "onyx.connectors.redmine.connector.tenant_wiki_access",
            side_effect=ConnectorValidationError("no mapped identities"),
        ),
        pytest.raises(ConnectorValidationError, match="no mapped identities"),
    ):
        connector.validate_redmine_permission_sync()


def test_slim_enumeration_includes_enabled_attachment_ids() -> None:
    connector = configured_connector(include_attachments=True)
    batches = list(connector.retrieve_all_slim_docs())
    slim_ids = {
        item.id for batch in batches for item in batch if isinstance(item, SlimDocument)
    }

    assert wiki_page_id(2, "Child") in slim_ids
    assert attachment_document_id(9) in slim_ids


def test_permission_sync_applies_fail_closed_acl_to_docs_nodes_and_slim() -> None:
    connector = configured_connector()
    access = ExternalAccess(
        external_user_emails={"member@example.com"},
        external_user_group_ids=set(),
        is_public=False,
    )
    with patch(
        "onyx.connectors.redmine.connector.tenant_wiki_access", return_value=access
    ):
        values, _ = drain_checkpoint(
            connector.load_from_checkpoint_with_perm_sync(
                NOW.timestamp() - 60,
                NOW.timestamp() + 60,
                RedmineCheckpoint(has_more=True, project_index=1),
            )
        )
        slim_batches = list(connector.retrieve_all_slim_docs_perm_sync())

    protected = [
        value for value in values if isinstance(value, (Document, HierarchyNode))
    ]
    assert protected
    assert all(value.external_access == access for value in protected)
    assert all(
        item.external_access == access
        for batch in slim_batches
        for item in batch
        if isinstance(item, SlimDocument)
    )
    assert any(
        isinstance(item, HierarchyNode) and item.external_access == access
        for batch in slim_batches
        for item in batch
    )


@patch("onyx.connectors.redmine.connector.extract_file_text", return_value="notes")
def test_enabled_attachment_is_a_child_document(_extract_file_text: Any) -> None:
    connector = configured_connector(include_attachments=True)
    values, _ = drain_checkpoint(
        connector.load_from_checkpoint(
            NOW.timestamp() - 60,
            NOW.timestamp() + 60,
            RedmineCheckpoint(has_more=True, project_index=1, page_offset=1),
        )
    )
    attachment = next(
        value
        for value in values
        if isinstance(value, Document) and value.id == attachment_document_id(9)
    )

    assert attachment.parent_hierarchy_raw_node_id == wiki_page_id(2, "Child")
    assert attachment.metadata["resource_type"] == "wiki_attachment"


def test_attachment_failure_does_not_hide_parent_page() -> None:
    connector = configured_connector(include_attachments=True)
    fake_client = connector._client
    assert isinstance(fake_client, FakeRedmineClient)
    cast(Any, fake_client).download_attachment = lambda _url: b""
    values, _ = drain_checkpoint(
        connector.load_from_checkpoint(
            NOW.timestamp() - 60,
            NOW.timestamp() + 60,
            RedmineCheckpoint(has_more=True, project_index=1, page_offset=1),
        )
    )

    assert any(
        isinstance(value, Document) and value.id == wiki_page_id(2, "Child")
        for value in values
    )
    assert any(
        isinstance(value, ConnectorFailure)
        and value.failed_document is not None
        and value.failed_document.document_id == attachment_document_id(9)
        for value in values
    )


def test_client_rejects_cross_origin_attachment_url() -> None:
    client = RedmineClient("https://redmine.example", "secret")

    with pytest.raises(RedmineClientError, match="cross-origin"):
        client.download_attachment("https://attacker.example/file")


def test_client_paginates_project_inventory() -> None:
    client = RedmineClient("https://redmine.example", "secret")
    first_page = {
        "projects": [
            {
                "id": 1,
                "identifier": "tenant-a",
                "name": "Tenant A",
                "is_public": False,
                "status": 1,
            }
        ],
        "total_count": 2,
    }
    second_page = {
        "projects": [
            {
                "id": 2,
                "identifier": "project-a",
                "name": "Project A",
                "is_public": False,
                "status": 1,
                "parent": {"id": 1},
            }
        ],
        "total_count": 2,
    }

    with patch.object(
        client, "_get_json", side_effect=[first_page, second_page]
    ) as get:
        projects = client.list_projects()

    assert [project.id for project in projects] == [1, 2]
    assert projects[1].parent_id == 1
    assert get.call_args_list[0].kwargs["params"]["offset"] == 0
    assert get.call_args_list[1].kwargs["params"]["offset"] == 1


@patch("cr_onyx.connectors.redmine.tenant_guard.redmine_binding_for_current_tenant")
def test_cr_tenant_guard_rejects_mismatched_root(binding: Any) -> None:
    from cr_onyx.connectors.redmine.tenant_guard import enforce_tenant_binding

    binding.return_value = {
        "schema_version": 1,
        "revenueos_tenant_id": "tenant-coding-reality",
        "enabled": True,
        "base_url": "https://redmine.example",
        "root_project_id": 1,
        "redmine_group_id": 6,
    }

    with pytest.raises(ConnectorValidationError, match="root"):
        enforce_tenant_binding("https://redmine.example", 2)


def test_redmine_tenant_binding_is_secret_free_and_strict() -> None:
    binding = RedmineTenantBinding(
        revenueos_tenant_id="tenant-coding-reality",
        base_url="https://redmine.example/",
        root_project_id=1,
        redmine_group_id=6,
    )

    assert binding.base_url == "https://redmine.example"
    assert binding.enabled is False
    with pytest.raises(ValidationError):
        RedmineTenantBinding(
            revenueos_tenant_id="tenant-coding-reality",
            base_url="http://redmine.example",
            root_project_id=1,
            redmine_group_id=6,
            api_key="must-not-be-accepted",  # ty: ignore[unknown-argument]
        )
