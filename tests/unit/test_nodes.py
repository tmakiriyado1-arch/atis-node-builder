"""Tests for validated node construction and explicit relationships."""
import pytest

from app.models import CanonicalNodeRow, ImportBundle, NodeDraft, NodeRelationship, SourceProvenance
from app.services.canonical_row_builder import CanonicalNodeRowBuilder
from app.services.export_layer import ExportPackage, export_rows
from app.services.node_builder import NodeBuildError, NodeBuilder
from app.services.node_draft_builder import NodeDraftBuilder
from app.services.node_store import NodeStore, NodeStoreError
from app.services.research_engine import ResearchClaim


def test_build_node_requires_resolved_entity(registry, resolver, zera_entity):
    builder = NodeBuilder(resolver)
    node = builder.build(
        node_id="NODE-ZERA",
        entity_text=" zera ",
        fields={"summary": "Source-backed summary"},
        source_id="source-1",
        source_type="trusted_document",
    )

    assert node.entity_id == zera_entity.entity_id
    assert node.canonical_name == zera_entity.canonical_name
    assert node.provenance[0].source_id == "source-1"
    assert node.fields == {"summary": "Source-backed summary"}


def test_build_node_rejects_unknown_entity(resolver):
    with pytest.raises(NodeBuildError, match="could not be resolved"):
        NodeBuilder(resolver).build(
            node_id="NODE-UNKNOWN",
            entity_text="Unknown entity",
            fields={},
            source_id="source-1",
        )


def test_relationship_is_explicit_deterministic_and_deduplicated(registry, resolver):
    source_entity = registry.create_entity("Source Entity")
    target_entity = registry.create_entity("Target Entity")
    node = NodeBuilder(resolver).build(
        node_id="NODE-SOURCE",
        entity_text=source_entity.canonical_name,
        fields={},
        source_id="source-1",
    )
    store = NodeStore(registry)
    store.save(node)
    relationship = NodeRelationship(
        source_node_id=node.node_id,
        target_entity_id=target_entity.entity_id,
        relationship_type="explicitly_related",
        provenance=[SourceProvenance(source_id="source-2")],
    )

    first = store.add_relationship(relationship)
    second = store.add_relationship(relationship)

    assert first.relationship_id == second.relationship_id
    assert len(store.list_relationships(node.node_id)) == 1


def test_relationship_rejects_unknown_target_and_self_link(registry, resolver):
    entity = registry.create_entity("Source Entity")
    node = NodeBuilder(resolver).build(
        node_id="NODE-SOURCE",
        entity_text=entity.canonical_name,
        fields={},
        source_id="source-1",
    )
    store = NodeStore(registry)
    store.save(node)

    for target_entity_id in ("ENTITY-999999", entity.entity_id):
        with pytest.raises(NodeStoreError):
            store.add_relationship(
                NodeRelationship(
                    source_node_id=node.node_id,
                    target_entity_id=target_entity_id,
                    relationship_type="explicitly_related",
                    provenance=[SourceProvenance(source_id="source-2")],
                )
            )


def test_research_claims_build_a_deterministic_node_draft():
    claims = [
        ResearchClaim(
            claim="Zimbabwe Energy Regulatory Authority regulates electricity licensing.",
            field_name="relationship",
            source_url="https://example.gov.zw/licensing",
            source_title="ZERA Licensing Overview",
            evidence_passage="The authority regulates electricity licensing.",
            confidence=0.9,
        )
    ]

    draft = NodeDraftBuilder().build(claims)

    assert isinstance(draft, NodeDraft)
    assert draft.title == "Zimbabwe Energy Regulatory Authority"
    assert "regulates → electricity licensing" in draft.body
    assert draft.frontmatter["entity"] == "Zimbabwe Energy Regulatory Authority"
    assert draft.frontmatter["sources"] == ["https://example.gov.zw/licensing"]
    assert draft.source_claims[0].source_url == "https://example.gov.zw/licensing"


