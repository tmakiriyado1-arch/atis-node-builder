# ATIS Node Builder

ATIS Node Builder is a foundational web service that integrates with the ATIS knowledge architecture. It takes entities discovered by RITA (ATIS's research/entity discovery system), researches them using reliable internet sources, populates the canonical ATIS Google Sheets schema, identifies additional entities, generates graph-compatible backlinks, and produces CSV output for Obsidian import.

## Core Principle: Entity Identity ≠ Node Existence

An entity can exist in the ATIS ontology even if there is no Obsidian node for it yet. The system resolves textual variants to canonical entities, generates backlinks for missing nodes, and maintains a queue of discovered entities for future processing.

Example:
- `ZERA`
- `Zimbabwe Energy Regulatory Authority`
- `Zimbabwe Energy Regulatory Authority (ZERA)`
- `ZERA (Zimbabwe Energy Regulatory Authority)`

These all resolve to the **same canonical entity**, and backlinks are generated even if the node doesn't exist yet.

## Quick Start

### Prerequisites
- Python 3.11+
- PostgreSQL 14+
- Mistral API key

### Installation

```bash
git clone https://github.com/tmakiriyado1-arch/atis-node-builder.git
cd atis-node-builder
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and configure:

```bash
DATABASE_URL=postgresql://user:password@localhost/atis_node_builder
MISTRAL_API_KEY=your_mistral_key
LOG_LEVEL=INFO
```

### RITA snapshot sync

The backend consumes the committed entity snapshot at `data/rita_entities.json` for `GET /api/entities` so the Render runtime does not require live Google credentials. The GitHub Action at `.github/workflows/sync-rita-entities.yml` authenticates to Google using the repository's existing Workload Identity Federation setup, reads the configured RITA sheet, validates each row using the repository's `RITAEntity` model, and writes the deterministic JSON snapshot only when content changes.

If the repository is redeployed after the JSON snapshot changes, the updated entity list is available immediately. A redeploy is required only if the hosting platform does not automatically rebuild on repo changes.

### Running the Service

```bash
uvicorn app.main:app --reload
```

API documentation: http://localhost:8000/docs

## Development

### Project Structure

```
atis-node-builder/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application
│   ├── config.py               # Configuration management
│   ├── logging.py              # Logging setup
│   ├── models/                 # Pydantic models
│   │   ├── entity.py
│   │   ├── claim.py
│   │   ├── job.py
│   │   └── queue.py
│   ├── db/                     # Database
│   │   ├── __init__.py
│   │   ├── session.py
│   │   ├── models.py           # SQLAlchemy ORM models
│   │   └── migrations/         # Alembic migrations
│   ├── services/               # Business logic
│   │   ├── entity_resolution/
│   │   │   ├── normalizer.py
│   │   │   ├── resolver.py
│   │   │   └── registry.py
│   │   ├── research/
│   │   │   ├── search_provider.py
│   │   │   ├── llm_provider.py
│   │   │   └── research_engine.py
│   │   ├── backlink/
│   │   │   ├── extractor.py
│   │   │   └── generator.py
│   │   ├── schema/
│   │   │   └── registry.py
│   │   ├── node_builder.py
│   │   └── queue_manager.py
│   ├── api/
│   │   ├── routes/
│   │   │   ├── entities.py
│   │   │   ├── jobs.py
│   │   │   ├── queue.py
│   │   │   ├── schema.py
│   │   │   └── health.py
│   │   └── dependencies.py
│   └── utils/
│       ├── validators.py
│       └── csv_export.py
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_normalization.py
│   │   ├── test_entity_resolution.py
│   │   ├── test_backlink_generation.py
│   │   └── test_schema_compliance.py
│   └── integration/
│       └── test_full_pipeline.py
├── scripts/
│   ├── init_db.py
│   └── import_schema.py
├── docs/
│   ├── ENTITY_RESOLUTION.md
│   ├── SCHEMA.md
│   ├── RESEARCH.md
│   ├── BACKLINKING.md
│   ├── QUEUE.md
│   ├── API.md
│   └── DECISIONS.md
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── ARCHITECTURE.md
└── pyproject.toml
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app tests/

# Run specific test file
pytest tests/unit/test_entity_resolution.py -v
```

### Database Migrations

```bash
# Create migration
alembic revision --autogenerate -m "Migration message"

# Apply migrations
alembic upgrade head
```

## Key Components

### Entity Resolution
Resolves textual variants to canonical entities using deterministic normalization and optional fuzzy matching. See [ENTITY_RESOLUTION.md](./docs/ENTITY_RESOLUTION.md).

### Schema Registry
Machine-readable representation of the canonical ATIS Google Sheets schema. See [SCHEMA.md](./docs/SCHEMA.md).

### Research Engine
Searches internet sources and synthesizes evidence into structured claims. See [RESEARCH.md](./docs/RESEARCH.md).

### Backlink Engine
Extracts entities from prose and generates canonical backlinks. See [BACKLINKING.md](./docs/BACKLINKING.md).

### New Entity Queue
Maintains a deduplicated queue of discovered entities for recursive processing. See [QUEUE.md](./docs/QUEUE.md).

## API Endpoints

### Entities
- `POST /entities` — Create/register entity
- `GET /entities/{entity_id}` — Get canonical entity
- `POST /resolve` — Resolve entity identity

### Jobs
- `POST /build` — Build a node (async job)
- `GET /jobs/{job_id}` — Get job status/results
- `POST /research` — Research an entity

### Queue
- `GET /queue` — List new entity queue

### Schema
- `GET /schema` — Get schema registry

### Health
- `GET /health` — Health check

See [API.md](./docs/API.md) for detailed endpoint documentation.

## First MVP

The first working milestone processes a single RITA entity and produces:

1. Resolved canonical entity
2. Research results with evidence
3. Populated ATIS CSV row
4. Backlinked summary
5. Backlinked structured fields
6. Entity-resolution report
7. New-entity queue
8. Validation report
9. Full processing log

Integration tests use these four RITA examples:
- Zambian Civil Society Debt Alliance
- Neoliberal policies
- Extractive colonial style economy
- International debt

## Important Rules

- **Never hallucinate ATIS data** — Only populate fields with evidence or explicit unknowns
- **Never delete/rename ATIS fields** — Only enrich or supplement existing fields
- **Never treat node existence as proof** — Generate backlinks for missing nodes
- **Never create duplicate entities** — Use entity resolution, not string equality
- **Backlinks are graph data** — Every entity-bearing field must support them
- **Normalization first** — Use deterministic logic before LLM assistance
- **Evidence-backed claims** — Every value should retain its provenance

## Documentation

- [docs/NORA_ARCHITECTURE.md](./docs/NORA_ARCHITECTURE.md) — implemented NORA contract and current boundaries
- [ARCHITECTURE.md](./ARCHITECTURE.md) — System design and core principles
- [docs/ENTITY_RESOLUTION.md](./docs/ENTITY_RESOLUTION.md) — Entity identity and resolution
- [docs/SCHEMA.md](./docs/SCHEMA.md) — ATIS schema registry
- [docs/RESEARCH.md](./docs/RESEARCH.md) — Research engine and evidence
- [docs/BACKLINKING.md](./docs/BACKLINKING.md) — Backlink generation
- [docs/QUEUE.md](./docs/QUEUE.md) — New entity queue
- [docs/API.md](./docs/API.md) — API reference
- [docs/DECISIONS.md](./docs/DECISIONS.md) — Architectural decisions

## License

MIT

## Contact

Part of the ATIS infrastructure ecosystem.
