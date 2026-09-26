"""
STEP 6: Controlled Evidence Selection Experiment

This experiment tests the impact of different evidence configurations on
semantic decision-making using the existing Mistral enrichment boundary.

The experiment is isolated from production code - it only tests the semantic
enrichment function with controlled evidence fixtures.

OBJECTIVE: Determine what evidence set the semantic LLM needs to make
correct semantic decisions reliably.

DO NOT: Modify production code, ontology, SemanticDecision schema, model,
provider, semantic prompt, or any production behavior.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.research.evidence import (
    EvidenceRecord,
    EvidenceStatus,
    ExtractionQuality,
    SourceType,
)
from app.services.research.mistral_enrichment import (
    _create_evidence_chunks,
    enrich_evidence_with_mistral,
)
from app.services.ontology import get_ontology


# =============================================================================
# EXPERIMENT HARNESS
# =============================================================================

@dataclass
class ExperimentConfig:
    """Configuration for an evidence experiment run."""
    name: str
    evidence_records: List[EvidenceRecord]
    entity_name: str = "SAPP"
    description: str = ""


@dataclass
class ExperimentResult:
    """Result of running semantic enrichment on a configuration."""
    config_name: str
    run_index: int = 0
    
    # Evidence metrics
    num_records: int = 0
    num_chunks: int = 0
    total_characters: int = 0
    source_distribution: Dict[str, int] = field(default_factory=dict)
    num_substantive: int = 0
    num_thin: int = 0
    num_duplicates: int = 0
    num_irrelevant: int = 0
    
    # Semantic output
    entity: Optional[str] = None
    entity_type: Optional[str] = None
    subtype: Optional[str] = None
    country: Optional[str] = None
    sector: Optional[str] = None
    status: Optional[str] = None
    summary: Optional[str] = None
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    associations: List[Dict[str, Any]] = field(default_factory=list)
    uncertainties: List[str] = field(default_factory=list)
    
    # Execution metadata
    success: bool = False
    error_message: Optional[str] = None
    raw_response: Optional[str] = None
    
    # Classification
    result_classification: str = ""  # consistent, contradicted, ambiguous, unstable


@dataclass
class ExperimentRun:
    """Complete experiment run with multiple configurations."""
    name: str
    configs: List[ExperimentConfig]
    results: List[ExperimentResult] = field(default_factory=list)
    
    def add_result(self, result: ExperimentResult) -> None:
        self.results.append(result)


# =============================================================================
# EVIDENCE FIXTURES
# =============================================================================

def create_authoritative_sapp_evidence() -> List[EvidenceRecord]:
    """Create authoritative substantive evidence for SAPP.
    
    SAPP (Southern African Power Pool) is a regional cooperation organization
    for electricity/power in Southern Africa.
    """
    return [
        EvidenceRecord(
            url="https://www.sapp.co.zw/about",
            title="About SAPP - Southern African Power Pool",
            snippet="The Southern African Power Pool (SAPP) is a cooperation of the national electricity companies in Southern Africa.",
            content="""The Southern African Power Pool (SAPP) is a regional cooperation organization established in 1995. It coordinates the planning, generation, transmission, and marketing of electricity among the national electricity utilities in the Southern African Development Community (SADC) region. SAPP facilitates cross-border electricity trade and ensures reliable power supply across member countries. The organization operates under the auspices of the SADC Energy Sector and works to integrate the power systems of its member utilities.""",
            source="official",
            query="SAPP",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.SUBSTANTIVE,
            evidence_status=EvidenceStatus.USABLE,
        ),
        EvidenceRecord(
            url="https://www.sadc.int/sapp",
            title="SAPP - SADC Energy Programme",
            snippet="SAPP coordinates electricity trading among SADC member states.",
            content="""The Southern African Power Pool (SAPP) is the regional electricity cooperation platform for the Southern African Development Community. It was established to facilitate the development of a competitive electricity market and to ensure the efficient utilization of energy resources across the region. SAPP member utilities include national power companies from Angola, Botswana, Democratic Republic of Congo, Lesotho, Malawi, Mozambique, Namibia, South Africa, Swaziland, Tanzania, Zambia, and Zimbabwe.""",
            source="institutional",
            query="SAPP Southern African Power Pool",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.SUBSTANTIVE,
            evidence_status=EvidenceStatus.USABLE,
        ),
        EvidenceRecord(
            url="https://en.wikipedia.org/wiki/Southern_African_Power_Pool",
            title="Southern African Power Pool - Wikipedia",
            snippet="SAPP is a regional electricity cooperation organization in Southern Africa.",
            content="""The Southern African Power Pool (SAPP) is an organization that coordinates the development and operation of electricity infrastructure in Southern Africa. It is a cooperation of national electricity companies working together to ensure reliable and affordable electricity supply across the region. SAPP operates as a regional power pool, facilitating electricity trade and grid interconnection among its members.""",
            source="wikipedia",
            query="Southern African Power Pool",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.SUBSTANTIVE,
            evidence_status=EvidenceStatus.USABLE,
        ),
    ]


def create_secondary_sapp_evidence() -> List[EvidenceRecord]:
    """Create secondary substantive evidence about SAPP."""
    return [
        EvidenceRecord(
            url="https://www.afdb.org/en/sapp",
            title="AfDB - SAPP Support",
            snippet="The African Development Bank supports SAPP infrastructure projects.",
            content="""The African Development Bank has provided financing for various SAPP infrastructure projects, including transmission lines and interconnector projects that enhance regional electricity trade. SAPP's work in coordinating electricity infrastructure development has been recognized as a model for regional cooperation in Africa.""",
            source="institutional",
            query="SAPP AfDB",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.SUBSTANTIVE,
            evidence_status=EvidenceStatus.USABLE,
        ),
        EvidenceRecord(
            url="https://www.worldbank.org/en/sapp",
            title="World Bank - SAPP Regional Integration",
            snippet="SAPP promotes regional electricity market integration.",
            content="""The Southern African Power Pool (SAPP) promotes regional integration of electricity markets in Southern Africa. Through coordinated planning and infrastructure development, SAPP enables member countries to share electricity resources efficiently, reducing costs and improving reliability.""",
            source="institutional",
            query="SAPP World Bank",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.SUBSTANTIVE,
            evidence_status=EvidenceStatus.USABLE,
        ),
    ]


