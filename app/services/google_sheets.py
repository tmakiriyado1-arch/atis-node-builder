"""Read-only Google Sheets access for private ENTITY_RAW sources."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import config


class GoogleSheetsError(RuntimeError):
    """Raised when Google Sheets access cannot be configured or used."""


class GoogleSheetsReader:
    """Thin read-only adapter for the private ENTITY_RAW spreadsheet."""

    READ_ONLY_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

    def __init__(
        self,
        spreadsheet_id: str,
        worksheet_name: str = "ENTITY_RAW",
        credentials_path: Optional[str] = None,
        impersonate_service_account: Optional[str] = None,
    ) -> None:
        cleaned_spreadsheet_id = (spreadsheet_id or "").strip()
        if not cleaned_spreadsheet_id:
            raise ValueError("GOOGLE_SHEETS_SPREADSHEET_ID is required")

        self.spreadsheet_id = cleaned_spreadsheet_id
        self.worksheet_name = (worksheet_name or "ENTITY_RAW").strip() or "ENTITY_RAW"
        self.credentials_path = (credentials_path or config.GOOGLE_APPLICATION_CREDENTIALS or "").strip()
        self.impersonate_service_account = (
            impersonate_service_account
            or config.GOOGLE_IMPERSONATE_SERVICE_ACCOUNT
            or config.GOOGLE_SERVICE_ACCOUNT_EMAIL
            or ""
        ).strip()

    @classmethod
    def from_env(cls) -> "GoogleSheetsReader":
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", config.GOOGLE_SHEETS_SPREADSHEET_ID)
        worksheet_name = os.getenv("GOOGLE_SHEETS_WORKSHEET_NAME", config.GOOGLE_SHEETS_WORKSHEET_NAME)
        credentials_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", config.GOOGLE_APPLICATION_CREDENTIALS)
        impersonate_service_account = os.getenv(
            "GOOGLE_IMPERSONATE_SERVICE_ACCOUNT",
            config.GOOGLE_IMPERSONATE_SERVICE_ACCOUNT or config.GOOGLE_SERVICE_ACCOUNT_EMAIL,
        )
        return cls(
            spreadsheet_id=spreadsheet_id,
            worksheet_name=worksheet_name,
            credentials_path=credentials_path,
            impersonate_service_account=impersonate_service_account,
        )

    @staticmethod
    def _coerce_service_account_info(value: Optional[Any]) -> Optional[Dict[str, Any]]:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            payload = value.strip()
            if not payload:
                return None
            if payload.startswith("{"):
                return json.loads(payload)
            if payload.startswith("file://"):
                return GoogleSheetsReader._load_service_account_info_from_file(payload[7:])
            if os.path.exists(payload):
                return GoogleSheetsReader._load_service_account_info_from_file(payload)
        raise ValueError("Invalid service account JSON or credentials path")

    @staticmethod
    def _load_service_account_info_from_file(path: str) -> Dict[str, Any]:
        resolved_path = Path(path).expanduser()
        if not resolved_path.exists():
            raise FileNotFoundError(f"Google credentials file not found: {resolved_path}")
        with resolved_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _build_credentials(self):
        try:
            import google.auth
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise GoogleSheetsError(
                "google-auth is required to authenticate to Google Sheets via ADC / WIF."
            ) from exc

        try:
            credentials, _ = google.auth.default(scopes=self.READ_ONLY_SCOPES)
        except Exception as exc:  # pragma: no cover - network or env dependent
            raise GoogleSheetsError(
                "Google ADC / Workload Identity Federation credentials are required for private-sheet access. "
                "Use a supported federated credential or a local ADC config; do not use a static service-account private key."
            ) from exc

        if self.impersonate_service_account:
            try:
                from google.auth import impersonated_credentials
            except ImportError as exc:  # pragma: no cover - dependency guard
                raise GoogleSheetsError(
                    "google-auth impersonation support is required for the NORA service account flow."
                ) from exc

            return impersonated_credentials.Credentials(
                source_credentials=credentials,
                target_principal=self.impersonate_service_account,
                target_scopes=self.READ_ONLY_SCOPES,
                lifetime=3600,
            )

        return credentials

    def fetch_rows(self, range_name: Optional[str] = None) -> List[List[str]]:
        """Return the raw worksheet rows, with no transformations applied."""
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise GoogleSheetsError(
                "google-api-python-client is required to access private Google Sheets."
            ) from exc

        range_target = (range_name or self.worksheet_name).strip() or self.worksheet_name
        service = build(
            "sheets",
            "v4",
            credentials=self._build_credentials(),
            cache_discovery=False,
        )
        response = service.spreadsheets().values().get(
            spreadsheetId=self.spreadsheet_id,
            range=range_target,
            valueRenderOption="FORMATTED_VALUE",
            majorDimension="ROWS",
        ).execute()
        return response.get("values", [])

    def fetch_entity_raw_rows(self) -> List[Dict[str, Any]]:
        rows = self.fetch_rows(self.worksheet_name)
        return self._normalize_rows(rows)

    @staticmethod
    def _normalize_rows(rows: List[List[str]]) -> List[Dict[str, Any]]:
        if not rows:
            return []

        header_row = rows[0]
        normalized: List[Dict[str, Any]] = []

        for row in rows[1:]:
            values = row[: len(header_row)] + [""] * max(0, len(header_row) - len(row))
            mapping = {str(header): str(value) for header, value in zip(header_row, values)}
            record = dict(mapping)
            record["raw_json"] = dict(mapping)
            normalized.append(record)

        return normalized


def read_entity_raw_rows() -> List[Dict[str, Any]]:
    """Return the canonical ENTITY_RAW sheet rows for downstream NORA intake."""
    return GoogleSheetsReader.from_env().fetch_entity_raw_rows()
