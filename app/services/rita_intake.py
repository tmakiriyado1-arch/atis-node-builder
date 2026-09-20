"""RITA ENTITY_RAW intake conversion and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from app.logging import logger
from app.services.google_sheets import GoogleSheetsReader


class RITAValidationError(ValueError):
    """Raised when a row cannot be converted into a valid RITA entity."""


class RITAEntityNotFoundError(RITAValidationError):
    """Raised when a requested entity_id is not present in the intake set."""


@dataclass(frozen=True)
class RITAEntity:
    """Typed representation of one validated RITA entity row."""

    entity_id: str = ""
    name: str = ""
    rita_type: str = ""
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

        aliases = cls._parse_string_list(mapping.get("aliases"))
        source_ids = cls._parse_string_list(mapping.get("source_ids"))
        metadata = cls._parse_metadata(mapping.get("metadata"))
        source_count = cls._parse_int(mapping.get("source_count"))

        entity = cls(
            entity_id=str(mapping.get("entity_id") or "").strip(),
            name=str(mapping.get("name") or "").strip(),
            rita_type=str(mapping.get("rita_type") or "").strip(),
            aliases=aliases,
            metadata=metadata,
            source_ids=source_ids,
            source_count=source_count,
            extracted_at=str(mapping.get("extracted_at") or "").strip(),
            extraction_run_id=str(mapping.get("extraction_run_id") or "").strip(),
            raw_json=raw_json,
            ingestion_status=str(mapping.get("ingestion_status") or "").strip(),
        )
        if entity.source_count != len(entity.source_ids):
            entity = dataclasses.replace(entity, source_count=len(entity.source_ids))
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
            return 0
        if isinstance(value, bool):
            raise RITAValidationError(f"RITA field {field_name} must be an integer, not a boolean")
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return 0
            try:
                return int(text)
            except ValueError as exc:
                raise RITAValidationError(f"RITA field {field_name} must be an integer value") from exc
        raise RITAValidationError(f"RITA field {field_name} must be an integer value")

    @staticmethod
    def _parse_string_list(value: Any, field_name: str) -> List[str]:
        if value is None:
            return []

        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if isinstance(value, tuple):
            return [str(item).strip() for item in value if str(item).strip()]

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
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
            return {}
        if isinstance(value, dict):
            return dict(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
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

    DEFAULT_JSON_PATH = Path(__file__).resolve().parents[2] / "data" / "rita_entities.json"

    def __init__(
        self,
        reader: Optional[GoogleSheetsReader] = None,
        rows: Optional[Sequence[Mapping[str, Any]]] = None,
        json_path: Optional[str | Path] = None,
    ) -> None:
        self.reader = reader
        self._rows = list(rows) if rows is not None else None
        self.json_path = Path(json_path) if json_path is not None else self.DEFAULT_JSON_PATH

    def get_snapshot_diagnostics(self) -> Dict[str, Any]:
        """Return a safe diagnostic summary for the committed RITA snapshot."""
        snapshot_path = Path(self.json_path).expanduser()
        exists = snapshot_path.exists()
        rows: List[Dict[str, Any]] = []
        if exists:
            try:
                rows = self._read_rows_from_snapshot(snapshot_path)
            except Exception:
                rows = []
        return {
            "snapshot_path": str(snapshot_path),
            "snapshot_exists": exists,
            "entity_count": len(rows),
        }

    def fetch_rows(self) -> List[Dict[str, Any]]:
        """Return rows from an injected list, the committed snapshot, or the configured Google reader."""
        if self._rows is not None:
            return [dict(row) for row in self._rows]

        snapshot_path = Path(self.json_path).expanduser()
        if snapshot_path.exists():
            rows = self._read_rows_from_snapshot(snapshot_path)
            logger.info(
                "RITA snapshot diagnostics: path=%s exists=%s entity_count=%s",
                snapshot_path,
                True,
                len(rows),
            )
            return rows

        logger.warning("RITA snapshot missing at %s; falling back to Google Sheets", snapshot_path)
        if self.reader is None:
            try:
                self.reader = GoogleSheetsReader.from_env()
            except Exception:
                logger.exception("Failed to configure Google Sheets reader for RITA fallback")
                return []
        try:
            rows = self.reader.fetch_entity_raw_rows()
            logger.info("RITA Google fallback row_count=%s", len(rows))
            return rows
        except Exception:
            logger.exception("Google Sheets RITA fallback failed")
            return []

    @staticmethod
    def _read_rows_from_snapshot(path: str | Path) -> List[Dict[str, Any]]:
        target = Path(path).expanduser()
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except json.JSONDecodeError as exc:
            raise ValueError(f"RITA snapshot at {target} is not valid JSON") from exc

        if payload is None:
            return []
        if isinstance(payload, dict):
            payload = payload.get("entities", [])
        if not isinstance(payload, list):
            raise ValueError("RITA snapshot must be a JSON array of entity objects")

        rows: List[Dict[str, Any]] = []
        for item in payload:
            if not isinstance(item, dict):
                raise RITAValidationError("Every item in the RITA snapshot must be an object")
            cleaned = dict(item)
            if "raw_json" not in cleaned:
                cleaned["raw_json"] = dict(cleaned)
            rows.append(cleaned)
        return rows

    @staticmethod
    def write_snapshot(rows: Sequence[Mapping[str, Any]], path: str | Path) -> Path:
        """Write a deterministic, validated RITA snapshot to disk."""
        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)

        serialized_rows = []
        for row in rows:
            mapping = dict(row)
            entity = RITAEntity.from_row(mapping)
            serialized_rows.append(
                {
                    "entity_id": entity.entity_id,
                    "name": entity.name,
                    "rita_type": entity.rita_type,
                    "aliases": entity.aliases,
                    "metadata": entity.metadata,
                    "source_ids": entity.source_ids,
                    "source_count": entity.source_count,
                    "extracted_at": entity.extracted_at,
                    "extraction_run_id": entity.extraction_run_id,
                    "ingestion_status": entity.ingestion_status,
                }
            )

        payload = sorted(serialized_rows, key=lambda item: str(item.get("entity_id", "")))
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

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