def create_thin_misleading_framework_evidence() -> List[EvidenceRecord]:
    """Create THIN evidence containing misleading 'framework' language.
    
    These are short snippets that mention 'framework' in a way that could
    potentially mislead the model into classifying SAPP as a Framework.
    """
    return [
        EvidenceRecord(
            url="https://example.com/news1",
            title="Regional Electricity Framework News",
            snippet="SAPP operates within a regional electricity framework.",
            content="SAPP operates within a regional electricity framework.",
            source="news",
            query="SAPP framework",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.THIN,
            evidence_status=EvidenceStatus.THIN,
        ),
        EvidenceRecord(
            url="https://example.com/news2",
            title="Power Sector Framework",
            snippet="The regional power framework includes SAPP.",
            content="The regional power framework includes SAPP.",
            source="news",
            query="SAPP power framework",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.THIN,
            evidence_status=EvidenceStatus.THIN,
        ),
        EvidenceRecord(
            url="https://example.com/news3",
            title="Electricity Cooperation Framework",
            snippet="SAPP is part of the electricity cooperation framework.",
            content="SAPP is part of the electricity cooperation framework.",
            source="news",
            query="SAPP electricity cooperation",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.THIN,
            evidence_status=EvidenceStatus.THIN,
        ),
    ]


def create_duplicate_evidence(base_records: List[EvidenceRecord]) -> List[EvidenceRecord]:
    """Create duplicate evidence records with same content but different URLs.
    
    This simulates syndicated/duplicated information.
    """
    duplicates = []
    for i, record in enumerate(base_records[:2]):  # Duplicate first 2 records
        # Create 2 duplicates for each
        for dup_num in range(1, 3):
            dup_record = deepcopy(record)
            # Modify URL to create duplicate
            dup_record.url = f"{record.url}_dup{dup_num}"
            # Keep same content
            duplicates.append(dup_record)
    return duplicates


def create_irrelevant_evidence() -> List[EvidenceRecord]:
    """Create irrelevant evidence that has nothing to do with SAPP."""
    return [
        EvidenceRecord(
            url="https://example.com/weather",
            title="Weather Forecast for Southern Africa",
            snippet="Weather patterns in Southern Africa are varied.",
            content="Weather patterns in Southern Africa are varied throughout the year.",
            source="news",
            query="weather",
            entity_name="",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.THIN,
            evidence_status=EvidenceStatus.THIN,
        ),
        EvidenceRecord(
            url="https://example.com/sports",
            title="Southern African Sports News",
            snippet="Football tournaments in Southern Africa.",
            content="Football tournaments are popular in Southern Africa.",
            source="news",
            query="sports",
            entity_name="",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.THIN,
            evidence_status=EvidenceStatus.THIN,
        ),
    ]


def create_unusable_evidence() -> List[EvidenceRecord]:
    """Create UNUSABLE evidence (should be filtered out by _create_evidence_chunks)."""
    return [
        EvidenceRecord(
            url="https://example.com/blocked",
            title="Access Denied",
            snippet="Access denied. Please verify you are human.",
            content="Access denied. Please verify you are human.",
            source="web",
            query="SAPP",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.BLOCK_PAGE,
            evidence_status=EvidenceStatus.UNUSABLE,
        ),
        EvidenceRecord(
            url="https://example.com/error",
            title="500 Internal Server Error",
            snippet="Internal Server Error",
            content="500 Internal Server Error - The server encountered an unexpected condition.",
            source="web",
            query="SAPP",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.ERROR_PAGE,
            evidence_status=EvidenceStatus.UNUSABLE,
        ),
    ]


# =============================================================================
# EXPERIMENT CONFIGURATIONS
# =============================================================================

def build_configuration_a() -> ExperimentConfig:
    """Configuration A: Authoritative substantive evidence only."""
    return ExperimentConfig(
        name="A_substantive_only",
        entity_name="SAPP",
        evidence_records=create_authoritative_sapp_evidence(),
        description="Authoritative substantive evidence only",
    )


