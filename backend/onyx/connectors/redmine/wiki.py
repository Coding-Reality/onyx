import re

from onyx.connectors.models import TextSection

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def project_node_id(project_id: int) -> str:
    return f"redmine:project:{project_id}"


def wiki_page_id(project_id: int, title: str) -> str:
    return f"redmine:wiki:{project_id}:{title}"


def attachment_document_id(attachment_id: int) -> str:
    return f"redmine:wiki_attachment:{attachment_id}"


def split_commonmark_sections(
    page_title: str, project_name: str, text: str, link: str
) -> list[TextSection]:
    """Split CommonMark at headings while preserving fenced code and body syntax."""
    sections: list[TextSection] = []
    heading: str | None = None
    body: list[str] = []
    in_fence = False

    def flush() -> None:
        content = "\n".join(body).strip()
        if not content and heading is None:
            return
        context = f"{project_name} / {page_title}"
        if heading:
            context = f"{context} / {heading}"
        sections.append(
            TextSection(
                heading=heading,
                link=link,
                text=f"{context}\n\n{content}".strip(),
            )
        )

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
        match = None if in_fence else _HEADING.match(line)
        if match:
            flush()
            body = []
            heading = match.group(2)
        else:
            body.append(line)
    flush()
    if sections:
        return sections
    return [TextSection(link=link, text=f"{project_name} / {page_title}")]
