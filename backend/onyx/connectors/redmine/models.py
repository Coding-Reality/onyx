from datetime import datetime

from pydantic import BaseModel, Field

from onyx.connectors.models import ConnectorCheckpoint


class RedmineCheckpoint(ConnectorCheckpoint):
    project_index: int = 0
    page_offset: int = 0


class RedmineProject(BaseModel):
    id: int
    identifier: str
    name: str
    is_public: bool = False
    status: int = 1
    parent_id: int | None = None
    custom_fields: dict[str, str] = Field(default_factory=dict)


class RedmineWikiPageSummary(BaseModel):
    title: str
    parent_title: str | None = None
    version: int
    created_on: datetime
    updated_on: datetime


class RedmineAttachment(BaseModel):
    id: int
    filename: str
    filesize: int
    content_type: str
    content_url: str
    description: str | None = None
    author_name: str | None = None
    created_on: datetime | None = None


class RedmineWikiPage(BaseModel):
    title: str
    text: str
    version: int
    author_name: str | None = None
    comments: str | None = None
    created_on: datetime
    updated_on: datetime
    attachments: list[RedmineAttachment] = Field(default_factory=list)
