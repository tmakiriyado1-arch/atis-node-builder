import json
from unittest.mock import MagicMock

import pytest

from app.services.google_sheets import GoogleSheetsReader
from app.services.rita_intake import (
    RITAEntity,
    RITAEntityNotFoundError,
    RITAIntakeService,
    RITAValidationError,
)


VALID_ROW = {
    "entity_id": "RITA-001",
    "name": "Acme Logistics",
    "rita_type": "organization",
    "aliases": '["Acme", "Acme Logistics"]',
    "metadata": '{"country": "US", "status": "active"}',
    "source_ids": '["src-001", "src-002"]',
    "source_count": "2",
    "extracted_at": "2026-01-15T12:00:00Z",
    "extraction_run_id": "run-2026-01-15",
    "raw_json": {
        "entity_id": "RITA-001",
        "name": "Acme Logistics",
        "rita_type": "organization",
        "aliases": '["Acme", "Acme Logistics"]',
        "metadata": '{"country": "US", "status": "active"}',
        "source_ids": '["src-001", "src-002"]',
        "source_count": "2",
        "extracted_at": "2026-01-15T12:00:00Z",
        "extraction_run_id": "run-2026-01-15",
        "ingestion_status": "PENDING",
    },
    "ingestion_status": "PENDING",
}


def test_valid_rita_row_converts_correctly():
    entity = RITAEntity.from_row(VALID_ROW)

    assert entity.entity_id == "RITA-001"
    assert entity.name == "Acme Logistics"
    assert entity.rita_type == "organization"
    assert entity.aliases == ["Acme", "Acme Logistics"]
    assert entity.metadata == {"country": "US", "status": "active"}
    assert entity.source_ids == ["src-001", "src-002"]
    assert entity.source_count == 2
    assert entity.ingestion_status == "PENDING"


def test_entity_id_missing_fails():
    row = {**VALID_ROW, "entity_id": ""}

    with pytest.raises(RITAValidationError, match="entity_id"):
        RITAEntity.from_row(row)


def test_name_missing_fails():
    row = {**VALID_ROW, "name": ""}

    with pytest.raises(RITAValidationError, match="name"):
        RITAEntity.from_row(row)


def test_raw_json_is_preserved():
    entity = RITAEntity.from_row(VALID_ROW)

    assert entity.raw_json == VALID_ROW["raw_json"]
    assert entity.raw_json["entity_id"] == "RITA-001"


def test_entity_lookup_returns_requested_entity():
    service = RITAIntakeService(rows=[VALID_ROW, {**VALID_ROW, "entity_id": "RITA-002", "name": "Beta Labs"}])

    entity = service.get_entity_by_id("RITA-002")

    assert entity.entity_id == "RITA-002"
    assert entity.name == "Beta Labs"


def test_unknown_entity_id_raises_clear_not_found_error():
    service = RITAIntakeService(rows=[VALID_ROW])

    with pytest.raises(RITAEntityNotFoundError, match="RITA-404"):
        service.get_entity_by_id("RITA-404")


def test_rita_intake_model_is_testable_without_google():
    mock_reader = MagicMock(spec=GoogleSheetsReader)
    service = RITAIntakeService(reader=mock_reader, rows=[VALID_ROW])

    entity = service.get_entity_by_id("RITA-001")

    assert entity.entity_id == "RITA-001"
    mock_reader.fetch_entity_raw_rows.assert_not_called()