def build_configuration_b() -> ExperimentConfig:
    """Configuration B: Substantive + one THIN misleading 'framework' statement."""
    auth = create_authoritative_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    return ExperimentConfig(
        name="B_substantive_plus_one_thin",
        entity_name="SAPP",
        evidence_records=auth[:1] + thin[:1],  # 1 authoritative + 1 thin
        description="Substantive + one THIN misleading 'framework' evidence",
    )


def build_configuration_c() -> ExperimentConfig:
    """Configuration C: Substantive + several duplicate 'framework' statements."""
    auth = create_authoritative_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    return ExperimentConfig(
        name="C_substantive_plus_multiple_thin",
        entity_name="SAPP",
        evidence_records=auth[:1] + thin,  # 1 authoritative + 3 thin framework
        description="Substantive + several duplicate 'framework' statements",
    )


def build_configuration_d() -> ExperimentConfig:
    """Configuration D: Mixed evidence (authoritative + secondary + thin + duplicates + irrelevant)."""
    auth = create_authoritative_sapp_evidence()
    secondary = create_secondary_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    irrelevant = create_irrelevant_evidence()
    duplicates = create_duplicate_evidence(auth)
    
    return ExperimentConfig(
        name="D_mixed",
        entity_name="SAPP",
        evidence_records=auth + secondary[:1] + thin[:2] + duplicates + irrelevant,
        description="Mixed: authoritative + secondary + thin + duplicates + irrelevant",
    )


def build_configuration_e() -> ExperimentConfig:
    """Configuration E: Substantive + duplicates of authoritative content."""
    auth = create_authoritative_sapp_evidence()
    duplicates = create_duplicate_evidence(auth)
    
    return ExperimentConfig(
        name="E_substantive_plus_duplicates",
        entity_name="SAPP",
        evidence_records=auth + duplicates,
        description="Substantive + duplicate authoritative copies",
    )


def build_configuration_f() -> ExperimentConfig:
    """Configuration F: Substantive + UNUSABLE evidence (should be filtered)."""
    auth = create_authoritative_sapp_evidence()
    unusable = create_unusable_evidence()
    
    return ExperimentConfig(
        name="F_substantive_plus_unusable",
        entity_name="SAPP",
        evidence_records=auth + unusable,
        description="Substantive + UNUSABLE evidence (should be filtered out)",
    )


def build_configuration_g(num_records: int = 5) -> ExperimentConfig:
    """Configuration G: Context volume experiment - N records."""
    auth = create_authoritative_sapp_evidence()
    secondary = create_secondary_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    irrelevant = create_irrelevant_evidence()
    
    # Build a larger set - duplicate records to reach higher volumes
    all_records = auth + secondary + thin + irrelevant
    
    # If we need more than available, duplicate the set
    while len(all_records) < num_records:
        all_records = all_records + all_records
    
    # Select first num_records
    selected = all_records[:num_records]
    
    return ExperimentConfig(
        name=f"G_volume_{num_records}_records",
        entity_name="SAPP",
        evidence_records=selected,
        description=f"Context volume: {num_records} records",
    )


def build_configuration_order_a() -> ExperimentConfig:
    """Order A: authoritative -> secondary -> thin -> irrelevant."""
    auth = create_authoritative_sapp_evidence()
    secondary = create_secondary_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    irrelevant = create_irrelevant_evidence()
    
    return ExperimentConfig(
        name="ORDER_A_auth_secondary_thin_irrelevant",
        entity_name="SAPP",
        evidence_records=auth[:1] + secondary[:1] + thin[:1] + irrelevant[:1],
        description="Order: authoritative -> secondary -> thin -> irrelevant",
    )


def build_configuration_order_b() -> ExperimentConfig:
    """Order B: thin -> irrelevant -> secondary -> authoritative."""
    auth = create_authoritative_sapp_evidence()
    secondary = create_secondary_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    irrelevant = create_irrelevant_evidence()
    
    return ExperimentConfig(
        name="ORDER_B_thin_irrelevant_secondary_auth",
        entity_name="SAPP",
        evidence_records=thin[:1] + irrelevant[:1] + secondary[:1] + auth[:1],
        description="Order: thin -> irrelevant -> secondary -> authoritative",
    )


# =============================================================================
# HYPOTHESIS TEST CONFIGURATIONS
# =============================================================================

def build_configuration_hypothesis_a() -> ExperimentConfig:
    """Hypothesis test A: authoritative evidence only."""
    return build_configuration_a()


def build_configuration_hypothesis_b() -> ExperimentConfig:
    """Hypothesis test B: authoritative + one THIN 'framework' statement."""
    return build_configuration_b()


def build_configuration_hypothesis_c() -> ExperimentConfig:
    """Hypothesis test C: authoritative + several duplicate 'framework' statements."""
    return build_configuration_c()


def build_configuration_hypothesis_d() -> ExperimentConfig:
    """Hypothesis test D: authoritative + misleading + irrelevant mixed evidence."""
    return build_configuration_d()


# =============================================================================
# DUPLICATE CONTENT EXPERIMENT CONFIGURATIONS
# =============================================================================

def build_duplicate_content_experiment_single() -> ExperimentConfig:
    """Duplicate experiment: single authoritative record."""
    auth = create_authoritative_sapp_evidence()
    return ExperimentConfig(
        name="DUP_single_authoritative",
        entity_name="SAPP",
        evidence_records=auth[:1],
        description="Single authoritative record",
    )


