"""RITA ENTITY_RAW intake conversion and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.services.google_sheets import GoogleSheetsReader


class RITAValidationError(ValueError):
    """Raised when a row cannot be converted into a valid RITA entity."""


class RITAEntityNotFoundError(RITAValidationError):
    """Raised when a requested entity_id is not present in the intake set."""


@dataclass(frozen=True)
class RITAEntity:
    """Typed representation of one validated RITA entity row."""

    entity_id: str
    name: str
    rita_type: str
    aliases: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    source_ids: List[str] = field(default_factory=list)
    source_count: int = 0
    extracted_at: str = ""
    extraction_run_id: str = ""
    raw_json: Dict[str, Any] = field(default_factory=dict)
    ingestion_status: str = ""

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "RITAEntity":
        """Convert a raw ENTITY_RAW dictionary into a validated RITAEntity."""
        mapping = dict(row)
        raw_json = mapping.get("raw_json")
        if raw_json is None:
            raw_json = dict(mapping)
        if not isinstance(raw_json, dict):
            raise RITAValidationError("raw_json must be a dictionary for a valid RITA entity row")

        raw_json = dict(raw_json)

        required_fields = (
            "entity_id",
            "name",
            "rita_type",
            "aliases",
            "metadata",
            "source_ids",
            "source_count",
            "extracted_at",
            "extraction_run_id",
            "raw_json",
            "ingestion_status",
        )
        missing_fields = [field_name for field_name in required_fields if field_name not in mapping or mapping.get(field_name) is None]
        if missing_fields:
            raise RITAValidationError(f"RITA row is missing required fields: {', '.join(missing_fields)}")

        blank_fields = [
            field_name
            for field_name in ("entity_id", "name", "rita_type", "extracted_at", "extraction_run_id", "ingestion_status")
            if isinstance(mapping.get(field_name), str) and not str(mapping.get(field_name)).strip()
        ]
        if blank_fields:
            raise RITAValidationError(f"RITA row contains blank required fields: {', '.join(blank_fields)}")

        aliases = cls._parse_string_list(mapping.get("aliases"), "aliases")
        source_ids = cls._parse_string_list(mapping.get("source_ids"), "source_ids")
        metadata = cls._parse_metadata(mapping.get("metadata"), "metadata")
        source_count = cls._parse_int(mapping.get("source_count"), "source_count")

        entity = cls(
            entity_id=cls._require_text(mapping.get("entity_id"), "entity_id"),
            name=cls._require_text(mapping.get("name"), "name"),
            rita_type=cls._require_text(mapping.get("rita_type"), "rita_type"),
            aliases=aliases,
            metadata=metadata,
            source_ids=source_ids,
            source_count=source_count,
            extracted_at=cls._require_text(mapping.get("extracted_at"), "extracted_at"),
            extraction_run_id=cls._require_text(mapping.get("extraction_run_id"), "extraction_run_id"),
            raw_json=raw_json,
            ingestion_status=cls._require_text(mapping.get("ingestion_status"), "ingestion_status"),
        )
        if entity.source_count != len(entity.source_ids):
            raise RITAValidationError(
                f"source_count ({entity.source_count}) does not match source_ids length ({len(entity.source_ids)})"
            )
        return entity

    @staticmethod
    def _require_text(value: Any, field_name: str) -> str:
        if value is None:
            raise RITAValidationError(f"RITA row is missing required field: {field_name}")
        text = str(value).strip()
        if not text:
            raise RITAValidationError(f"RITA row has an empty required field: {field_name}")
        return text

    @staticmethod
    def _parse_int(value: Any, field_name: str) -> int:
        if value is None:
            raise RITAValidationError(f"RITA row is missing required field: {field_name}")
        if isinstance(value, bool):
            raise RITAValidationError(f"RITA field {field_name} must be an integer, not a boolean")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise RITAValidationError(f"RITA row has an empty required field: {field_name}")
            try:
                return int(text)
            except ValueError as exc:
                raise RITAValidationError(f"RITA field {field_name} must be an integer value") from exc
        raise RITAValidationError(f"RITA field {field_name} must be an integer value")

    @staticmethod
    def _parse_string_list(value: Any, field_name: str) -> List[str]:
        if value is None:
            raise RITAValidationError(f"RITA row is missing required field: {field_name}")

        if isinstance(value, list):
            result = [str(item).strip() for item in value if str(item).strip()]
            if field_name == "source_ids" and not result:
                raise RITAValidationError(f"RITA field {field_name} cannot be empty")
            return result

        if isinstance(value, tuple):
            result = [str(item).strip() for item in value if str(item).strip()]
            if field_name == "source_ids" and not result:
                raise RITAValidationError(f"RITA field {field_name} cannot be empty")
            return result

        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise RITAValidationError(f"RITA field {field_name} cannot be empty")
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                parsed = text

            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
            if isinstance(parsed, tuple):
                return [str(item).strip() for item in parsed if str(item).strip()]
            if isinstance(parsed, str):
                if field_name == "source_ids" and "," in parsed:
                    return [part.strip() for part in parsed.split(",") if part.strip()]
                return [parsed.strip()] if parsed.strip() else []

            if "," in text:
                return [part.strip() for part in text.split(",") if part.strip()]
            return [text]

        raise RITAValidationError(f"RITA field {field_name} must be a string or list of strings")

    @staticmethod
    def _parse_metadata(value: Any, field_name: str) -> Dict[str, Any]:
        if value is None:
            raise RITAValidationError(f"RITA row is missing required field: {field_name}")
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                raise RITAValidationError(f"RITA field {field_name} cannot be empty")
            try:
                parsed = json.loads(text)
            except (TypeError, ValueError):
                return {"value": text}
            if isinstance(parsed, dict):
                return parsed
            raise RITAValidationError(f"RITA field {field_name} must decode to a dictionary")
        raise RITAValidationError(f"RITA field {field_name} must be a dictionary or JSON string")


class RITAIntakeService:
    """Small wrapper that reads ENTITY_RAW rows and validates them into RITAEntity objects."""

    def __init__(
        self,
        reader: Optional[GoogleSheetsReader] = None,
        rows: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> None:
        self.reader = reader
        self._rows = list(rows) if rows is not None else None

    def fetch_rows(self) -> List[Dict[str, Any]]:
        """Return raw rows, either from an injected list or the configured Google reader."""
        if self._rows is not None:
            return [dict(row) for row in self._rows]
        if self.reader is None:
            self.reader = GoogleSheetsReader.from_env()
        return self.reader.fetch_entity_raw_rows()

    def get_entities(self) -> List[RITAEntity]:
        """Return all valid RITA entities available from the configured source."""
        return [RITAEntity.from_row(row) for row in self.fetch_rows()]

    def get_entity_by_id(self, entity_id: str) -> RITAEntity:
        """Return one entity by entity_id, or raise a not-found validation error."""
        target_id = str(entity_id).strip()
        if not target_id:
            raise RITAValidationError("entity_id is required")

        for row in self.fetch_rows():
            if str(row.get("entity_id", "")).strip() == target_id:
                return RITAEntity.from_row(row)

        raise RITAEntityNotFoundError(f"RITA entity with entity_id '{target_id}' was not found")
