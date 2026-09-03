import time
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from onyx.connectors.redmine.models import (
    RedmineAttachment,
    RedmineProject,
    RedmineWikiPage,
    RedmineWikiPageSummary,
)
from onyx.server.metrics.redmine_connector import observe_api_request


class RedmineClientError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RedmineClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.request_timeout_seconds = request_timeout_seconds
        self._origin = self._url_origin(self.base_url)
        self._session = requests.Session()
        self._session.headers.update(
            {"X-Redmine-API-Key": api_key, "Accept": "application/json"}
        )
        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
            respect_retry_after_header=True,
        )
        self._session.mount(self.base_url, HTTPAdapter(max_retries=retry))

    @staticmethod
    def _url_origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80 if scheme == "http" else None
        return scheme, (parsed.hostname or "").lower(), port

    def _same_origin_url(self, url: str) -> str:
        absolute_url = urljoin(f"{self.base_url}/", url)
        if self._url_origin(absolute_url) != self._origin:
            raise RedmineClientError("Redmine returned a cross-origin URL")
        return absolute_url

    def _get_json(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            response = self._session.get(
                self._same_origin_url(path),
                params=params,
                timeout=self.request_timeout_seconds,
            )
        except Exception:
            observe_api_request("json", "transport_error", time.monotonic() - started)
            raise
        observe_api_request("json", str(response.status_code), time.monotonic() - started)
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            raise RedmineClientError(
                f"Redmine API request failed with status {response.status_code}",
                status_code=response.status_code,
            ) from error
        payload = response.json()
        if not isinstance(payload, dict):
            raise RedmineClientError("Redmine returned an invalid JSON object")
        return payload

    def list_projects(self) -> list[RedmineProject]:
        offset = 0
        limit = 100
        projects: list[RedmineProject] = []
        while True:
            payload = self._get_json(
                "projects.json",
                params={"limit": limit, "offset": offset},
            )
            raw_projects = payload.get("projects")
            if not isinstance(raw_projects, list):
                raise RedmineClientError("Redmine project response has no project list")
            for raw_project in raw_projects:
                if not isinstance(raw_project, dict):
                    continue
                custom_fields = {
                    str(field.get("name")): str(field.get("value"))
                    for field in raw_project.get("custom_fields", [])
                    if isinstance(field, dict)
                    and field.get("name")
                    and field.get("value")
                }
                parent = raw_project.get("parent") or {}
                projects.append(
                    RedmineProject(
                        id=raw_project["id"],
                        identifier=raw_project["identifier"],
                        name=raw_project["name"],
                        is_public=bool(raw_project.get("is_public", False)),
                        status=int(raw_project.get("status", 1)),
                        parent_id=parent.get("id"),
                        custom_fields=custom_fields,
                    )
                )
            total_count = int(payload.get("total_count", len(projects)))
            offset += len(raw_projects)
            if not raw_projects or offset >= total_count:
                return projects

    def list_wiki_pages(self, project_identifier: str) -> list[RedmineWikiPageSummary]:
        encoded_project = quote(project_identifier, safe="")
        payload = self._get_json(f"projects/{encoded_project}/wiki/index.json")
        raw_pages = payload.get("wiki_pages")
        if not isinstance(raw_pages, list):
            raise RedmineClientError("Redmine Wiki response has no page list")
        summaries = []
        for raw_page in raw_pages:
            parent = raw_page.get("parent") or {}
            summaries.append(
                RedmineWikiPageSummary(
                    title=raw_page["title"],
                    parent_title=parent.get("title"),
                    version=raw_page["version"],
                    created_on=raw_page["created_on"],
                    updated_on=raw_page["updated_on"],
                )
            )
        by_title = {page.title: page for page in summaries}
        emitted: set[str] = set()
        ordered: list[RedmineWikiPageSummary] = []
        pending = sorted(summaries, key=lambda page: page.title.casefold())
        while pending:
            ready = [
                page
                for page in pending
                if page.parent_title is None
                or page.parent_title in emitted
                or page.parent_title not in by_title
            ]
            if not ready:
                # A malformed source cycle must not make indexing loop forever.
                ready = [pending[0]]
            for page in ready:
                ordered.append(page)
                emitted.add(page.title)
                pending.remove(page)
        return ordered

    def get_wiki_page(
        self, project_identifier: str, page_title: str
    ) -> RedmineWikiPage:
        encoded_project = quote(project_identifier, safe="")
        encoded_title = quote(page_title, safe="")
        payload = self._get_json(
            f"projects/{encoded_project}/wiki/{encoded_title}.json",
            params={"include": "attachments"},
        )
        raw_page = payload.get("wiki_page")
        if not isinstance(raw_page, dict):
            raise RedmineClientError("Redmine Wiki response has no page")
        attachments = []
        for raw_attachment in raw_page.get("attachments", []):
            author = raw_attachment.get("author") or {}
            attachments.append(
                RedmineAttachment(
                    id=raw_attachment["id"],
                    filename=raw_attachment["filename"],
                    filesize=raw_attachment["filesize"],
                    content_type=raw_attachment.get("content_type")
                    or "application/octet-stream",
                    content_url=raw_attachment["content_url"],
                    description=raw_attachment.get("description"),
                    author_name=author.get("name"),
                    created_on=raw_attachment.get("created_on"),
                )
            )
        author = raw_page.get("author") or {}
        return RedmineWikiPage(
            title=raw_page["title"],
            text=raw_page.get("text") or "",
            version=raw_page["version"],
            author_name=author.get("name"),
            comments=raw_page.get("comments"),
            created_on=raw_page["created_on"],
            updated_on=raw_page["updated_on"],
            attachments=attachments,
        )

    def download_attachment(self, content_url: str) -> bytes:
        next_url = self._same_origin_url(content_url)
        for _ in range(4):
            started = time.monotonic()
            try:
                response = self._session.get(
                    next_url,
                    timeout=self.request_timeout_seconds,
                    allow_redirects=False,
                )
            except Exception:
                observe_api_request(
                    "attachment", "transport_error", time.monotonic() - started
                )
                raise
            observe_api_request(
                "attachment", str(response.status_code), time.monotonic() - started
            )
            if response.is_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise RedmineClientError("Attachment redirect has no location")
                next_url = self._same_origin_url(urljoin(next_url, location))
                continue
            try:
                response.raise_for_status()
            except requests.HTTPError as error:
                raise RedmineClientError(
                    f"Attachment download failed with status {response.status_code}"
                ) from error
            return response.content
        raise RedmineClientError("Attachment download exceeded redirect limit")