def test_node_draft_preserves_provenance_and_rejects_hallucinated_fields():
    claims = [
        ResearchClaim(
            claim="Zimbabwe Energy Regulatory Authority manages licensing administration.",
            field_name="relationship",
            source_url="https://example.gov.zw/licensing-admin",
            source_title="Licensing Administration",
            evidence_passage="The authority manages licensing administration.",
            confidence=0.8,
        )
    ]

    draft = NodeDraftBuilder().build(claims)

    assert draft.frontmatter["sources"] == ["https://example.gov.zw/licensing-admin"]
    assert "industry" not in draft.frontmatter
    assert "employees" not in draft.frontmatter
    assert "founding_year" not in draft.frontmatter


def test_node_draft_handles_empty_and_missing_metadata_without_crashing():
    empty = NodeDraftBuilder().build([])
    assert empty.title == ""
    assert empty.body == ""
    assert empty.frontmatter == {}

    partial = NodeDraftBuilder().build(
        [
            ResearchClaim(
                claim="Zimbabwe Energy Regulatory Authority regulates licensing.",
                field_name="relationship",
                source_url="https://example.gov.zw/licensing",
                source_title=None,
                evidence_passage="",
                confidence=0.2,
            )
        ]
    )

    assert partial.title == "Zimbabwe Energy Regulatory Authority"
    assert partial.frontmatter["sources"] == ["https://example.gov.zw/licensing"]


def test_node_draft_is_deterministic_and_combines_multiple_claims():
    claims = [
        ResearchClaim(
            claim="Zimbabwe Energy Regulatory Authority regulates electricity licensing.",
            field_name="relationship",
            source_url="https://example.gov.zw/licensing",
            source_title="Licensing",
            evidence_passage="Energy licensing.",
            confidence=0.9,
        ),
        ResearchClaim(
            claim="Zimbabwe Energy Regulatory Authority oversees energy compliance.",
            field_name="relationship",
            source_url="https://example.gov.zw/compliance",
            source_title="Compliance",
            evidence_passage="Energy compliance.",
            confidence=0.8,
        ),
    ]

    first = NodeDraftBuilder().build(claims)
    second = NodeDraftBuilder().build(claims)

    assert first.render_markdown() == second.render_markdown()
    assert first.body.count("- ") >= 2
    assert "regulates → electricity licensing" in first.body
    assert "oversees → energy compliance" in first.body


def test_invalid_claims_are_safely_rejected():
    invalid = [
        ResearchClaim(
            claim="",
            field_name="",
            source_url="",
            source_title=None,
            evidence_passage="",
            confidence=0.0,
        )
    ]

    draft = NodeDraftBuilder().build(invalid)

    assert draft.title == ""
    assert draft.body == ""
    assert draft.frontmatter == {}
    assert draft.source_claims == []


def test_node_draft_routes_summary_relationships_and_metadata_from_claims(registry, resolver):
    claims = [
        ResearchClaim(
            subject="ZERA",
            predicate="regulates",
            object="Electricity",
            claim_text="ZERA regulates Electricity.",
            evidence_urls=["https://example.gov.zw/licensing"],
            claim="ZERA regulates Electricity.",
            source_url="https://example.gov.zw/licensing",
        ),
        ResearchClaim(
            subject="ZERA",
            predicate="is_a",
            object="government agency",
            claim_text="ZERA is a government agency.",
            evidence_urls=["https://example.gov.zw/overview"],
            claim="ZERA is a government agency.",
            source_url="https://example.gov.zw/overview",
        ),
        ResearchClaim(
            subject="ZERA",
            predicate="connected_to",
            object="Energy Security",
            claim_text="ZERA is connected to energy security.",
            evidence_urls=["https://example.gov.zw/related"],
            claim="ZERA is connected to energy security.",
            source_url="https://example.gov.zw/related",
        ),
    ]

    draft = NodeDraftBuilder(registry=registry, resolver=resolver).build(claims)

    assert draft.frontmatter["entity"] == "ZERA"
    assert "regulates::[[Electricity]]" in draft.frontmatter["relationships"]
    assert "connected_to::[[Energy Security]]" in draft.frontmatter["associations"]
    assert draft.frontmatter["entity_type"] == "government agency"
    assert "[[ZERA]]" in draft.body or "ZERA" in draft.body
    assert len(draft.source_claims) == 3


