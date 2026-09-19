"""
Pydantic models for API requests/responses
"""
import re
import csv
import io
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EntityResolveRequest(BaseModel):
    """Request to resolve entity name."""
    text: str = Field(..., min_length=1, description="Text to resolve")
    entity_type: Optional[str] = Field(None, description="Optional entity type hint")
    context: Optional[str] = Field(None, description="Optional context")


class EntityResolveResponse(BaseModel):
    """Response from entity resolution."""
    state: str = Field(..., description="Resolution state")
    entity_id: Optional[str] = Field(None, description="Resolved entity ID")
    canonical_name: Optional[str] = Field(None, description="Canonical name")
    confidence: float = Field(..., description="Confidence (0-1)")
    reasoning: str = Field(..., description="Explanation")


class EntityCreateRequest(BaseModel):
    """Request to create entity."""
    canonical_name: str = Field(..., min_length=1, description="Authoritative name")
    entity_type: Optional[str] = Field(None, description="Entity type")
    acronyms: Optional[List[str]] = Field(None, description="Known acronyms")
    notes: Optional[str] = Field(None, description="Additional notes")


class EntityCreateResponse(BaseModel):
    """Response from entity creation."""
    entity_id: str
    canonical_name: str
    entity_type: Optional[str]
    acronyms: List[str]


class BuildJobRequest(BaseModel):
    """Request to build a node."""
    entity_name: str = Field(..., description="Entity to build")
    entity_type: Optional[str] = Field(None, description="Entity type")
    rita_id: Optional[str] = Field(None, description="RITA entity ID")


class BuildJobResponse(BaseModel):
    """Response with job ID."""
    job_id: str
    status: str = "QUEUED"
    entity_name: str


class SourceProvenance(BaseModel):
    """Traceability reference for a value or knowledge object."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1)
    source_type: Optional[str] = Field(None, min_length=1)
    source_uri: Optional[str] = Field(None, min_length=1)
    excerpt: Optional[str] = None
    collected_at: Optional[datetime] = None


class ValidationResult(BaseModel):
    """Deterministic validation report."""

    valid: bool
    errors: List[str] = Field(default_factory=list)


class NodeDraft(BaseModel):
    """Markdown draft for an evidence-backed node before writing or graph expansion."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", min_length=0)
    frontmatter: Dict[str, Any] = Field(default_factory=dict)
    body: str = ""
    source_claims: List[Any] = Field(default_factory=list)

    def render_markdown(self) -> str:
        if not self.title and not self.body and not self.frontmatter:
            return ""

        lines: List[str] = ["---"]
        for key, value in self.frontmatter.items():
            if isinstance(value, list):
                lines.append(f"{key}:")
                for item in value:
                    lines.append(f"  - {item}")
            else:
                if value is None or value == "":
                    continue
                lines.append(f"{key}: {value}")
        lines.append("---")
        if self.body.strip():
            lines.extend(["", self.body.strip()])
        return "\n".join(lines) + "\n"