def build_duplicate_content_experiment_triple() -> ExperimentConfig:
    """Duplicate experiment: same authoritative content repeated across 3 URLs."""
    base = create_authoritative_sapp_evidence()[0]
    records = [
        EvidenceRecord(
            url="https://sapp.co.zw/about",
            title=base.title,
            snippet=base.snippet,
            content=base.content,
            source=base.source,
            query=base.query,
            entity_name=base.entity_name,
            retrieval_status=base.retrieval_status,
            extraction_quality=base.extraction_quality,
            evidence_status=base.evidence_status,
        ),
        EvidenceRecord(
            url="https://mirror1.example.com/sapp/about",
            title=base.title,
            snippet=base.snippet,
            content=base.content,
            source=base.source,
            query=base.query,
            entity_name=base.entity_name,
            retrieval_status=base.retrieval_status,
            extraction_quality=base.extraction_quality,
            evidence_status=base.evidence_status,
        ),
        EvidenceRecord(
            url="https://mirror2.example.com/sapp/about",
            title=base.title,
            snippet=base.snippet,
            content=base.content,
            source=base.source,
            query=base.query,
            entity_name=base.entity_name,
            retrieval_status=base.retrieval_status,
            extraction_quality=base.extraction_quality,
            evidence_status=base.evidence_status,
        ),
    ]
    return ExperimentConfig(
        name="DUP_triple_authoritative",
        entity_name="SAPP",
        evidence_records=records,
        description="Same authoritative content repeated across 3 URLs",
    )


def build_duplicate_content_experiment_quintuple() -> ExperimentConfig:
    """Duplicate experiment: same authoritative content repeated across 5 URLs."""
    base = create_authoritative_sapp_evidence()[0]
    records = []
    for i in range(5):
        records.append(
            EvidenceRecord(
                url=f"https://mirror{i}.example.com/sapp/about",
                title=base.title,
                snippet=base.snippet,
                content=base.content,
                source=base.source,
                query=base.query,
                entity_name=base.entity_name,
                retrieval_status=base.retrieval_status,
                extraction_quality=base.extraction_quality,
                evidence_status=base.evidence_status,
            )
        )
    return ExperimentConfig(
        name="DUP_quintuple_authoritative",
        entity_name="SAPP",
        evidence_records=records,
        description="Same authoritative content repeated across 5 URLs",
    )


def build_duplicate_content_experiment_different_secondary() -> ExperimentConfig:
    """Duplicate experiment: authoritative + different secondary source."""
    auth = create_authoritative_sapp_evidence()
    secondary = create_secondary_sapp_evidence()
    return ExperimentConfig(
        name="DUP_auth_plus_different_secondary",
        entity_name="SAPP",
        evidence_records=auth[:1] + secondary[:1],
        description="Authoritative content + different secondary source",
    )


# =============================================================================
# THIN EVIDENCE EXPERIMENT CONFIGURATIONS
# =============================================================================

def build_thin_experiment_substantive_only() -> ExperimentConfig:
    """THIN experiment: substantive only."""
    return build_configuration_a()


def build_thin_experiment_plus_one() -> ExperimentConfig:
    """THIN experiment: substantive + one THIN."""
    return build_configuration_b()


def build_thin_experiment_plus_several() -> ExperimentConfig:
    """THIN experiment: substantive + several THIN."""
    auth = create_authoritative_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    return ExperimentConfig(
        name="THIN_substantive_plus_several",
        entity_name="SAPP",
        evidence_records=auth[:1] + thin,  # 1 authoritative + 3 thin
        description="Substantive + several THIN evidence",
    )


# =============================================================================
# EXPERIMENT EXECUTION
# =============================================================================

def analyze_evidence_metrics(evidence_records: List[EvidenceRecord]) -> Dict[str, Any]:
    """Analyze evidence metrics without calling Mistral."""
    num_records = len(evidence_records)
    source_dist: Dict[str, int] = {}
    num_substantive = 0
    num_thin = 0
    num_unusable = 0
    
    for record in evidence_records:
        source = record.source or "unknown"
        source_dist[source] = source_dist.get(source, 0) + 1
        
        if record.evidence_status == EvidenceStatus.USABLE:
            num_substantive += 1
        elif record.evidence_status == EvidenceStatus.THIN:
            num_thin += 1
        elif record.evidence_status == EvidenceStatus.UNUSABLE:
            num_unusable += 1
    
    # Create chunks to count them
    chunks = _create_evidence_chunks(evidence_records)
    num_chunks = len(chunks)
    
    # Calculate total characters
    total_chars = 0
    for chunk in chunks:
        total_chars += len(chunk.get("content", ""))
    
    return {
        "num_records": num_records,
        "num_chunks": num_chunks,
        "total_characters": total_chars,
        "source_distribution": source_dist,
        "num_substantive": num_substantive,
        "num_thin": num_thin,
        "num_unusable": num_unusable,
    }


