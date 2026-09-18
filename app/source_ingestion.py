"""Deterministic source ingestion and markdown parsing for NORA."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Tuple


@dataclass
class SourceDocument:
    """Structured representation of a source document."""

    path: str
    filename: str
    raw_content: str
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    title: str = ""
    body: str = ""
    links: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class MarkdownSourceParser:
    """Parse Markdown source documents and preserve available metadata."""

    def __init__(self):
        self.wikilink_pattern = re.compile(r"\[\[([^\]]+)\]\]")
        self.inline_link_pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
        self.frontmatter_pattern = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)
        self.heading_pattern = re.compile(r"^#\s+(.*)$", re.MULTILINE)

    def parse(self, source_path: str | Path) -> SourceDocument:
        file_path = Path(source_path)
        raw_content = file_path.read_text(encoding="utf-8") if file_path.exists() else ""

        frontmatter: Dict[str, Any] = {}
        content = raw_content
        match = self.frontmatter_pattern.match(raw_content)
        if match:
            frontmatter = self._parse_frontmatter(match.group(1))
            content = raw_content[match.end():]

        title = self._extract_title(frontmatter, content)
        body = self._clean_body(content)
        links = self._extract_links(body)
        references = self._extract_references(body, links)

        return SourceDocument(
            path=str(file_path),
            filename=file_path.name,
            raw_content=raw_content,
            frontmatter=frontmatter,
            title=title,
            body=body,
            links=links,
            references=references,
            metadata={
                "source_type": "markdown",
                "link_count": len(links),
                "reference_count": len(references),
            },
        )

    def _parse_frontmatter(self, frontmatter_text: str) -> Dict[str, Any]:
        parsed: Dict[str, Any] = {}
        for line in frontmatter_text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            parsed[key] = self._coerce_scalar(value)
        return parsed

    def _coerce_scalar(self, value: str) -> Any:
        if value in {"", "null", "Null", "NULL"}:
            return ""
        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if re.fullmatch(r"-?\d+", value):
            return int(value)
        if re.fullmatch(r"-?\d+\.\d+", value):
            return float(value)
        return value.strip("\"'")

    def _extract_title(self, frontmatter: Dict[str, Any], content: str) -> str:
        for key in ("title", "name", "entity", "entity_name", "subject"):
            value = frontmatter.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        match = self.heading_pattern.search(content)
        if match:
            return match.group(1).strip()

        return ""

    def _clean_body(self, content: str) -> str:
        cleaned = content.strip()
        if not cleaned:
            return ""
        return cleaned

    def _extract_links(self, body: str) -> List[str]:
        links: List[str] = []
        for label, target in self.inline_link_pattern.findall(body):
            label = label.strip()
            target = target.strip()
            if label:
                links.append(label)
            elif target:
                links.append(target)
        for item in self.wikilink_pattern.findall(body):
            value = item.strip()
            if value and value not in links:
                links.append(value)
        return links

    def _extract_references(self, body: str, links: List[str]) -> List[str]:
        references: List[str] = []
        for link in links:
            if link and link not in references:
                references.append(link)

        for line in body.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.lower().startswith("references:"):
                remaining = stripped.split(":", 1)[1].strip()
                if remaining:
                    references.append(remaining)
        return references


def parse_markdown_source(source_path: str | Path) -> SourceDocument:
    return MarkdownSourceParser().parse(source_path)
