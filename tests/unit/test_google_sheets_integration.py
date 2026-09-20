import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.google_sheets import GoogleSheetsError, GoogleSheetsReader


def test_reader_requires_spreadsheet_id():
    with pytest.raises(ValueError, match="GOOGLE_SHEETS_SPREADSHEET_ID"):
        GoogleSheetsReader(spreadsheet_id="", worksheet_name="ENTITY_RAW")


def test_rows_are_normalized_and_raw_json_is_preserved():
    reader = GoogleSheetsReader(spreadsheet_id="sheet-123", worksheet_name="ENTITY_RAW")

    raw_rows = [
        ["entity_name", "entity_type", "notes"],
        ["Acme Logistics", "carrier", "primary account"],
    ]

    normalized = reader._normalize_rows(raw_rows)

    assert normalized == [
        {
            "entity_name": "Acme Logistics",
            "entity_type": "carrier",
            "notes": "primary account",
            "raw_json": {
                "entity_name": "Acme Logistics",
                "entity_type": "carrier",
                "notes": "primary account",
            },
        }
    ]


def test_rows_are_normalized_from_human_readable_sheet_headers():
    reader = GoogleSheetsReader(spreadsheet_id="sheet-123", worksheet_name="ENTITY_RAW")

    raw_rows = [
        [
            "Entity ID",
            "Name",
            "RITA Type",
            "Aliases",
            "Metadata",
            "Source IDs",
            "Source Count",
            "Extracted At",
            "Extraction Run ID",
            "Ingestion Status",
        ],
        [
            "RITA-001",
            "Acme Logistics",
            "organization",
            '["Acme", "Acme Logistics"]',
            '{"country": "US"}',
            '["src-001", "src-002"]',
            "2",
            "2026-01-15T12:00:00Z",
            "run-2026-01-15",
            "PENDING",
        ],
    ]

    normalized = reader._normalize_rows(raw_rows)

    assert normalized[0]["entity_id"] == "RITA-001"
    assert normalized[0]["name"] == "Acme Logistics"
    assert normalized[0]["rita_type"] == "organization"
    assert normalized[0]["source_count"] == "2"
    assert normalized[0]["raw_json"]["entity_id"] == "RITA-001"


@patch.dict(
    "os.environ",
    {
        "GOOGLE_SHEETS_SPREADSHEET_ID": "sheet-123",
        "GOOGLE_SHEETS_WORKSHEET_NAME": "ENTITY_RAW",
        "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT": "nora-reader@example.iam.gserviceaccount.com",
        "GOOGLE_AUTH_MODE": "WORKLOAD_IDENTITY_FEDERATION",
    },
    clear=False,
)
def test_reader_builds_from_environment_for_wif():
    reader = GoogleSheetsReader.from_env()

    assert reader.spreadsheet_id == "sheet-123"
    assert reader.worksheet_name == "ENTITY_RAW"
    assert reader.impersonate_service_account == "nora-reader@example.iam.gserviceaccount.com"


@patch("google.auth.default")
@patch("google.auth.impersonated_credentials.Credentials")
@patch("googleapiclient.discovery.build")
def test_wif_credentials_are_used_to_build_sheets_client(
    mock_build,
    mock_impersonated_credentials,
    mock_default,
):
    mock_source_creds = object()
    mock_default.return_value = (mock_source_creds, object())
    mock_impersonated = MagicMock()
    mock_impersonated_credentials.return_value = mock_impersonated

    mock_service = MagicMock()
    mock_service.spreadsheets().values().get().execute.return_value = {"values": [["entity_id", "name"], ["1", "Acme"]]}
    mock_build.return_value = mock_service

    reader = GoogleSheetsReader(
        spreadsheet_id="sheet-123",
        worksheet_name="ENTITY_RAW",
        impersonate_service_account="nora-reader@example.iam.gserviceaccount.com",
    )

    rows = reader.fetch_rows()

    assert rows == [["entity_id", "name"], ["1", "Acme"]]
    mock_default.assert_called_once_with(scopes=reader.READ_ONLY_SCOPES)
    mock_impersonated_credentials.assert_called_once_with(
        source_credentials=mock_source_creds,
        target_principal="nora-reader@example.iam.gserviceaccount.com",
        target_scopes=reader.READ_ONLY_SCOPES,
        lifetime=3600,
    )
    mock_build.assert_called_once()


@patch("google.auth.default")
def test_authentication_failures_are_surfaces_cleanly(mock_default):
    mock_default.side_effect = RuntimeError("no credentials available")

    reader = GoogleSheetsReader(spreadsheet_id="sheet-123", worksheet_name="ENTITY_RAW")

    with pytest.raises(GoogleSheetsError, match="ADC / Workload Identity Federation|static service-account private key"):
        reader.fetch_rows()


@patch("google.auth.default")
def test_no_private_key_is_required_for_wif(mock_default):
    mock_source_creds = object()
    mock_default.return_value = (mock_source_creds, object())

    reader = GoogleSheetsReader(
        spreadsheet_id="sheet-123",
        worksheet_name="ENTITY_RAW",
        impersonate_service_account="nora-reader@example.iam.gserviceaccount.com",
    )

    credentials = reader._build_credentials()

    assert credentials is not None
    mock_default.assert_called_once_with(scopes=reader.READ_ONLY_SCOPES)


@patch("google.auth.default")
def test_no_credentials_are_logged(mock_default, capsys):
    mock_default.side_effect = RuntimeError("missing ADC")

    reader = GoogleSheetsReader(spreadsheet_id="sheet-123", worksheet_name="ENTITY_RAW")

    with pytest.raises(GoogleSheetsError):
        reader.fetch_rows()

    captured = capsys.readouterr()
    assert "missing ADC" not in captured.out
    assert "missing ADC" not in captured.err