class CanonicalEntity(BaseModel):
    """Canonical entity identity used to prevent duplicate node creation."""

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(..., min_length=1)
    uid: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    entity_type: Optional[str] = None
    subtype: Optional[str] = None
    resolution_status: str = "resolved"

    @field_validator("entity")
    @classmethod
    def validate_entity(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("entity is required")
        return cleaned

    @field_validator("uid")
    @classmethod
    def validate_uid(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("uid is required")
        return cleaned


class CanonicalNodeRow(BaseModel):
    """Deterministic import-ready representation of one ATIS node."""

    model_config = ConfigDict(extra="forbid")

    uid: str = Field(..., min_length=1)
    entity: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    entity_type: Optional[str] = None
    subtype: Optional[str] = None
    country: Optional[str] = None
    sector: Optional[str] = None
    status: Optional[str] = None
    summary: str = Field(..., min_length=1)
    relationships: List[str] = Field(default_factory=list)
    associations: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)

    @field_validator("entity")
    @classmethod
    def validate_entity(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("entity is required")
        return cleaned

    @field_validator("summary")
    @classmethod
    def validate_summary(cls, value: str, info: Any) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("summary is required")

        entity = (info.data.get("entity") if isinstance(info.data, dict) else "") or ""
        entity_name = str(entity).strip()
        if entity_name and entity_name.lower() not in cleaned.lower():
            raise ValueError("summary must contain the subject")

        if not re.search(
            r"\b(is|regulates|manages|oversees|operates|functions|responsible|supports|coordinates|monitors|provides|governs|requires|controls|maintains|administers|helps|delivers|develops|handles|supports)\b",
            cleaned,
            flags=re.IGNORECASE,
        ):
            raise ValueError("summary must explain the subject's function or role")

        if "[[" not in cleaned or "]]" not in cleaned:
            raise ValueError("summary must include graph links where expected")
        return cleaned

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in (value or []) if isinstance(item, str) and item.strip()]
        if not cleaned:
            raise ValueError("at least one source is required")
        return cleaned

    def serialize_csv(self) -> str:
        rows = [
            "uid",
            "entity",
            "aliases",
            "entity_type",
            "subtype",
            "country",
            "sector",
            "status",
            "summary",
            "relationships",
            "associations",
            "sources",
        ]
        values = [
            self.uid,
            self.entity,
            "|".join(self.aliases),
            self.entity_type or "",
            self.subtype or "",
            self.country or "",
            self.sector or "",
            self.status or "",
            self.summary,
            "|".join(self.relationships),
            "|".join(self.associations),
            "|".join(self.sources),
        ]
        return "|".join(rows) + "\n" + "|".join(values)


DEFAULT_IMPORT_TEMPLATE = """---
entity: {{entity}}
aliases:
{{aliases_list}}
entity_type: {{entity_type}}
subtype: {{subtype}}
country:
{{country_list}}
sector:
{{sector_list}}
status: {{status}}
sources:
{{sources_list}}
---

# {{entity}}

## Summary

{{summary}}

## Relationships

{{relationships_list}}

## Associations

{{associations_list}}
"""


class ImportBundle(BaseModel):
    """Import-ready bundle of canonical rows, CSV, JSON, and a markdown template."""

    model_config = ConfigDict(extra="forbid")

    rows: List["CanonicalNodeRow"] = Field(default_factory=list)
    csv_text: str = ""
    json_text: str = ""
    template_text: str = DEFAULT_IMPORT_TEMPLATE

    @classmethod
    def from_rows(cls, rows: List["CanonicalNodeRow"]) -> "ImportBundle":
        normalized = list(rows or [])
        if not normalized:
            return cls(rows=[], csv_text="", json_text="[]", template_text=DEFAULT_IMPORT_TEMPLATE)

        csv_text = _canonical_csv_text(normalized)
        json_text = json.dumps([row.model_dump(mode="json") for row in normalized], ensure_ascii=False, indent=2)
        return cls(rows=normalized, csv_text=csv_text, json_text=json_text, template_text=DEFAULT_IMPORT_TEMPLATE)

    def render_markdown(self, row: Optional["CanonicalNodeRow"] = None) -> str:
        target = row if row is not None else (self.rows[0] if self.rows else None)
        if target is None:
            return ""

        rendered = self.template_text
        rendered = rendered.replace("{{entity}}", target.entity)
        rendered = rendered.replace("{{entity_type}}", target.entity_type or "")
        rendered = rendered.replace("{{subtype}}", target.subtype or "")
        rendered = rendered.replace("{{status}}", target.status or "")
        rendered = rendered.replace("{{summary}}", target.summary)
        rendered = rendered.replace("{{aliases_list}}", _as_yaml_list(target.aliases, empty_value="[]"))
        rendered = rendered.replace("{{country_list}}", _as_yaml_list(_coerce_list(target.country), empty_value="[]"))
        rendered = rendered.replace("{{sector_list}}", _as_yaml_list(_coerce_list(target.sector), empty_value="[]"))
        rendered = rendered.replace("{{sources_list}}", _as_yaml_list(target.sources, empty_value="[]"))
        rendered = rendered.replace("{{relationships_list}}", _as_markdown_list(target.relationships, empty_value="- none"))
        rendered = rendered.replace("{{associations_list}}", _as_markdown_list(target.associations, empty_value="- none"))
        return rendered


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _as_yaml_list(values: List[str], empty_value: str = "[]") -> str:
    cleaned = [str(item).strip() for item in (values or []) if str(item).strip()]
    if not cleaned:
        return empty_value
    return "\n".join(f"  - {item}" for item in cleaned)


def _as_markdown_list(values: List[str], empty_value: str = "- none") -> str:
    cleaned = [str(item).strip() for item in (values or []) if str(item).strip()]
    if not cleaned:
        return empty_value
    return "\n".join(f"- {item}" for item in cleaned)


def _canonical_csv_text(rows: List["CanonicalNodeRow"]) -> str:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow([
        "uid",
        "entity",
        "aliases",
        "entity_type",
        "subtype",
        "country",
        "sector",
        "status",
        "summary",
        "relationships",
        "associations",
        "sources",
    ])
    for row in rows:
        writer.writerow([
            row.uid,
            row.entity,
            "|".join(row.aliases),
            row.entity_type or "",
            row.subtype or "",
            row.country or "",
            row.sector or "",
            row.status or "",
            row.summary,
            "|".join(row.relationships),
            "|".join(row.associations),
            "|".join(row.sources),
        ])
    return output.getvalue()


class ATISNode(BaseModel):
    """Validated generic node until the canonical ATIS field schema is supplied."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(..., min_length=1)
    entity_id: str = Field(..., min_length=1)
    canonical_name: str = Field(..., min_length=1)
    entity_type: Optional[str] = Field(None, min_length=1)
    fields: Dict[str, Any] = Field(default_factory=dict)
    provenance: List[SourceProvenance] = Field(..., min_length=1)
    validation_status: str = "VALIDATED"

    @field_validator("fields")
    @classmethod
    def validate_field_names(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        if any(not isinstance(name, str) or not name.strip() for name in value):
            raise ValueError("field names must be non-empty strings")
        return value


class NodeRelationship(BaseModel):
    """An explicitly asserted, provenance-backed relationship."""

    model_config = ConfigDict(extra="forbid")

    relationship_id: Optional[str] = None
    source_node_id: str = Field(..., min_length=1)
    target_entity_id: str = Field(..., min_length=1)
    relationship_type: str = Field(..., min_length=1)
    provenance: List[SourceProvenance] = Field(..., min_length=1)


class NodeCreateRequest(BaseModel):
    """Request to build and store a validated node."""

    node_id: str = Field(..., min_length=1)
    entity_name: str = Field(..., min_length=1)
    fields: Dict[str, Any] = Field(default_factory=dict)
    source_id: str = Field(..., min_length=1)
    source_type: Optional[str] = Field(None, min_length=1)
    source_uri: Optional[str] = Field(None, min_length=1)
    excerpt: Optional[str] = None


class RelationshipCreateRequest(BaseModel):
    """Request to store an explicitly asserted relationship."""

    target_entity_id: str = Field(..., min_length=1)
    relationship_type: str = Field(..., min_length=1)
    provenance: List[SourceProvenance] = Field(..., min_length=1)