def test_node_draft_rejects_ambiguous_entity_targets_without_wikilink(registry, resolver):
    registry.create_entity("Zimbabwe Energy Regulatory Authority", acronyms=["ZERA"])
    registry.create_entity("ZERA Holdings", acronyms=["ZH"])
    registry.add_alias_to_entity(registry.list_all()[1].entity_id, "ZERA", "zera", "source")

    claims = [
        ResearchClaim(
            subject="ZERA",
            predicate="regulates",
            object="ZERA",
            claim_text="ZERA regulates ZERA.",
            evidence_urls=["https://example.gov.zw/ambiguous"],
            claim="ZERA regulates ZERA.",
            source_url="https://example.gov.zw/ambiguous",
        )
    ]

    draft = NodeDraftBuilder(registry=registry, resolver=resolver).build(claims)

    assert draft.frontmatter["entity"] == "ZERA"
    assert all("[[ZERA]]" not in item for item in draft.frontmatter.get("relationships", []))


def test_canonical_row_builds_from_node_draft():
    draft = NodeDraft(
        title="Zimbabwe Energy Regulatory Authority",
        frontmatter={
            "entity": "Zimbabwe Energy Regulatory Authority",
            "sources": ["https://example.gov.zw/licensing"],
        },
        body="## Relationships\n- regulates → electricity licensing",
        source_claims=[
            ResearchClaim(
                claim="Zimbabwe Energy Regulatory Authority regulates electricity licensing.",
                field_name="relationship",
                source_url="https://example.gov.zw/licensing",
                source_title="ZERA Licensing Overview",
                evidence_passage="The authority regulates electricity licensing.",
                confidence=0.9,
            )
        ],
    )

    row = CanonicalNodeRowBuilder().build(draft)

    assert isinstance(row, CanonicalNodeRow)
    assert row.entity == "Zimbabwe Energy Regulatory Authority"
    assert row.uid == "zimbabwe-energy-regulatory-authority"
    assert row.summary.startswith("[[Zimbabwe Energy Regulatory Authority]]")
    # PHASE 13: Do NOT create wikilinks to arbitrary text like "electricity licensing"
    # The summary should contain the factual statement without creating invalid backlinks
    assert "regulates" in row.summary.lower()
    assert "electricity licensing" in row.summary.lower()
    assert "regulates::[[Electricity]]" in row.relationships
    assert row.sources == ["https://example.gov.zw/licensing"]


def test_canonical_row_is_deterministic_and_safe_for_csv():
    draft = NodeDraft(
        title="Zimbabwe Energy Regulatory Authority",
        frontmatter={"entity": "Zimbabwe Energy Regulatory Authority", "sources": ["https://example.gov.zw/licensing", "https://example.gov.zw/overview"]},
        body="## Relationships\n- regulates → electricity licensing\n- oversees → energy compliance",
        source_claims=[
            ResearchClaim(
                claim="Zimbabwe Energy Regulatory Authority regulates electricity licensing.",
                field_name="relationship",
                source_url="https://example.gov.zw/licensing",
                source_title="Licensing",
                evidence_passage="regulates electricity licensing.",
                confidence=0.9,
            ),
            ResearchClaim(
                claim="Zimbabwe Energy Regulatory Authority oversees energy compliance.",
                field_name="relationship",
                source_url="https://example.gov.zw/overview",
                source_title="Overview",
                evidence_passage="oversees energy compliance.",
                confidence=0.8,
            ),
        ],
    )

    first = CanonicalNodeRowBuilder().build(draft)
    second = CanonicalNodeRowBuilder().build(draft)

    assert first.model_dump() == second.model_dump()
    assert "https://example.gov.zw/licensing|https://example.gov.zw/overview" in first.serialize_csv()