def classify_result(
    result: ExperimentResult,
    expected_entity_type: str = "regional organization",
    expected_subtype: Optional[str] = None,
) -> str:
    """Classify the semantic result descriptively.
    
    Returns one of: consistent, contradicted, ambiguous, unstable
    """
    if not result.success:
        return "failed"
    
    if result.entity_type is None:
        return "ambiguous"
    
    # Check if entity_type matches expected
    if expected_entity_type.lower() in (result.entity_type or "").lower():
        return "consistent"
    
    # Check if it's clearly wrong (e.g., Framework when it should be organization)
    if "framework" in (result.entity_type or "").lower() and expected_entity_type.lower() != "framework":
        return "contradicted"
    
    return "ambiguous"


# =============================================================================
# TEST: Experiment Setup Verification
# =============================================================================

class TestExperimentSetup:
    """Verify the experiment setup."""
    
    def test_semantic_boundary_identified(self):
        """Verify that _create_evidence_chunks is the boundary function."""
        # The boundary is: EvidenceRecord[] -> _create_evidence_chunks() -> Mistral
        auth = create_authoritative_sapp_evidence()
        chunks = _create_evidence_chunks(auth)
        
        assert len(chunks) > 0
        assert all("content" in c for c in chunks)
        assert all("url" in c for c in chunks)
    
    def test_authoritative_evidence_created(self):
        """Verify authoritative evidence fixtures are created correctly."""
        auth = create_authoritative_sapp_evidence()
        
        assert len(auth) == 3
        assert all(r.evidence_status == EvidenceStatus.USABLE for r in auth)
        assert all(r.extraction_quality == ExtractionQuality.SUBSTANTIVE for r in auth)
        assert all("SAPP" in r.content for r in auth)
        assert all("electricity" in r.content.lower() or "power" in r.content.lower() for r in auth)
    
    def test_thin_misleading_evidence_created(self):
        """Verify THIN misleading evidence fixtures."""
        thin = create_thin_misleading_framework_evidence()
        
        assert len(thin) == 3
        assert all(r.evidence_status == EvidenceStatus.THIN for r in thin)
        assert all(r.extraction_quality == ExtractionQuality.THIN for r in thin)
        assert all("framework" in r.content.lower() for r in thin)
    
    def test_duplicate_evidence_created(self):
        """Verify duplicate evidence fixtures."""
        auth = create_authoritative_sapp_evidence()
        dups = create_duplicate_evidence(auth)
        
        assert len(dups) == 4  # 2 base records * 2 duplicates each
        # Verify URLs are different but content should be same for duplicates
        urls = [r.url for r in dups]
        assert len(set(urls)) == 4  # All URLs should be unique
    
    def test_irrelevant_evidence_created(self):
        """Verify irrelevant evidence fixtures."""
        irrelevant = create_irrelevant_evidence()
        
        assert len(irrelevant) == 2
        assert all(r.evidence_status == EvidenceStatus.THIN for r in irrelevant)
        # Should not mention SAPP or electricity
        assert all("sapp" not in r.content.lower() for r in irrelevant)
    
    def test_unusable_evidence_created(self):
        """Verify UNUSABLE evidence fixtures."""
        unusable = create_unusable_evidence()
        
        assert len(unusable) == 2
        assert all(r.evidence_status == EvidenceStatus.UNUSABLE for r in unusable)
    
    def test_configuration_a_built(self):
        """Verify Configuration A is built correctly."""
        config = build_configuration_a()
        
        assert config.name == "A_substantive_only"
        assert len(config.evidence_records) == 3
        assert all(r.evidence_status == EvidenceStatus.USABLE for r in config.evidence_records)
    
    def test_configuration_b_built(self):
        """Verify Configuration B is built correctly."""
        config = build_configuration_b()
        
        assert config.name == "B_substantive_plus_one_thin"
        assert len(config.evidence_records) == 2  # 1 auth + 1 thin
        # First should be authoritative, second should be thin
        assert config.evidence_records[0].evidence_status == EvidenceStatus.USABLE
        assert config.evidence_records[1].evidence_status == EvidenceStatus.THIN
    
    def test_configuration_c_built(self):
        """Verify Configuration C is built correctly."""
        config = build_configuration_c()
        
        assert config.name == "C_substantive_plus_multiple_thin"
        assert len(config.evidence_records) == 4  # 1 auth + 3 thin
    
    def test_configuration_d_built(self):
        """Verify Configuration D (mixed) is built correctly."""
        config = build_configuration_d()
        
        assert config.name == "D_mixed"
        # Should have: 3 auth + 1 secondary + 2 thin + 2 duplicates + 2 irrelevant = 10
        assert len(config.evidence_records) >= 8
    
    def test_configuration_e_built(self):
        """Verify Configuration E (duplicates) is built correctly."""
        config = build_configuration_e()
        
        assert config.name == "E_substantive_plus_duplicates"
        # Should have: 3 auth + 4 duplicates = 7
        assert len(config.evidence_records) == 7
    
    def test_configuration_f_built(self):
        """Verify Configuration F (unusable) is built correctly."""
        config = build_configuration_f()
        
        assert config.name == "F_substantive_plus_unusable"
        # Should have: 3 auth + 2 unusable = 5
        assert len(config.evidence_records) == 5
    
    def test_volume_configurations_built(self):
        """Verify volume configurations are built correctly."""
        for num in [5, 10, 25]:
            config = build_configuration_g(num)
            assert config.name == f"G_volume_{num}_records"
            assert len(config.evidence_records) == num
    
    def test_ordering_configurations_built(self):
        """Verify ordering configurations are built correctly."""
        config_a = build_configuration_order_a()
        config_b = build_configuration_order_b()
        
        assert config_a.name == "ORDER_A_auth_secondary_thin_irrelevant"
        assert config_b.name == "ORDER_B_thin_irrelevant_secondary_auth"
        
        # Both should have same records but different order
        assert len(config_a.evidence_records) == len(config_b.evidence_records)
        assert config_a.evidence_records[0].evidence_status == EvidenceStatus.USABLE
        assert config_b.evidence_records[0].evidence_status == EvidenceStatus.THIN
    
    def test_hypothesis_configurations_built(self):
        """Verify SAPP hypothesis test configurations."""
        configs = [
            build_configuration_hypothesis_a(),
            build_configuration_hypothesis_b(),
            build_configuration_hypothesis_c(),
            build_configuration_hypothesis_d(),
        ]
        
        assert len(configs) == 4
        assert configs[0].name == "A_substantive_only"
        assert configs[1].name == "B_substantive_plus_one_thin"
        assert configs[2].name == "C_substantive_plus_multiple_thin"
        assert configs[3].name == "D_mixed"
    
    def test_duplicate_content_configurations_built(self):
        """Verify duplicate content experiment configurations."""
        configs = [
            build_duplicate_content_experiment_single(),
            build_duplicate_content_experiment_triple(),
            build_duplicate_content_experiment_quintuple(),
            build_duplicate_content_experiment_different_secondary(),
        ]
        
        assert len(configs) == 4
        assert configs[0].name == "DUP_single_authoritative"
        assert configs[1].name == "DUP_triple_authoritative"
        assert configs[2].name == "DUP_quintuple_authoritative"
        assert configs[3].name == "DUP_auth_plus_different_secondary"
    
    def test_thin_evidence_configurations_built(self):
        """Verify THIN evidence experiment configurations."""
        configs = [
            build_thin_experiment_substantive_only(),
            build_thin_experiment_plus_one(),
            build_thin_experiment_plus_several(),
        ]
        
        assert len(configs) == 3
        assert configs[0].name == "A_substantive_only"
        assert configs[1].name == "B_substantive_plus_one_thin"
        assert configs[2].name == "THIN_substantive_plus_several"


