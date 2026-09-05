import fnmatch
import os
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import quote, urlparse

from typing_extensions import override

from onyx.access.models import ExternalAccess
from onyx.configs.constants import DocumentSource, FileOrigin
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.interfaces import (
    CheckpointedConnectorWithPermSync,
    CheckpointOutput,
    GenerateSlimDocumentOutput,
    HierarchyConnector,
    HierarchyOutput,
    SecondsSinceUnixEpoch,
    SlimConnector,
    SlimConnectorWithPermSync,
)
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    ConnectorMissingCredentialError,
    Document,
    DocumentFailure,
    HierarchyNode,
    ImageSection,
    SlimDocument,
    TextSection,
)
from onyx.connectors.redmine.client import RedmineClient, RedmineClientError
from onyx.connectors.redmine.models import (
    RedmineAttachment,
    RedmineCheckpoint,
    RedmineProject,
    RedmineWikiPage,
    RedmineWikiPageSummary,
)
from onyx.connectors.redmine.permissions import tenant_wiki_access
from onyx.connectors.redmine.tenant_guard import enforce_tenant_binding
from onyx.connectors.redmine.wiki import (
    attachment_document_id,
    extract_knowledge_metadata,
    project_node_id,
    split_commonmark_sections,
    wiki_page_id,
)
from onyx.db.enums import HierarchyNodeType
from onyx.file_processing.extract_file_text import extract_file_text, get_file_ext
from onyx.file_processing.file_types import OnyxFileExtensions, OnyxMimeTypes
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.server.metrics.redmine_connector import inc_attachment
from onyx.utils.logger import setup_logger

logger = setup_logger()

REDMINE_CONNECTOR_ENABLED = (
    os.environ.get("REDMINE_CONNECTOR_ENABLED", "false").lower() == "true"
)
REDMINE_ATTACHMENTS_ENABLED = (
    os.environ.get("REDMINE_ATTACHMENTS_ENABLED", "false").lower() == "true"
)
REDMINE_PERMISSION_SYNC_ENABLED = (
    os.environ.get("REDMINE_PERMISSION_SYNC_ENABLED", "false").lower() == "true"
)

_DEFAULT_CONTENT_TYPES = [
    "application/pdf",
    "text/*",
    "application/vnd.openxmlformats-officedocument.*",
    "application/vnd.ms-excel.sheet.macroenabled.12",
    "application/epub+zip",
    "message/rfc822",
    "image/png",
    "image/jpeg",
    "image/webp",
]