def test_canonical_row_rejects_missing_entity_summary_or_provenance():
    with pytest.raises(ValueError):
        CanonicalNodeRow(
            uid="bad",
            entity="",
            aliases=[],
            entity_type=None,
            subtype=None,
            country=None,
            sector=None,
            status=None,
            summary="",
            relationships=[],
            associations=[],
            sources=[],
        )

    with pytest.raises(ValueError):
        CanonicalNodeRow(
            uid="bad",
            entity="Zimbabwe Energy Regulatory Authority",
            aliases=[],
            entity_type=None,
            subtype=None,
            country=None,
            sector=None,
            status=None,
            summary="No subject or function.",
            relationships=[],
            associations=[],
            sources=["https://example.gov.zw/one"],
        )


def test_canonical_row_serializes_aliases_and_associations():
    draft = NodeDraft(
        title="ZERA",
        frontmatter={"entity": "ZERA", "sources": ["https://example.gov.zw/overview"]},
        body="## Relationships\n- relevant_to → energy investment",
        source_claims=[
            ResearchClaim(
                claim="ZERA is relevant to energy investment.",
                field_name="association",
                source_url="https://example.gov.zw/overview",
                source_title="Overview",
                evidence_passage="ZERA is relevant to energy investment.",
                confidence=0.7,
            )
        ],
    )

    row = CanonicalNodeRowBuilder().build(draft)

    assert row.aliases == ["ZERA"]
    assert "relevant_to::[[Energy Investment]]" in row.associations
    assert row.serialize_csv().count("|") >= 1


def test_canonical_row_builder_rejects_empty_node_draft():
    with pytest.raises(ValueError):
        CanonicalNodeRowBuilder().build(NodeDraft(title="", frontmatter={}, body="", source_claims=[]))


def test_export_package_serializes_csv_and_json_for_rows():
    row = CanonicalNodeRow(
        uid="zimbabwe-energy-regulatory-authority",
        entity="Zimbabwe Energy Regulatory Authority",
        aliases=["ZERA"],
        entity_type="authority",
        subtype=None,
        country="Zimbabwe",
        sector="energy",
        status="draft",
        summary="[[Zimbabwe Energy Regulatory Authority]] regulates [[Electricity]]. It functions by licensing and monitoring energy activity.",
        relationships=["regulates::[[Electricity]]"],
        associations=["relevant_to::[[Energy Security]]"],
        sources=["https://example.gov.zw/licensing", "https://example.gov.zw/overview"],
    )

    package = ExportPackage(rows=[row])
    csv_output = package.to_csv()
    json_output = package.to_json()

    assert csv_output.splitlines()[0] == "uid,entity,aliases,entity_type,subtype,country,sector,status,summary,relationships,associations,sources"
    assert "[[Electricity]]" in csv_output
    assert '"aliases": [' in json_output
    assert '"ZERA"' in json_output
    assert '"regulates::[[Electricity]]"' in json_output
    assert "https://example.gov.zw/licensing|https://example.gov.zw/overview" in csv_output


def test_export_package_multiple_rows_are_ordered_and_deterministic():
    rows = [
        CanonicalNodeRow(
            uid="alpha",
            entity="Alpha Org",
            aliases=["AO"],
            entity_type="agency",
            subtype=None,
            country=None,
            sector=None,
            status="draft",
            summary="[[Alpha Org]] regulates [[Energy]]. It functions by coordinating oversight.",
            relationships=["regulates::[[Energy]]"],
            associations=[],
            sources=["https://example.com/alpha"],
        ),
        CanonicalNodeRow(
            uid="beta",
            entity="Beta Org",
            aliases=["BO"],
            entity_type="agency",
            subtype=None,
            country=None,
            sector=None,
            status="draft",
            summary="[[Beta Org]] manages [[Water]]. It functions by licensing and oversight.",
            relationships=["manages::[[Water]]"],
            associations=[],
            sources=["https://example.com/beta"],
        ),
    ]

    first = export_rows(rows)
    second = export_rows(rows)

    assert first.to_csv() == second.to_csv()
    assert first.to_dicts()[0]["uid"] == "alpha"
    assert first.to_dicts()[1]["uid"] == "beta"