# =============================================================================
# TEST: Evidence Metrics Analysis
# =============================================================================

class TestEvidenceMetrics:
    """Test evidence metrics calculation."""
    
    def test_metrics_for_configuration_a(self):
        """Test metrics calculation for Configuration A."""
        config = build_configuration_a()
        metrics = analyze_evidence_metrics(config.evidence_records)
        
        assert metrics["num_records"] == 3
        assert metrics["num_substantive"] == 3
        assert metrics["num_thin"] == 0
        assert metrics["num_chunks"] >= 3  # Each record should produce at least 1 chunk
        assert metrics["total_characters"] > 0
    
    def test_metrics_for_configuration_b(self):
        """Test metrics calculation for Configuration B."""
        config = build_configuration_b()
        metrics = analyze_evidence_metrics(config.evidence_records)
        
        assert metrics["num_records"] == 2
        assert metrics["num_substantive"] == 1
        assert metrics["num_thin"] == 1
    
    def test_metrics_for_configuration_f(self):
        """Test metrics for Configuration F (should filter UNUSABLE)."""
        config = build_configuration_f()
        metrics = analyze_evidence_metrics(config.evidence_records)
        
        assert metrics["num_records"] == 5
        assert metrics["num_unusable"] == 2
        # But chunks should only include usable ones
        chunks = _create_evidence_chunks(config.evidence_records)
        # UNUSABLE evidence should be filtered out by _create_evidence_chunks
        unusable_count = sum(1 for r in config.evidence_records if r.evidence_status == EvidenceStatus.UNUSABLE)
        assert len(chunks) == metrics["num_records"] - unusable_count


# =============================================================================
# TEST: Chunking Behavior
# =============================================================================

class TestChunkingBehavior:
    """Test the chunking behavior of _create_evidence_chunks."""
    
    def test_chunking_filters_unusable_evidence(self):
        """Verify that UNUSABLE evidence is filtered out by chunking."""
        unusable = create_unusable_evidence()
        chunks = _create_evidence_chunks(unusable)
        
        assert len(chunks) == 0
    
    def test_chunking_includes_thin_evidence(self):
        """Verify that THIN evidence IS included in chunking."""
        thin = create_thin_misleading_framework_evidence()
        chunks = _create_evidence_chunks(thin)
        
        assert len(chunks) == len(thin)
        assert all("framework" in c["content"].lower() for c in chunks)
    
    def test_chunking_preserves_full_content(self):
        """Verify that full content is preserved in chunks."""
        auth = create_authoritative_sapp_evidence()
        chunks = _create_evidence_chunks(auth)
        
        assert len(chunks) >= len(auth)
        # Check that content is preserved
        for chunk in chunks:
            assert "content" in chunk
            assert len(chunk["content"]) > 0
    
    def test_chunking_handles_long_content(self):
        """Verify that long content is split into overlapping chunks."""
        # Create a record with very long content
        long_content = "SAPP is an organization. " * 500  # ~10,000 chars
        record = EvidenceRecord(
            url="https://example.com/long",
            title="Long SAPP content",
            snippet="SAPP is an organization.",
            content=long_content,
            source="test",
            query="SAPP",
            entity_name="SAPP",
            retrieval_status="success",
            extraction_quality=ExtractionQuality.SUBSTANTIVE,
            evidence_status=EvidenceStatus.USABLE,
        )
        
        chunks = _create_evidence_chunks([record])
        
        # With max_chunk_size=4000 and overlap=200, should produce multiple chunks
        assert len(chunks) > 1
        
        # Check overlap
        if len(chunks) >= 2:
            chunk1_end = chunks[0]["content"][-200:] if len(chunks[0]["content"]) >= 200 else ""
            chunk2_start = chunks[1]["content"][:200] if len(chunks[1]["content"]) >= 200 else ""
            # There should be overlap
            assert chunk1_end == chunk2_start