class RedmineConnector(
    CheckpointedConnectorWithPermSync[RedmineCheckpoint],
    SlimConnector,
    SlimConnectorWithPermSync,
    HierarchyConnector,
):
    """Index current Redmine Wiki pages from one approved private project tree."""

    def __init__(
        self,
        base_url: str,
        root_project_id: int,
        include_subprojects: bool = True,
        include_attachments: bool = False,
        batch_size: int = 100,
        overlap_seconds: int = 300,
        max_attachment_size_mb: int = 100,
        allowed_content_types: list[str] | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.root_project_id = root_project_id
        self.include_subprojects = include_subprojects
        self.include_attachments = include_attachments
        self.batch_size = min(max(batch_size, 1), 500)
        self.overlap_seconds = min(max(overlap_seconds, 0), 3600)
        self.max_attachment_bytes = max_attachment_size_mb * 1024 * 1024
        self.allowed_content_types = (
            _DEFAULT_CONTENT_TYPES
            if allowed_content_types is None
            else allowed_content_types
        )
        self.allow_insecure_http = allow_insecure_http
        self.allow_images = False
        self._api_key: str | None = None
        self._client: RedmineClient | None = None
        self._permission_sync_active = False
        self._permission_access: ExternalAccess | None = None

    @override
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_key = credentials.get("redmine_api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ConnectorMissingCredentialError("Redmine")
        self._api_key = api_key.strip()
        self._client = None
        return None

    @override
    def set_allow_images(self, value: bool) -> None:
        self.allow_images = value

    def _get_client(self) -> RedmineClient:
        if not self._api_key:
            raise ConnectorMissingCredentialError("Redmine")
        if self._client is None:
            self._client = RedmineClient(self.base_url, self._api_key)
        return self._client

    def _validate_base_url(self) -> None:
        parsed = urlparse(self.base_url)
        if not parsed.hostname or parsed.username or parsed.password:
            raise ConnectorValidationError("Redmine base URL is invalid")
        if parsed.query or parsed.fragment:
            raise ConnectorValidationError("Redmine base URL cannot contain a query")
        if parsed.scheme != "https" and not (
            self.allow_insecure_http and parsed.scheme == "http"
        ):
            raise ConnectorValidationError("Redmine base URL must use HTTPS")

    def _scoped_projects(self) -> list[RedmineProject]:
        if not REDMINE_CONNECTOR_ENABLED:
            raise ConnectorValidationError("Redmine connector is disabled")
        if self.include_attachments and not REDMINE_ATTACHMENTS_ENABLED:
            raise ConnectorValidationError("Redmine attachment indexing is disabled")
        self._validate_base_url()
        enforce_tenant_binding(self.base_url, self.root_project_id)
        visible_projects = self._get_client().list_projects()
        by_id = {project.id: project for project in visible_projects}
        root = by_id.get(self.root_project_id)
        if root is None:
            raise ConnectorValidationError("Configured Redmine root is not visible")

        subtree_ids = {self.root_project_id}
        changed = True
        while changed:
            changed = False
            for project in visible_projects:
                if project.parent_id in subtree_ids and project.id not in subtree_ids:
                    subtree_ids.add(project.id)
                    changed = True

        foreign_ids = {project.id for project in visible_projects} - subtree_ids
        if foreign_ids:
            raise ConnectorValidationError(
                "Redmine credential can see projects outside the approved root"
            )
        for project in visible_projects:
            if project.is_public:
                raise ConnectorValidationError(
                    "Public Redmine projects are not supported"
                )
            if project.status != 1:
                raise ConnectorValidationError(
                    "Closed Redmine projects are not supported"
                )

        selected_ids = (
            subtree_ids if self.include_subprojects else {self.root_project_id}
        )
        selected_projects = sorted(
            (project for project in visible_projects if project.id in selected_ids),
            key=lambda project: project.id,
        )
        if self._permission_sync_active:
            self._permission_access = tenant_wiki_access(
                [project.id for project in selected_projects]
            )
        else:
            self._permission_access = None
        return selected_projects

    def _list_wiki_pages(self, project: RedmineProject) -> list[RedmineWikiPageSummary]:
        try:
            return self._get_client().list_wiki_pages(project.identifier)
        except RedmineClientError as error:
            if error.status_code != 404:
                raise
            # Redmine returns 404 when a project has its Wiki module disabled.
            # One such subproject must not prevent sibling projects from indexing.
            logger.info(
                "Skipping Redmine project %s because its Wiki is unavailable",
                project.id,
            )
            return []

    @override
    def validate_connector_settings(self) -> None:
        try:
            self._scoped_projects()
        except (RedmineClientError, ValueError) as error:
            raise ConnectorValidationError(str(error)) from error

    def validate_redmine_permission_sync(self) -> None:
        if not REDMINE_PERMISSION_SYNC_ENABLED:
            raise ConnectorValidationError("Redmine permission sync is disabled")
        projects = self._scoped_projects()
        tenant_wiki_access([project.id for project in projects])

    @override
    def build_dummy_checkpoint(self) -> RedmineCheckpoint:
        return RedmineCheckpoint(has_more=True)

    @override
    def validate_checkpoint_json(self, checkpoint_json: str) -> RedmineCheckpoint:
        return RedmineCheckpoint.model_validate_json(checkpoint_json)

    def _project_link(self, project: RedmineProject) -> str:
        return f"{self.base_url}/projects/{quote(project.identifier, safe='')}"

    def _wiki_link(self, project: RedmineProject, title: str) -> str:
        return (
            f"{self._project_link(project)}/wiki/"
            f"{quote(title.replace(' ', '_'), safe='')}"
        )

    def _project_node(self, project: RedmineProject) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=project_node_id(project.id),
            raw_parent_id=(
                project_node_id(project.parent_id)
                if project.id != self.root_project_id and project.parent_id is not None
                else None
            ),
            display_name=project.name,
            link=self._project_link(project),
            node_type=HierarchyNodeType.PROJECT,
            external_access=self._permission_access,
        )

    def _page_node(
        self, project: RedmineProject, summary: RedmineWikiPageSummary
    ) -> HierarchyNode:
        return HierarchyNode(
            raw_node_id=wiki_page_id(project.id, summary.title),
            raw_parent_id=(
                wiki_page_id(project.id, summary.parent_title)
                if summary.parent_title
                else project_node_id(project.id)
            ),
            display_name=summary.title,
            link=self._wiki_link(project, summary.title),
            node_type=HierarchyNodeType.PAGE,
            external_access=self._permission_access,
        )

    def _page_document(
        self,
        project: RedmineProject,
        page: RedmineWikiPage,
        parent_title: str | None,
    ) -> Document:
        link = self._wiki_link(project, page.title)
        metadata: dict[str, str | list[str]] = {
            "source": "redmine",
            "resource_type": "wiki_page",
            "project_id": str(project.id),
            "project_identifier": project.identifier,
            "project_name": project.name,
            "wiki_page_title": page.title,
            "wiki_version": str(page.version),
            "redmine_url": link,
        }
        if page.author_name:
            metadata["author"] = page.author_name
        metadata.update(extract_knowledge_metadata(page.text))
        return Document(
            id=wiki_page_id(project.id, page.title),
            sections=split_commonmark_sections(
                page.title, project.name, page.text, link
            ),
            source=DocumentSource.REDMINE,
            semantic_identifier=page.title,
            title=page.title,
            metadata=metadata,
            doc_created_at=page.created_on,
            doc_updated_at=page.updated_on,
            primary_owners=(
                [BasicExpertInfo(display_name=page.author_name)]
                if page.author_name
                else None
            ),
            parent_hierarchy_raw_node_id=(
                wiki_page_id(project.id, parent_title)
                if parent_title
                else project_node_id(project.id)
            ),
            external_access=self._permission_access,
        )

    def _attachment_allowed(self, attachment: RedmineAttachment) -> bool:
        if attachment.filesize > self.max_attachment_bytes:
            return False
        extension = get_file_ext(attachment.filename)
        if extension not in OnyxFileExtensions.ALL_ALLOWED_EXTENSIONS:
            return False
        content_type = attachment.content_type.lower()
        if not any(
            fnmatch.fnmatchcase(content_type, pattern.lower())
            for pattern in self.allowed_content_types
        ):
            return False
        if content_type.startswith("image/") and (
            not self.allow_images or content_type not in OnyxMimeTypes.IMAGE_MIME_TYPES
        ):
            return False
        return True

    def _attachment_document(
        self,
        project: RedmineProject,
        page: RedmineWikiPage,
        attachment: RedmineAttachment,
    ) -> Document:
        raw_bytes = self._get_client().download_attachment(attachment.content_url)
        if not raw_bytes:
            raise ValueError("Redmine attachment is empty")
        sections: list[TextSection | ImageSection]
        if attachment.content_type.lower().startswith("image/"):
            image_section, _ = store_image_and_create_section(
                image_data=raw_bytes,
                file_id=attachment_document_id(attachment.id),
                display_name=attachment.filename,
                media_type=attachment.content_type,
                link=attachment.content_url,
                file_origin=FileOrigin.CONNECTOR,
            )
            sections = [image_section]
        else:
            text = extract_file_text(
                file=BytesIO(raw_bytes),
                file_name=attachment.filename,
            ).strip()
            if not text:
                raise ValueError("Onyx extracted no content from the attachment")
            sections = [TextSection(text=text, link=attachment.content_url)]

        metadata: dict[str, str | list[str]] = {
            "source": "redmine",
            "resource_type": "wiki_attachment",
            "project_id": str(project.id),
            "project_identifier": project.identifier,
            "parent_page": page.title,
            "attachment_id": str(attachment.id),
            "filename": attachment.filename,
            "content_type": attachment.content_type,
            "filesize": str(attachment.filesize),
            "redmine_url": attachment.content_url,
        }
        if attachment.author_name:
            metadata["author"] = attachment.author_name
        if attachment.description:
            metadata["description"] = attachment.description
        return Document(
            id=attachment_document_id(attachment.id),
            sections=sections,
            source=DocumentSource.REDMINE,
            semantic_identifier=attachment.filename,
            title=attachment.filename,
            metadata=metadata,
            doc_created_at=attachment.created_on,
            doc_updated_at=attachment.created_on,
            primary_owners=(
                [BasicExpertInfo(display_name=attachment.author_name)]
                if attachment.author_name
                else None
            ),
            parent_hierarchy_raw_node_id=wiki_page_id(project.id, page.title),
            external_access=self._permission_access,
        )

    @override
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: RedmineCheckpoint,
    ) -> CheckpointOutput[RedmineCheckpoint]:
        if not REDMINE_PERMISSION_SYNC_ENABLED:
            raise ConnectorValidationError("Redmine permission sync is disabled")
        self._permission_sync_active = True
        try:
            return (yield from self.load_from_checkpoint(start, end, checkpoint))
        finally:
            self._permission_sync_active = False
            self._permission_access = None

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: RedmineCheckpoint,
    ) -> CheckpointOutput[RedmineCheckpoint]:
        projects = self._scoped_projects()
        if checkpoint.project_index >= len(projects):
            return RedmineCheckpoint(has_more=False)

        project = projects[checkpoint.project_index]
        summaries = self._list_wiki_pages(project)
        page_slice = summaries[
            checkpoint.page_offset : checkpoint.page_offset + self.batch_size
        ]
        yield self._project_node(project)

        window_start = datetime.fromtimestamp(
            max(0, start - self.overlap_seconds), tz=timezone.utc
        )
        window_end = datetime.fromtimestamp(end, tz=timezone.utc)
        for summary in page_slice:
            yield self._page_node(project, summary)
            if not window_start <= summary.updated_on <= window_end:
                continue
            page_id = wiki_page_id(project.id, summary.title)
            try:
                page = self._get_client().get_wiki_page(
                    project.identifier, summary.title
                )
                yield self._page_document(project, page, summary.parent_title)
            except Exception as error:
                logger.exception("Failed to read Redmine Wiki page %s", page_id)
                yield ConnectorFailure(
                    failed_document=DocumentFailure(
                        document_id=page_id,
                        document_link=self._wiki_link(project, summary.title),
                    ),
                    failure_message=str(error),
                    exception=error,
                )
                continue

            if not self.include_attachments:
                continue
            for attachment in page.attachments:
                if not self._attachment_allowed(attachment):
                    continue
                attachment_id = attachment_document_id(attachment.id)
                try:
                    document = self._attachment_document(project, page, attachment)
                    inc_attachment("success")
                    yield document
                except Exception as error:
                    inc_attachment("failure")
                    logger.exception(
                        "Failed to process Redmine attachment %s", attachment_id
                    )
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=attachment_id,
                            document_link=attachment.content_url,
                        ),
                        failure_message=str(error),
                        exception=error,
                    )

        next_offset = checkpoint.page_offset + len(page_slice)
        if next_offset < len(summaries):
            return RedmineCheckpoint(
                has_more=True,
                project_index=checkpoint.project_index,
                page_offset=next_offset,
            )
        next_project = checkpoint.project_index + 1
        return RedmineCheckpoint(
            has_more=next_project < len(projects),
            project_index=next_project,
            page_offset=0,
        )

    @override
    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        end: SecondsSinceUnixEpoch | None = None,  # noqa: ARG002
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        batch: list[SlimDocument | HierarchyNode] = []
        for project in self._scoped_projects():
            if callback and callback.should_stop():
                return
            summaries = self._list_wiki_pages(project)
            for summary in summaries:
                batch.append(SlimDocument(id=wiki_page_id(project.id, summary.title)))
                if self.include_attachments:
                    page = self._get_client().get_wiki_page(
                        project.identifier, summary.title
                    )
                    batch.extend(
                        SlimDocument(id=attachment_document_id(attachment.id))
                        for attachment in page.attachments
                        if self._attachment_allowed(attachment)
                    )
                if len(batch) >= self.batch_size:
                    yield batch
                    if callback:
                        callback.progress("redmine_slim", len(batch))
                    batch = []
        if batch:
            yield batch
            if callback:
                callback.progress("redmine_slim", len(batch))

    @override
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        if not REDMINE_PERMISSION_SYNC_ENABLED:
            raise ConnectorValidationError("Redmine permission sync is disabled")
        self._permission_sync_active = True
        try:
            for batch in self.retrieve_all_slim_docs(start, end, callback):
                access = self._permission_access
                if access is None:
                    raise ConnectorValidationError("Redmine tenant ACL is unavailable")
                yield [
                    item.model_copy(update={"external_access": access})
                    if isinstance(item, SlimDocument)
                    else item
                    for item in batch
                ]
            hierarchy_batch: list[SlimDocument | HierarchyNode] = []
            for node in self.load_hierarchy(start or 0, end or 0):
                hierarchy_batch.append(node)
                if len(hierarchy_batch) >= self.batch_size:
                    yield hierarchy_batch
                    hierarchy_batch = []
            if hierarchy_batch:
                yield hierarchy_batch
        finally:
            self._permission_sync_active = False
            self._permission_access = None

    @override
    def load_hierarchy(
        self,
        start: SecondsSinceUnixEpoch,  # noqa: ARG002
        end: SecondsSinceUnixEpoch,  # noqa: ARG002
    ) -> HierarchyOutput:
        for project in self._scoped_projects():
            yield self._project_node(project)
            for summary in self._list_wiki_pages(project):
                yield self._page_node(project, summary)
