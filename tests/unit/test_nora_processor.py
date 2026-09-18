from pathlib import Path

from app.processor import NORAProcessor


def test_process_markdown_file_creates_node_and_relationship(registry, resolver):
    zera = registry.create_entity(
        canonical_name="Zimbabwe Energy Regulatory Authority",
        entity_type="government_entity",
        acronyms=["ZERA"],
    )
    registry.create_entity("International Debt", entity_type="concept")

    source_path = Path("tests/fixtures/nora/known_entity_with_reference.md")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.write_text(
        """---
title: Zimbabwe Energy Regulatory Authority
entity: Zimbabwe Energy Regulatory Authority
---

# Zimbabwe Energy Regulatory Authority

This authority works on issues related to [[International Debt]].

See also [International Debt](https://example.test/international-debt).
""",
        encoding="utf-8",
    )

    processor = NORAProcessor(registry=registry, resolver=resolver)
    result = processor.process_file(source_path)

    assert result["status"] == "ok"
    assert result["node_id"].startswith("NODE-")
    assert result["entity_id"] == zera.entity_id
    assert result["canonical_name"] == zera.canonical_name
    assert result["provenance"][0]["source_id"] == str(source_path)
    assert len(result["relationships"]) >= 1


def test_process_directory_records_unresolved_and_idempotent_updates(registry, resolver, tmp_path):
    registry.create_entity("Zimbabwe Energy Regulatory Authority", entity_type="government_entity", acronyms=["ZERA"])
    registry.create_entity("International Debt", entity_type="concept")

    known_path = tmp_path / "known.md"
    known_path.write_text(
        """---
title: Zimbabwe Energy Regulatory Authority
---

# Zimbabwe Energy Regulatory Authority

This document references [[International Debt]].
""",
        encoding="utf-8",
    )

    unknown_path = tmp_path / "unknown.md"
    unknown_path.write_text(
        """---
title: New Agency of the Future
---

# New Agency of the Future

This source mentions a candidate that has not been registered yet.
""",
        encoding="utf-8",
    )

    processor = NORAProcessor(registry=registry, resolver=resolver)
    first = processor.process_directory(tmp_path)
    second = processor.process_directory(tmp_path)

    assert first["processed"] >= 1
    assert first["failed"] == 0
    assert first["unresolved"] >= 1
    assert second["created"] == 0
    assert second["updated"] >= 0
    assert second["unchanged"] >= 1
