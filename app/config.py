"""
ATIS Node Builder Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# Database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://localhost/atis_node_builder"
)

# LLM Provider
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Research
SEARCH_TIMEOUT = int(os.getenv("SEARCH_TIMEOUT", "30"))
MAX_SOURCES_PER_QUERY = int(os.getenv("MAX_SOURCES_PER_QUERY", "10"))

# Google Sheets (read-only ENTITY_RAW intake)
GOOGLE_AUTH_MODE = os.getenv("GOOGLE_AUTH_MODE", "WORKLOAD_IDENTITY_FEDERATION").upper()
GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID", "")
GOOGLE_WORKLOAD_IDENTITY_PROVIDER = os.getenv("GOOGLE_WORKLOAD_IDENTITY_PROVIDER", "")
GOOGLE_IMPERSONATE_SERVICE_ACCOUNT = os.getenv("GOOGLE_IMPERSONATE_SERVICE_ACCOUNT", "")
GOOGLE_SERVICE_ACCOUNT_EMAIL = os.getenv("GOOGLE_SERVICE_ACCOUNT_EMAIL", "")
GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
GOOGLE_SHEETS_WORKSHEET_NAME = os.getenv("GOOGLE_SHEETS_WORKSHEET_NAME", "ENTITY_RAW")
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
GOOGLE_SERVICE_ACCOUNT_INFO = os.getenv("GOOGLE_SERVICE_ACCOUNT_INFO", "")

# Entity Resolution
FUZZY_MATCH_THRESHOLD = float(os.getenv("FUZZY_MATCH_THRESHOLD", "0.85"))

# Job Processing
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "5"))
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "3600"))

# API
API_TITLE = "ATIS Node Builder API"
API_VERSION = "0.1.0"
API_DESCRIPTION = "Infrastructure service for entity research and canonical schema population"
