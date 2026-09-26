"""
STEP 8: Reproduce the Historical SAPP Semantic Decision

This module attempts to reproduce the historical SAPP misclassification
using the actual production semantic pipeline.

IMPORTANT: This experiment requires Mistral API access.
If MISTRAL_API_KEY is not configured, the model experiment cannot run.

The experiment is observational only - it does NOT modify production behavior.
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.services.research.evidence import (
    EvidenceRecord,
    EvidenceStatus,
    ExtractionQuality,
    deduplicate_evidence,
)
from app.services.research.mistral_enrichment import (
    _create_evidence_chunks,
    enrich_evidence_with_mistral,
)
from app.services.ontology import get_ontology


# =============================================================================
# EVIDENCE FIXTURES
# =============================================================================

def create_authoritative_sapp_evidence() -> List[EvidenceRecord]:
    """Create authoritative substantive evidence for SAPP."""
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


def create_thin_misleading_framework_evidence() -> List[EvidenceRecord]:
    """Create THIN evidence containing 'framework' language."""
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


def create_duplicate_sapp_evidence() -> List[EvidenceRecord]:
    """Create duplicate SAPP evidence (same content, different URLs)."""
    base = create_authoritative_sapp_evidence()[0]
    return [
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
        EvidenceRecord(
            url="https://mirror3.example.com/sapp/about",
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


# =============================================================================
# EVIDENCE CAPTURE
# =============================================================================

@dataclass
class EvidenceCapture:
    """Capture of evidence at the semantic boundary."""
    entity_name: str
    num_records: int
    num_chunks: int
    total_characters: int
    chunks: List[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_name": self.entity_name,
            "num_records": self.num_records,
            "num_chunks": self.num_chunks,
            "total_characters": self.total_characters,
            "chunks": [
                {
                    "url": c.get("url"),
                    "title": c.get("title"),
                    "source": c.get("source"),
                    "query": c.get("query"),
                    "chunk_index": c.get("chunk_index"),
                    "total_chunks": c.get("total_chunks"),
                    "content_length": len(c.get("content", "")),
                    "content_preview": c.get("content", "")[:200] + "..." if len(c.get("content", "")) > 200 else c.get("content", ""),
                }
                for c in self.chunks
            ],
        }


@dataclass
class SemanticResult:
    """Capture of semantic decision output."""
    variant: str
    run_index: int = 0
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
    raw_response: Optional[str] = None
    success: bool = False
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "variant": self.variant,
            "run_index": self.run_index,
            "entity": self.entity,
            "entity_type": self.entity_type,
            "subtype": self.subtype,
            "country": self.country,
            "sector": self.sector,
            "status": self.status,
            "summary": self.summary,
            "relationships": self.relationships,
            "associations": self.associations,
            "uncertainties": self.uncertainties,
            "success": self.success,
            "error": self.error,
        }


# =============================================================================
# VARIANT CONFIGURATIONS
# =============================================================================

def create_variant_a_current_production() -> List[EvidenceRecord]:
    """Variant A: Current production evidence (authoritative + THIN)."""
    auth = create_authoritative_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    return auth + thin


def create_variant_b_substantive_only() -> List[EvidenceRecord]:
    """Variant B: Substantive evidence only (no THIN)."""
    return create_authoritative_sapp_evidence()


def create_variant_c_substantive_plus_thin() -> List[EvidenceRecord]:
    """Variant C: Substantive + THIN (explicit comparison with B)."""
    auth = create_authoritative_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    return auth + thin


def create_variant_d_deduplicated_vs_pre_step7() -> tuple:
    """Variant D: Compare deduplicated vs pre-Step-7 (with duplicates).
    
    Returns tuple of (deduplicated_evidence, pre_step7_evidence)
    """
    auth = create_authoritative_sapp_evidence()
    thin = create_thin_misleading_framework_evidence()
    duplicates = create_duplicate_sapp_evidence()
    
    # Deduplicated (current Step 7 behavior)
    deduped_evidence = deduplicate_evidence(auth + thin)
    
    # Pre-Step-7 (with duplicates)
    pre_step7_evidence = auth + thin + duplicates
    
    return deduped_evidence, pre_step7_evidence


def create_variant_e_authoritative_only() -> List[EvidenceRecord]:
    """Variant E: Authoritative SAPP evidence only (minimal baseline)."""
    # Use just the official SAPP source
    return create_authoritative_sapp_evidence()[:1]


# =============================================================================
# API AVAILABILITY CHECK
# =============================================================================

def check_mistral_api_available() -> tuple[bool, str]:
    """Check if Mistral API is available.
    
    Returns:
        Tuple of (available: bool, message: str)
    """
    import os
    from app import config
    
    api_key = (config.MISTRAL_API_KEY or os.getenv("MISTRAL_API_KEY") or "").strip()
    
    if not api_key:
        return False, "MISTRAL_API_KEY is empty or not configured"
    
    if api_key == "" or api_key == "your-api-key-here":
        return False, "MISTRAL_API_KEY contains placeholder value"
    
    return True, f"MISTRAL_API_KEY configured (model: {config.MISTRAL_MODEL})"


# =============================================================================
# EVIDENCE CAPTURE FUNCTIONS
# =============================================================================

def capture_evidence(entity_name: str, evidence_records: List[EvidenceRecord], apply_deduplication: bool = True) -> EvidenceCapture:
    """Capture evidence at the semantic boundary (before Mistral call).
    
    Args:
        entity_name: The entity name
        evidence_records: List of evidence records
        apply_deduplication: Whether to apply deduplication (default True, as production would)
    """
    # Apply deduplication (as production would)
    if apply_deduplication:
        deduped = deduplicate_evidence(evidence_records)
    else:
        deduped = list(evidence_records)
    
    # Create chunks (as production would)
    chunks = _create_evidence_chunks(deduped)
    
    # Calculate metrics
    total_chars = sum(len(c.get("content", "")) for c in chunks)
    
    return EvidenceCapture(
        entity_name=entity_name,
        num_records=len(deduped),
        num_chunks=len(chunks),
        total_characters=total_chars,
        chunks=chunks,
    )


async def call_mistral(entity_name: str, evidence_records: List[EvidenceRecord]) -> SemanticResult:
    """Call Mistral semantic enrichment and capture the result.
    
    Returns SemanticResult with the parsed output.
    """
    import httpx
    from app import config
    
    result = SemanticResult(
        variant="",
        success=False,
        error="API call not attempted",
    )
    
    # Check API availability
    available, message = check_mistral_api_available()
    if not available:
        result.error = message
        return result
    
    try:
        claims = await enrich_evidence_with_mistral(
            entity_name=entity_name,
            evidence_records=evidence_records,
            api_key=config.MISTRAL_API_KEY,
            model=config.MISTRAL_MODEL,
        )
        
        if not claims:
            result.error = "No claims returned from Mistral"
            return result
        
        # Parse claims to extract semantic decision
        # The enrich_evidence_with_mistral returns ResearchClaim objects
        # We need to extract the semantic decision from them
        result.success = True
        result.entity = entity_name
        
        # Extract information from claims
        for claim in claims:
            claim_text = getattr(claim, 'claim_text', None) or getattr(claim, 'claim', '')
            
            # Try to extract entity_type, subtype, etc. from claim text
            # This is a simplified extraction - the actual parsing would depend
            # on how Mistral formats its response
            if 'entity_type' in claim_text.lower():
                pass  # Would need actual response format
            
            if result.summary is None:
                result.summary = claim_text[:500] if len(claim_text) > 500 else claim_text
        
        # If we can't parse properly, store raw claims
        if result.entity_type is None:
            result.raw_response = str([str(c) for c in claims[:3]])  # First 3 claims
        
    except Exception as e:
        result.error = f"Mistral API call failed: {str(e)}"
        import traceback
        result.raw_response = traceback.format_exc()
    
    return result


# =============================================================================
# MAIN EXPERIMENT
# =============================================================================

async def run_sapp_experiment() -> Dict[str, Any]:
    """Run the complete SAPP reproduction experiment."""
    
    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "experiment": "STEP 8 - SAPP Semantic Decision Reproduction",
        "api_available": False,
        "api_message": "",
        "variants": [],
        "conclusion": "",
    }
    
    # Check API availability
    available, message = check_mistral_api_available()
    report["api_available"] = available
    report["api_message"] = message
    
    if not available:
        report["conclusion"] = "External semantic model unavailable. Model-behavior experiment not executed."
        return report
    
    # Define variants
    variants_config = [
        ("A_current_production", create_variant_a_current_production(), True),
        ("B_substantive_only", create_variant_b_substantive_only(), True),
        ("C_substantive_plus_thin", create_variant_c_substantive_plus_thin(), True),
        ("E_authoritative_only", create_variant_e_authoritative_only(), True),
    ]
    
    # Variant D is special (comparison)
    deduped_d, pre_step7_d = create_variant_d_deduplicated_vs_pre_step7()
    variants_config.append(("D_deduplicated", deduped_d, True))
    variants_config.append(("D_pre_step7_with_duplicates", pre_step7_d, False))
    
    # Run each variant
    for variant_tuple in variants_config:
        if len(variant_tuple) == 3:
            variant_name, evidence_records, apply_dedup = variant_tuple
        else:
            # Backward compatibility
            variant_name, evidence_records = variant_tuple
            apply_dedup = True
        variant_report: Dict[str, Any] = {
            "name": variant_name,
            "evidence_capture": None,
            "runs": [],
        }
        
        # Capture evidence (before Mistral)
        evidence_capture = capture_evidence("SAPP", evidence_records, apply_deduplication=apply_dedup)
        variant_report["evidence_capture"] = evidence_capture.to_dict()
        
        # Run Mistral (if available)
        # Limit to 1 run per variant due to API costs
        # In production, you might run 3 times for repeatability
        for run_index in range(1):  # Change to 3 for full repeatability
            semantic_result = await call_mistral("SAPP", evidence_records)
            semantic_result.variant = variant_name
            semantic_result.run_index = run_index
            variant_report["runs"].append(semantic_result.to_dict())
        
        report["variants"].append(variant_report)
    
    return report


# =============================================================================
# SYNCHRONOUS WRAPPER FOR TESTING
# =============================================================================

def run_experiment_sync() -> Dict[str, Any]:
    """Run the experiment synchronously for testing."""
    return asyncio.run(run_sapp_experiment())


# =============================================================================
# TEST: API Availability
# =============================================================================

class TestAPIAvailability:
    """Test Mistral API availability."""
    
    def test_api_check_returns_result(self):
        """Test that API check returns a valid result."""
        available, message = check_mistral_api_available()
        
        assert isinstance(available, bool)
        assert isinstance(message, str)
        assert len(message) > 0
        
        print(f"API Available: {available}")
        print(f"Message: {message}")


# =============================================================================
# TEST: Evidence Capture
# =============================================================================

class TestEvidenceCapture:
    """Test evidence capture without calling Mistral."""
    
    def test_capture_variant_a(self):
        """Test evidence capture for Variant A."""
        evidence = create_variant_a_current_production()
        capture = capture_evidence("SAPP", evidence)
        
        assert capture.entity_name == "SAPP"
        assert capture.num_records > 0
        assert capture.num_chunks > 0
        assert capture.total_characters > 0
        
        print(f"Variant A: {capture.num_records} records, {capture.num_chunks} chunks, {capture.total_characters} chars")
    
    def test_capture_variant_b(self):
        """Test evidence capture for Variant B."""
        evidence = create_variant_b_substantive_only()
        capture = capture_evidence("SAPP", evidence)
        
        assert capture.entity_name == "SAPP"
        assert capture.num_records > 0
        
        print(f"Variant B: {capture.num_records} records, {capture.num_chunks} chunks, {capture.total_characters} chars")
    
    def test_capture_variant_d_comparison(self):
        """Test evidence capture for Variant D comparison."""
        deduped, pre_step7 = create_variant_d_deduplicated_vs_pre_step7()
        
        capture_deduped = capture_evidence("SAPP", deduped, apply_deduplication=True)
        capture_pre = capture_evidence("SAPP", pre_step7, apply_deduplication=False)
        
        # Deduplicated should have fewer records
        assert capture_deduped.num_records < capture_pre.num_records
        
        print(f"Variant D deduped: {capture_deduped.num_records} records")
        print(f"Variant D pre-step7: {capture_pre.num_records} records")


# =============================================================================
# TEST: Report Generation
# =============================================================================

class TestReportGeneration:
    """Test report generation without API calls."""
    
    def test_report_structure(self):
        """Test that report has correct structure."""
        # Run without API (will detect unavailability)
        report = run_experiment_sync()
        
        assert "timestamp" in report
        assert "experiment" in report
        assert "api_available" in report
        assert "api_message" in report
        assert "variants" in report
        assert "conclusion" in report
        
        # Check variants structure
        if report["variants"]:
            variant = report["variants"][0]
            assert "name" in variant
            assert "evidence_capture" in variant
            assert "runs" in variant
        
        print(f"Report generated: API available={report['api_available']}")


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, '/workspace/github__tmakiriyado1-arch__atis-node-builder')
    
    print("=" * 70)
    print("STEP 8: SAPP Semantic Decision Reproduction")
    print("=" * 70)
    print()
    
    # Check API
    available, message = check_mistral_api_available()
    print(f"Mistral API Available: {available}")
    print(f"Message: {message}")
    print()
    
    if not available:
        print("External semantic model unavailable.")
        print("Model-behavior experiment not executed.")
        print()
        print("Fixture-level results from Steps 5-7 remain valid but")
        print("must not be presented as model results.")
        
        # Still run evidence capture tests
        print()
        print("Running evidence capture tests (no API calls)...")
        
        t_capture = TestEvidenceCapture()
        t_capture.test_capture_variant_a()
        t_capture.test_capture_variant_b()
        t_capture.test_capture_variant_d_comparison()
        
        t_report = TestReportGeneration()
        t_report.test_report_structure()
        
        print()
        print("Evidence capture tests completed successfully.")
    else:
        print("Mistral API is available. Running full experiment...")
        report = run_experiment_sync()
        
        # Print summary
        print()
        print("=" * 70)
        print("EXPERIMENT RESULTS")
        print("=" * 70)
        print(f"API Available: {report['api_available']}")
        print(f"Conclusion: {report['conclusion']}")
        
        if report['variants']:
            for variant in report['variants']:
                name = variant['name']
                capture = variant.get('evidence_capture', {})
                print(f"\n{variant['name']}:")
                print(f"  Records: {capture.get('num_records', 0)}")
                print(f"  Chunks: {capture.get('num_chunks', 0)}")
                print(f"  Characters: {capture.get('total_characters', 0)}")
                
                for run in variant.get('runs', []):
                    print(f"  Run {run.get('run_index', 0)}: entity_type={run.get('entity_type')}, success={run.get('success')}")
                    if run.get('error'):
                        print(f"    Error: {run.get('error')[:100]}")
