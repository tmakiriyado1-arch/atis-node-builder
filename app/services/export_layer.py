"""Deterministic export layer for canonical import rows."""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence

from app.models import CanonicalNodeRow


EXPORT_COLUMNS = [
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


@dataclass
class ExportPackage:
    """Stable collection of canonical rows in serializable form."""

    rows: List[CanonicalNodeRow] = field(default_factory=list)

    def validate(self) -> None:
        if self.rows is None:
            raise ValueError("rows cannot be None")
        for row in self.rows:
            if not isinstance(row, CanonicalNodeRow):
                raise ValueError("all rows must be CanonicalNodeRow instances")
            if not row.uid or not row.uid.strip():
                raise ValueError("row uid is required")
            if not row.entity or not row.entity.strip():
                raise ValueError("row entity is required")
            if not row.summary or not row.summary.strip():
                raise ValueError("row summary is required")
            if not row.sources:
                raise ValueError("row sources are required")

    def to_dicts(self) -> List[Dict[str, Any]]:
        self.validate()
        return [self._row_to_dict(row) for row in self.rows]

    def to_json(self) -> str:
        return json.dumps(self.to_dicts(), ensure_ascii=False, indent=2)

    def to_csv(self) -> str:
        self.validate()
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(EXPORT_COLUMNS)
        for row in self.rows:
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

    @staticmethod
    def _row_to_dict(row: CanonicalNodeRow) -> Dict[str, Any]:
        return {
            "uid": row.uid,
            "entity": row.entity,
            "aliases": list(row.aliases),
            "entity_type": row.entity_type,
            "subtype": row.subtype,
            "country": row.country,
            "sector": row.sector,
            "status": row.status,
            "summary": row.summary,
            "relationships": list(row.relationships),
            "associations": list(row.associations),
            "sources": list(row.sources),
        }


def export_rows(rows: Sequence[CanonicalNodeRow] | Iterable[CanonicalNodeRow]) -> ExportPackage:
    if rows is None:
        raise ValueError("rows cannot be None")
    normalized = list(rows)
    if not normalized:
        return ExportPackage(rows=[])
    return ExportPackage(rows=normalized)