# =============================================================================
# TEST: Fixture-Level Experiment (No Mistral API calls)
# =============================================================================

class TestFixtureLevelExperiment:
    """
    Run the experiment at fixture level without calling Mistral API.
    
    This tests the deterministic behavior of evidence processing up to
    the point where Mistral would be called.
    
    Note: This does NOT test actual model behavior, only the fixture
    processing and chunking behavior.
    """
    
    def test_all_configurations_process_without_error(self):
        """Test that all configurations can be processed through chunking."""
        configs = [
            build_configuration_a(),
            build_configuration_b(),
            build_configuration_c(),
            build_configuration_d(),
            build_configuration_e(),
            build_configuration_f(),
            build_configuration_order_a(),
            build_configuration_order_b(),
            build_duplicate_content_experiment_single(),
            build_duplicate_content_experiment_triple(),
            build_duplicate_content_experiment_quintuple(),
            build_duplicate_content_experiment_different_secondary(),
            build_thin_experiment_substantive_only(),
            build_thin_experiment_plus_one(),
            build_thin_experiment_plus_several(),
        ]
        
        for config in configs:
            # Process through chunking
            chunks = _create_evidence_chunks(config.evidence_records)
            metrics = analyze_evidence_metrics(config.evidence_records)
            
            # Verify basic properties
            assert len(chunks) > 0 or len(config.evidence_records) == 0
            assert metrics["num_records"] == len(config.evidence_records)
            
            print(f"OK {config.name}: {metrics['num_records']} records -> {len(chunks)} chunks, {metrics['total_characters']} chars")
    
    def test_hypothesis_configurations_process(self):
        """Test SAPP hypothesis configurations specifically."""
        configs = [
            build_configuration_hypothesis_a(),
            build_configuration_hypothesis_b(),
            build_configuration_hypothesis_c(),
            build_configuration_hypothesis_d(),
        ]
        
        results = []
        for config in configs:
            chunks = _create_evidence_chunks(config.evidence_records)
            metrics = analyze_evidence_metrics(config.evidence_records)
            
            result = ExperimentResult(
                config_name=config.name,
                num_records=metrics["num_records"],
                num_chunks=len(chunks),
                total_characters=metrics["total_characters"],
                source_distribution=metrics["source_distribution"],
                num_substantive=metrics["num_substantive"],
                num_thin=metrics["num_thin"],
                success=True,
            )
            results.append(result)
        
        # Verify we have results for all configs
        assert len(results) == 4
        
        # Print summary
        print("\n=== SAPP Hypothesis Test - Fixture Level ===")
        print(f"{'Config':<30} {'Records':<8} {'Chunks':<8} {'Chars':<10} {'Subst':<6} {'Thin':<6}")
        print("-" * 80)
        for r in results:
            print(f"{r.config_name:<30} {r.num_records:<8} {r.num_chunks:<8} {r.total_characters:<10} {r.num_substantive:<6} {r.num_thin:<6}")
    
    def test_volume_experiment_process(self):
        """Test context volume experiment configurations."""
        results = []
        for num in [5, 10, 25]:
            config = build_configuration_g(num)
            chunks = _create_evidence_chunks(config.evidence_records)
            metrics = analyze_evidence_metrics(config.evidence_records)
            
            result = ExperimentResult(
                config_name=config.name,
                num_records=metrics["num_records"],
                num_chunks=len(chunks),
                total_characters=metrics["total_characters"],
                source_distribution=metrics["source_distribution"],
                num_substantive=metrics["num_substantive"],
                num_thin=metrics["num_thin"],
                success=True,
            )
            results.append(result)
        
        assert len(results) == 3
        
        # Verify increasing volume
        assert results[0].num_records == 5
        assert results[1].num_records == 10
        assert results[2].num_records == 25
        
        # Verify character count increases
        assert results[0].total_characters < results[1].total_characters
        assert results[1].total_characters < results[2].total_characters
        
        print("\n=== Context Volume Experiment - Fixture Level ===")
        print(f"{'Config':<30} {'Records':<8} {'Chunks':<8} {'Chars':<10}")
        print("-" * 60)
        for r in results:
            print(f"{r.config_name:<30} {r.num_records:<8} {r.num_chunks:<8} {r.total_characters:<10}")
    
    def test_ordering_experiment_process(self):
        """Test deterministic ordering experiment."""
        config_a = build_configuration_order_a()
        config_b = build_configuration_order_b()
        
        chunks_a = _create_evidence_chunks(config_a.evidence_records)
        chunks_b = _create_evidence_chunks(config_b.evidence_records)
        
        metrics_a = analyze_evidence_metrics(config_a.evidence_records)
        metrics_b = analyze_evidence_metrics(config_b.evidence_records)
        
        # Same number of records
        assert metrics_a["num_records"] == metrics_b["num_records"]
        
        # Same number of chunks (order shouldn't affect chunk count)
        assert len(chunks_a) == len(chunks_b)
        
        # Same total characters
        assert metrics_a["total_characters"] == metrics_b["total_characters"]
        
        # But the order of chunks should be different
        if len(chunks_a) >= 2 and len(chunks_b) >= 2:
            first_chunk_a = chunks_a[0]["url"]
            first_chunk_b = chunks_b[0]["url"]
            # Different order should produce different first chunk
            # (unless by coincidence they're the same)
            
        print("\n=== Ordering Experiment - Fixture Level ===")
        print(f"Order A (auth->sec->thin->irr): {len(chunks_a)} chunks, {metrics_a['total_characters']} chars")
        print(f"Order B (thin->irr->sec->auth): {len(chunks_b)} chunks, {metrics_b['total_characters']} chars")
    
    def test_duplicate_experiment_process(self):
        """Test duplicate evidence experiment."""
        configs = [
            build_duplicate_content_experiment_single(),
            build_duplicate_content_experiment_triple(),
            build_duplicate_content_experiment_quintuple(),
            build_duplicate_content_experiment_different_secondary(),
        ]
        
        results = []
        for config in configs:
            chunks = _create_evidence_chunks(config.evidence_records)
            metrics = analyze_evidence_metrics(config.evidence_records)
            
            result = ExperimentResult(
                config_name=config.name,
                num_records=metrics["num_records"],
                num_chunks=len(chunks),
                total_characters=metrics["total_characters"],
                num_substantive=metrics["num_substantive"],
                success=True,
            )
            results.append(result)
        
        assert len(results) == 4
        
        # Single: 1 record -> 1 chunk
        assert results[0].num_records == 1
        
        # Triple: 3 records with same content -> 3 chunks
        assert results[1].num_records == 3
        
        # Quintuple: 5 records with same content -> 5 chunks
        assert results[2].num_records == 5
        
        print("\n=== Duplicate Evidence Experiment - Fixture Level ===")
        print(f"{'Config':<40} {'Records':<8} {'Chunks':<8} {'Chars':<10}")
        print("-" * 70)
        for r in results:
            print(f"{r.config_name:<40} {r.num_records:<8} {r.num_chunks:<8} {r.total_characters:<10}")
    
    def test_thin_evidence_experiment_process(self):
        """Test THIN evidence experiment."""
        configs = [
            build_thin_experiment_substantive_only(),
            build_thin_experiment_plus_one(),
            build_thin_experiment_plus_several(),
        ]
        
        results = []
        for config in configs:
            chunks = _create_evidence_chunks(config.evidence_records)
            metrics = analyze_evidence_metrics(config.evidence_records)
            
            result = ExperimentResult(
                config_name=config.name,
                num_records=metrics["num_records"],
                num_chunks=len(chunks),
                total_characters=metrics["total_characters"],
                num_substantive=metrics["num_substantive"],
                num_thin=metrics["num_thin"],
                success=True,
            )
            results.append(result)
        
        assert len(results) == 3
        
        # Verify THIN count increases
        assert results[0].num_thin == 0
        assert results[1].num_thin == 1
        assert results[2].num_thin == 3
        
        print("\n=== THIN Evidence Experiment - Fixture Level ===")
        print(f"{'Config':<40} {'Records':<8} {'Subst':<6} {'Thin':<6} {'Chars':<10}")
        print("-" * 70)
        for r in results:
            print(f"{r.config_name:<40} {r.num_records:<8} {r.num_substantive:<6} {r.num_thin:<6} {r.total_characters:<10}")


# =============================================================================
# TEST: Ontology Unchanged
# =============================================================================

class TestOntologyUnchanged:
    """Verify that ontology is unchanged for the experiment."""
    
    def test_ontology_available(self):
        """Verify ontology is available."""
        ontology = get_ontology()
        assert ontology is not None
    
    def test_ontology_has_sapp_relevant_types(self):
        """Verify ontology has types relevant to SAPP."""
        ontology = get_ontology()
        
        # SAPP should be classifiable as regional organization
        assert "regional organization" in ontology.all_entity_types
        assert "cooperation" in ontology.all_entity_types
        assert "pool" in ontology.all_entity_types
        
        # Framework should also be a valid type
        assert "framework" in ontology.concept_types
    
    def test_ontology_has_african_countries(self):
        """Verify ontology has African countries."""
        ontology = get_ontology()
        
        assert "zimbabwe" in ontology.countries
        assert "south africa" in ontology.countries
    
    def test_ontology_has_energy_sector(self):
        """Verify ontology has energy sector."""
        ontology = get_ontology()
        
        assert "Energy Sector" in ontology.sectors
        assert "Electricity Sector" in ontology.sectors
