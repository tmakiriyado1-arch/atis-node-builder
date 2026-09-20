#!/usr/bin/env python3
"""Sync the committed RITA snapshot from the private Google Sheet."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.google_sheets import GoogleSheetsReader
from app.services.rita_intake import RITAEntity, RITAIntakeService

OUTPUT_PATH = ROOT / "data" / "rita_entities.json"


def _serialize_row(row: dict) -> dict:
    entity = RITAEntity.from_row(row)
    return {
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


def main() -> int:
    spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID") or os.getenv("GOOGLE_SHEET_ID")
    worksheet_name = os.getenv("GOOGLE_SHEETS_WORKSHEET_NAME", "ENTITY_RAW")
    if not spreadsheet_id:
        raise RuntimeError("GOOGLE_SHEETS_SPREADSHEET_ID is required")

    reader = GoogleSheetsReader(
        spreadsheet_id=spreadsheet_id,
        worksheet_name=worksheet_name,
    )
    rows = reader.fetch_entity_raw_rows()
    payload = [_serialize_row(row) for row in rows]
    RITAIntakeService.write_snapshot(payload, OUTPUT_PATH)
    print(f"Wrote {len(payload)} RITA entities to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