def test_export_package_rejects_invalid_rows_and_empty_input_policy():
    with pytest.raises(ValueError):
        ExportPackage(rows=[CanonicalNodeRow(
            uid="",
            entity="Bad",
            aliases=[],
            entity_type=None,
            subtype=None,
            country=None,
            sector=None,
            status=None,
            summary="[[Bad]] regulates [[Energy]]. It functions by oversight.",
            relationships=[],
            associations=[],
            sources=["https://example.com/bad"],
        )]).validate()

    empty = export_rows([])
    assert empty.rows == []
    assert empty.to_dicts() == []


def test_import_bundle_creates_csv_json_and_template():
    row = CanonicalNodeRow(
        uid="zimbabwe-energy-regulatory-authority",
        entity="Zimbabwe Energy Regulatory Authority",
        aliases=["ZERA"],
        entity_type="government_agency",
        subtype="energy_regulator",
        country="Zimbabwe",
        sector="Energy",
        status="active",
        summary="[[Zimbabwe Energy Regulatory Authority]] regulates [[Electricity]]. It functions by licensing and monitoring energy activity.",
        relationships=["regulates::[[Electricity]]"],
        associations=["relevant_to::[[Energy Security]]"],
        sources=["https://zera.co.zw"],
    )

    bundle = ImportBundle.from_rows([row])

    assert bundle.rows[0].entity == row.entity
    assert "uid,entity,aliases" in bundle.csv_text
    assert '"uid": "zimbabwe-energy-regulatory-authority"' in bundle.json_text
    assert "entity: {{entity}}" in bundle.template_text
    assert "{{summary}}" in bundle.template_text


def test_import_bundle_round_trip_preserves_wikilinks_and_unicode():
    row = CanonicalNodeRow(
        uid="energy-regulator",
        entity="Zimbabwe Energy Regulatory Authority",
        aliases=["ZERA", "Zimbabwe Energy Regulator"],
        entity_type="government_agency",
        subtype="energy_regulator",
        country="Zimbabwe",
        sector="Energy",
        status="active",
        summary="[[Zimbabwe Energy Regulatory Authority]] is the statutory authority responsible for regulating Zimbabwe's [[energy sector]]. It functions by licensing and monitoring [[electricity]] and [[petroleum]].",
        relationships=["regulates::[[Electricity]]", "established_by::[[Energy Regulatory Act]]"],
        associations=["relevant_to::[[Energy Security]]"],
        sources=["https://zera.co.zw/report?lang=en"],
    )

    bundle = ImportBundle.from_rows([row])
    parsed = __import__("json").loads(bundle.json_text)

    assert parsed[0]["entity"] == row.entity
    assert parsed[0]["relationships"][0] == "regulates::[[Electricity]]"
    assert "[[energy sector]]" in bundle.render_markdown(row)
    assert "[[petroleum]]" in bundle.render_markdown(row)
    assert "Zimbabwe's" in bundle.render_markdown(row)


def test_import_bundle_template_renders_valid_markdown():
    row = CanonicalNodeRow(
        uid="zera",
        entity="Zimbabwe Energy Regulatory Authority",
        aliases=["ZERA"],
        entity_type="government_agency",
        subtype="energy_regulator",
        country="Zimbabwe",
        sector="Energy",
        status="active",
        summary="[[Zimbabwe Energy Regulatory Authority]] regulates [[Electricity]]. It functions by licensing and monitoring demand.",
        relationships=["regulates::[[Electricity]]"],
        associations=["relevant_to::[[Energy Security]]"],
        sources=["https://zera.co.zw"],
    )

    rendered = ImportBundle.from_rows([row]).render_markdown(row)

    assert "---" in rendered
    assert "entity: Zimbabwe Energy Regulatory Authority" in rendered
    assert "aliases:" in rendered
    assert "- ZERA" in rendered
    assert "## Summary" in rendered
    assert "[[Electricity]]" in rendered
    assert "## Relationships" in rendered
    assert "regulates::[[Electricity]]" in rendered
    assert "## Associations" in rendered
    assert "relevant_to::[[Energy Security]]" in rendered
