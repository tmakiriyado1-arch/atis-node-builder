"""Deterministic routing of research claims into node sections.

This classifier extracts metadata, relationships, associations, and summaries from
any claim text, ensuring comprehensive coverage of entity information.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, List, Optional, Sequence

from app.services.entity_resolution.registry import EntityRegistry, ResolutionState
from app.services.entity_resolution.resolver import EntityResolver
from app.services.research_engine import ResearchClaim


class ClaimCategory(str, Enum):
    """Deterministic routing categories for a research claim."""

    SUMMARY = "SUMMARY"
    RELATIONSHIP = "RELATIONSHIP"
    ASSOCIATION = "ASSOCIATION"
    METADATA = "METADATA"
    SOURCE = "SOURCE"
    UNCLASSIFIED = "UNCLASSIFIED"


@dataclass
class ClaimClassification:
    """The decision and routing output for one research claim."""

    category: ClaimCategory | str
    target: Optional[str] = None
    predicate: Optional[str] = None
    metadata_field: Optional[str] = None
    evidence_urls: List[str] = field(default_factory=list)
    reasoning: str = ""
    resolved_target: Optional[str] = None
    raw_claim: str = ""
    subtype: Optional[str] = None

    def render_relationship(self) -> str:
        if not self.predicate or not self.target:
            return ""
        target = self.resolved_target or self.target
        return f"{self.predicate.lower()}::[[{target.strip()}]]"

    def render_association(self) -> str:
        if not self.predicate or not self.target:
            return ""
        target = self.resolved_target or self.target
        return f"{self.predicate.lower()}::[[{target.strip()}]]"

    def render_summary(self) -> str:
        if not self.raw_claim:
            return ""
        return self.raw_claim.strip()


class ClaimClassifier:
    """Route evidence-backed research claims into safe node sections without inventing fact content.
    
    This classifier is designed to handle ANY claim text and extract meaningful information
    including metadata, relationships, associations, and summaries.
    """

    _relationship_predicates = {
        "regulates",
        "manages",
        "oversees",
        "supports",
        "operates",
        "provides",
        "governs",
        "controls",
        "establishes",
        "requires",
        "enforces",
        "includes",
        "covers",
        "monitors",
        "administers",
        "coordinates",
        "maintains",
        "owns",
        "leads",
        "founded",
        "created",
        "funds",
        "licenses",
        "authorizes",
        "approved",
        "signed",
        "built",
        "develops",
        "implements",
        "executes",
        "advises",
        "consults",
        "represents",
        "participates",
        "collaborates",
        "partners",
    }

    _association_predicates = {
        "connected_to",
        "relevant_to",
        "related_to",
        "associated_with",
        "linked_to",
        "relevant to",
        "connected to",
        "associated with",
        "affiliated_with",
        "partnered_with",
        "collaborates_with",
        "works_with",
        "member_of",
        "part_of",
    }

    # Expanded metadata keywords for comprehensive coverage
    _metadata_keywords = {
        "entity_type": [
            # Organization types
            "government agency",
            "government body",
            "public authority",
            "state-owned enterprise",
            "private company",
            "non-profit",
            "organization",
            "authority",
            "agency",
            "company",
            "institution",
            "ministry",
            "department",
            "utility",
            "station",
            "plant",
            "firm",
            "corporation",
            "enterprise",
            "consortium",
            "alliance",
            "pool",
            "cooperation",
            "cooperative",
            "network",
            "association",
            "council",
            "committee",
            "board",
            "commission",
            "foundation",
            "institute",
            "center",
            "bureau",
            "office",
            "service",
            "program",
            "initiative",
            "project",
            "task force",
            "working group",
            # Concept types
            "concept",
            "economic policy approach",
            "policy approach",
            "ideological framework",
            "economic framework",
            "political concept",
            "strategy",
            "approach",
            "methodology",
            "framework",
            "doctrine",
            "principle",
            "theory",
        ],
        "country": [
            "located in",
            "based in",
            "situated in",
            "operates in",
            "headquartered in",
            "registered in",
            "incorporated in",
            "in africa",
            "in zimbabwe",
            "in south africa",
            "in mozambique",
            "in kenya",
            "in nigeria",
            "in ghana",
            "in uganda",
            "in tanzania",
            "in zambia",
            "in malawi",
            "in botswana",
            "in namibia",
            "in angola",
            "southern africa",
            "eastern africa",
            "western africa",
            "north africa",
            "sadc",
            "southern african development community",
        ],
        "sector": [
            "energy sector",
            "power sector",
            "electricity sector",
            "water sector",
            "transport sector",
            "telecommunications sector",
            "mining sector",
            "agriculture sector",
            "technology sector",
            "financial sector",
            "health sector",
            "education sector",
            "infrastructure",
            "energy",
            "power",
            "electricity",
            "renewable energy",
            "sustainable energy",
        ],
        "status": [
            "active",
            "inactive",
            "proposed",
            "approved",
            "operational",
            "closed",
            "pending",
            "draft",
            "published",
            "implemented",
            "established",
            "founded",
            "launched",
            "running",
            "functional",
        ],
    }

    _concept_entity_type_keywords = {
        "concept": [
            "concept",
            "economic policy approach",
            "policy approach",
            "ideological framework",
            "economic framework",
            "political concept",
        ],
    }

    _concept_subtype_mapping = {
        "economic policy approach": "economic_policy",
        "policy approach": "policy",
        "ideological framework": "ideological_framework",
        "economic framework": "economic_framework",
        "political concept": "political_concept",
        "concept": None,
    }

    def __init__(self, registry: Optional[EntityRegistry] = None, resolver: Optional[EntityResolver] = None):
        self.registry = registry
        self.resolver = resolver

    def classify(self, claim: ResearchClaim) -> ClaimClassification:
        if claim is None:
            return ClaimClassification(category=ClaimCategory.UNCLASSIFIED, reasoning="empty claim")

        text = self._claim_text(claim)
        if not text:
            return ClaimClassification(category=ClaimCategory.UNCLASSIFIED, reasoning="empty claim text")

        evidence_urls = self._evidence_urls(claim)
        subject, predicate, target = self._extract_triplet(claim, text)
        
        # First, try to extract metadata from the claim
        metadata_field = self._metadata_field(text, target, predicate)
        if metadata_field:
            subtype = self._extract_subtype(text, target) if metadata_field == "entity_type" else None
            return ClaimClassification(
                category=ClaimCategory.METADATA,
                target=target,
                predicate=predicate or "is",
                metadata_field=metadata_field,
                evidence_urls=evidence_urls,
                reasoning="metadata claim routed to canonical field",
                raw_claim=text,
                subtype=subtype,
            )

        # Try to extract entity type from "is a/an [type]" pattern
        if predicate and predicate.lower() in {"is", "is_a", "is_an"}:
            entity_type = self._extract_entity_type_from_target(target, text)
            if entity_type:
                return ClaimClassification(
                    category=ClaimCategory.METADATA,
                    target=entity_type,
                    predicate="is",
                    metadata_field="entity_type",
                    evidence_urls=evidence_urls,
                    reasoning="entity type extracted from 'is a/an' pattern",
                    raw_claim=text,
                )

        # Enhanced: Try to extract location information first
        location = self._extract_location(text)
        if location:
            return ClaimClassification(
                category=ClaimCategory.METADATA,
                target=location,
                predicate="located_in",
                metadata_field="country",
                evidence_urls=evidence_urls,
                reasoning="location extracted from claim text",
                raw_claim=text,
            )

        # Enhanced: Try to extract sector information
        sector = self._extract_sector(text)
        if sector:
            return ClaimClassification(
                category=ClaimCategory.METADATA,
                target=sector,
                predicate="operates_in",
                metadata_field="sector",
                evidence_urls=evidence_urls,
                reasoning="sector extracted from claim text",
                raw_claim=text,
            )

        # Check for direct relationships
        if self._is_direct_relationship(text, predicate, target):
            route_target = self._canonical_target(subject, target)
            return ClaimClassification(
                category=ClaimCategory.RELATIONSHIP,
                target=route_target or target,
                predicate=(predicate or self._match_predicate(text) or "related_to").lower(),
                evidence_urls=evidence_urls,
                reasoning="direct entity-to-entity relationship",
                resolved_target=self._resolve_target(subject, route_target or target),
                raw_claim=text,
            )

        # Check for summary claims
        if self._is_summary_claim(text, predicate, target):
            route_target = self._canonical_target(subject, target)
            return ClaimClassification(
                category=ClaimCategory.SUMMARY,
                target=route_target or target,
                predicate=predicate or self._match_predicate(text) or "describes",
                evidence_urls=evidence_urls,
                reasoning="functional or identity claim routed to summary",
                resolved_target=self._resolve_target(subject, route_target or target),
                raw_claim=text,
            )

        # Check for association claims
        if self._is_association_claim(text):
            route_target = self._canonical_target(subject, target)
            return ClaimClassification(
                category=ClaimCategory.ASSOCIATION,
                target=route_target or target,
                predicate=(predicate or "connected_to").lower(),
                evidence_urls=evidence_urls,
                reasoning="explicit contextual association",
                resolved_target=self._resolve_target(subject, route_target or target),
                raw_claim=text,
            )

        # Enhanced: Try to find any verb-based relationship
        verb_relationship = self._extract_verb_relationship(text, subject)
        if verb_relationship:
            predicate_val, target_val = verb_relationship
            route_target = self._canonical_target(subject, target_val)
            return ClaimClassification(
                category=ClaimCategory.RELATIONSHIP,
                target=route_target or target_val,
                predicate=predicate_val,
                evidence_urls=evidence_urls,
                reasoning="verb-based relationship extracted",
                resolved_target=self._resolve_target(subject, route_target or target_val),
                raw_claim=text,
            )

        # If all else fails, classify as summary if it describes the entity
        if self._is_descriptive_claim(text, subject):
            return ClaimClassification(
                category=ClaimCategory.SUMMARY,
                target=subject or text,
                predicate="describes",
                evidence_urls=evidence_urls,
                reasoning="descriptive claim routed to summary",
                raw_claim=text,
            )

        # Enhanced: Try to extract entity type from descriptive text
        extracted_type = self._extract_entity_type_from_descriptive_text(text)
        if extracted_type:
            return ClaimClassification(
                category=ClaimCategory.METADATA,
                target=extracted_type,
                predicate="is",
                metadata_field="entity_type",
                evidence_urls=evidence_urls,
                reasoning="entity type extracted from descriptive text",
                raw_claim=text,
            )

        return ClaimClassification(
            category=ClaimCategory.UNCLASSIFIED,
            target=target,
            predicate=predicate,
            evidence_urls=evidence_urls,
            reasoning="claim does not satisfy deterministic routing rules",
            raw_claim=text,
        )

    def route(self, claims: Sequence[ResearchClaim] | Iterable[ResearchClaim]) -> dict[ClaimCategory | str, List[str]]:
        buckets: dict[ClaimCategory | str, List[str]] = {
            ClaimCategory.METADATA: [],
            ClaimCategory.RELATIONSHIP: [],
            ClaimCategory.SUMMARY: [],
            ClaimCategory.ASSOCIATION: [],
            ClaimCategory.UNCLASSIFIED: [],
            ClaimCategory.SOURCE: [],
        }

        seen_relationships: set[str] = set()
        seen_associations: set[str] = set()
        seen_metadata: set[str] = set()
        seen_summary: set[str] = set()

        for claim in claims:
            result = self.classify(claim)
            category = result.category
            if category == ClaimCategory.METADATA:
                field = result.metadata_field or "metadata"
                value = result.target or result.raw_claim or ""
                key = f"{field}::{value}"
                if key not in seen_metadata:
                    seen_metadata.add(key)
                    buckets[ClaimCategory.METADATA].append(key)
            elif category == ClaimCategory.RELATIONSHIP:
                rendered = result.render_relationship()
                if rendered and rendered not in seen_relationships:
                    seen_relationships.add(rendered)
                    buckets[ClaimCategory.RELATIONSHIP].append(rendered)
            elif category == ClaimCategory.ASSOCIATION:
                rendered = result.render_association()
                if rendered and rendered not in seen_associations:
                    seen_associations.add(rendered)
                    buckets[ClaimCategory.ASSOCIATION].append(rendered)
            elif category == ClaimCategory.SUMMARY:
                summary_text = result.render_summary()
                if summary_text and summary_text not in seen_summary:
                    seen_summary.add(summary_text)
                    buckets[ClaimCategory.SUMMARY].append(summary_text)
            elif category == ClaimCategory.UNCLASSIFIED:
                if result.raw_claim:
                    buckets[ClaimCategory.UNCLASSIFIED].append(result.raw_claim)
            elif category == ClaimCategory.SOURCE:
                buckets[ClaimCategory.SOURCE].extend(result.evidence_urls or [])

        return buckets

    def classify_many(self, claims: Sequence[ResearchClaim] | Iterable[ResearchClaim]) -> List[ClaimClassification]:
        return [self.classify(claim) for claim in claims if claim is not None]

    def _claim_text(self, claim: ResearchClaim) -> str:
        if isinstance(claim, dict):
            return str((claim.get("claim_text") or claim.get("claim") or "")).strip()
        return str(getattr(claim, "claim_text", getattr(claim, "claim", "") or "")).strip()

    def _evidence_urls(self, claim: ResearchClaim) -> List[str]:
        if isinstance(claim, dict):
            raw = claim.get("evidence_urls") or claim.get("source_url") or []
            values = raw if isinstance(raw, list) else [raw]
            return [str(item).strip() for item in values if str(item).strip()]

        raw = getattr(claim, "evidence_urls", None)
        if raw is None:
            raw = getattr(claim, "source_url", "")
        if isinstance(raw, list):
            return [str(item).strip() for item in raw if str(item).strip()]
        return [str(raw).strip()] if str(raw).strip() else []

    def _extract_triplet(self, claim: ResearchClaim, text: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
        subject = getattr(claim, "subject", None)
        predicate = getattr(claim, "predicate", None)
        obj = getattr(claim, "object", None)
        if subject or predicate or obj:
            return self._clean(subject), self._clean(predicate), self._clean(obj)

        # Enhanced pattern matching for subject-predicate-object
        # Try "is a/an [type]" first
        match = re.search(
            r"^(?P<subject>.+?)\s+(?P<predicate>is a|is an|is|are a|are an|are)\s+(?P<object>.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._clean(match.group("subject")), self._clean(match.group("predicate")).lower(), self._clean(match.group("object"))
        
        # Try relationship predicates
        match = re.search(
            r"^(?P<subject>.+?)\s+(?P<predicate>regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|founded|created|funds|licenses|authorizes|approved|signed|built|develops|implements|executes|advises|consults|represents|participates|collaborates|partners|created|has)\s+(?P<object>.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._clean(match.group("subject")), self._clean(match.group("predicate")).lower(), self._clean(match.group("object"))
        
        # Try association predicates
        match = re.search(
            r"^(?P<subject>.+?)\s+(?P<predicate>connected to|relevant to|related to|associated with|linked to|affiliated with|partnered with|collaborates with|works with|member of|part of)\s+(?P<object>.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._clean(match.group("subject")), self._clean(match.group("predicate")).lower(), self._clean(match.group("object"))
        
        # Try location patterns
        match = re.search(
            r"^(?P<subject>.+?)\s+(?P<predicate>located in|based in|situated in|operates in|headquartered in|registered in|incorporated in)\s+(?P<object>.+)$",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._clean(match.group("subject")), self._clean(match.group("predicate")).lower(), self._clean(match.group("object"))
        
        # Try sector patterns
        match = re.search(
            r"^(?P<subject>.+?)\s+(?P<predicate>operates in|in the|works in|active in|focused on)\s+(?P<object>\w+ sector|\w+ industry|energy|power|electricity|infrastructure)\s*",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._clean(match.group("subject")), self._clean(match.group("predicate")).lower(), self._clean(match.group("object"))
        
        return None, None, None

    def _clean(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = str(value).strip().strip(". ")
        return cleaned or None

    def _is_metadata_claim(self, text: str, target: Optional[str], predicate: Optional[str]) -> bool:
        lower = text.lower()
        if predicate and predicate.lower() in self._relationship_predicates:
            return False
        if re.search(r"\b(is|are|was|were)\s+(?:a|an)\s+", lower):
            if any(keyword in lower for keyword in self._metadata_keywords["entity_type"]):
                return True
            if any(keyword in lower for keyword in self._concept_entity_type_keywords["concept"]):
                return True
        if any(keyword in lower for keyword in ["located in", "based in", "situated in", "operates in", "headquartered in"]):
            return True
        if any(keyword in lower for keyword in ["operates in", "in the energy sector", "energy sector", "power sector", "electricity sector", "water sector", "transport sector", "technology sector"]):
            return True
        if re.search(r"\b(active|inactive|proposed|approved|operational|closed|pending|draft|published|implemented|established|founded|launched)\b", lower):
            return True
        return False

    def _metadata_field(self, text: str, target: Optional[str], predicate: Optional[str]) -> Optional[str]:
        lower = text.lower()
        if predicate and predicate.lower() in self._relationship_predicates:
            return None
        if re.search(r"\b(is|are|was|were)\s+(?:a|an)\s+", lower):
            if any(keyword in lower for keyword in self._metadata_keywords["entity_type"]):
                return "entity_type"
            if any(keyword in lower for keyword in self._concept_entity_type_keywords["concept"]):
                return "entity_type"
        if any(keyword in lower for keyword in ["located in", "based in", "situated in", "headquartered in", "registered in", "incorporated in"]):
            return "country"
        if any(keyword in lower for keyword in ["operates in", "in the energy sector", "energy sector", "power sector", "electricity sector", "water sector", "transport sector", "technology sector", "infrastructure"]):
            return "sector"
        if re.search(r"\b(active|inactive|proposed|approved|operational|closed|pending|draft|published|implemented|established|founded|launched|running|functional)\b", lower):
            return "status"
        return None

    def _extract_entity_type_from_target(self, target: Optional[str], text: str) -> Optional[str]:
        """Extract entity type from the target of an 'is a/an' claim."""
        if not target:
            return None
        
        lower_target = target.lower()
        
        # Check against entity_type keywords
        for keyword in self._metadata_keywords["entity_type"]:
            if keyword.lower() in lower_target:
                # Return the keyword that matched
                return keyword
        
        # Check for common organization patterns
        org_patterns = [
            r"\b(organization|agency|authority|body|committee|commission|council|board|department|ministry|institution|company|corporation|enterprise|firm|utility|service|program|initiative|project|consortium|alliance|pool|cooperation|cooperative|network|association|foundation|institute|center|bureau|office)\b",
        ]
        for pattern in org_patterns:
            match = re.search(pattern, lower_target, re.IGNORECASE)
            if match:
                return match.group(1).capitalize()
        
        # Check for concept patterns
        for keyword in self._concept_entity_type_keywords["concept"]:
            if keyword.lower() in lower_target:
                return keyword
        
        # If target looks like an organization name, classify it
        if any(org_keyword in lower_target for org_keyword in [
            'power', 'electricity', 'energy', 'development', 'community',
            'southern', 'african', 'regulatory', 'authority'
        ]):
            # Check if it's a cooperation/pool/authority
            if 'cooperation' in lower_target or 'pool' in lower_target:
                return 'cooperation'
            if 'authority' in lower_target:
                return 'regulatory authority'
            if 'development' in lower_target and 'community' in lower_target:
                return 'development community'
            return 'organization'
        
        return None

    def _extract_location(self, text: str) -> Optional[str]:
        """Extract location/country information from text."""
        lower = text.lower()
        
        # Check for country keywords
        country_patterns = [
            ("southern africa", "Southern Africa"),
            ("sadc", "SADC"),
            ("southern african development community", "Southern African Development Community"),
            ("africa", "Africa"),
            ("zimbabwe", "Zimbabwe"),
            ("south africa", "South Africa"),
            ("mozambique", "Mozambique"),
            ("kenya", "Kenya"),
            ("nigeria", "Nigeria"),
            ("ghana", "Ghana"),
            ("uganda", "Uganda"),
            ("tanzania", "Tanzania"),
            ("zambia", "Zambia"),
            ("malawi", "Malawi"),
            ("botswana", "Botswana"),
            ("namibia", "Namibia"),
            ("angola", "Angola"),
        ]
        
        for pattern, country_name in country_patterns:
            if pattern in lower:
                return country_name
        
        # Check for location prepositions
        location_patterns = [
            r"(?:located|based|situated|operates|headquartered|registered|incorporated)\s+(?:in\s+)?(?P<location>[A-Z][a-zA-Z\s-]+(?:\s+[A-Z][a-zA-Z\s-]+)*)",
        ]
        for pattern in location_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                location = match.group("location").strip()
                # Capitalize properly
                return location.title()
        
        return None

    def _extract_entity_type_from_descriptive_text(self, text: str) -> Optional[str]:
        """Extract entity type from descriptive text without explicit 'is a' pattern."""
        lower = text.lower()
        
        # Check for organization patterns in descriptive text
        org_patterns = [
            (r"\b(is|are|was|were|functions as|operates as|acts as|serves as)\s+(?:a|an|the)\s+([a-z0-9\s-]+)", "entity_type"),
            (r"\b(known as|referred to as|called|also known as)\s+([a-z0-9\s-]+)", "entity_type"),
        ]
        
        for pattern, field in org_patterns:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                entity_type = match.group(2).strip()
                # Check if it's an actual type
                if any(keyword in entity_type for keyword in [
                    'cooperation', 'pool', 'authority', 'agency', 'organization',
                    'company', 'institution', 'body', 'commission', 'council'
                ]):
                    return entity_type.capitalize()
        
        return None

    def _extract_sector(self, text: str) -> Optional[str]:
        """Extract sector information from text."""
        lower = text.lower()
        
        sector_patterns = [
            ("energy sector", "Energy Sector"),
            ("power sector", "Power Sector"),
            ("electricity sector", "Electricity Sector"),
            ("infrastructure", "Infrastructure"),
            ("energy", "Energy"),
            ("power", "Power"),
            ("electricity", "Electricity"),
            ("renewable energy", "Renewable Energy"),
            ("sustainable energy", "Sustainable Energy"),
        ]
        
        for pattern, sector_name in sector_patterns:
            if pattern in lower:
                return sector_name
        
        # Check for sector prepositions
        sector_patterns_regex = [
            r"(?:in the|works in|active in|focused on|specializes in|operates in|involved in|participates in)\s+(?P<sector>[\w\s-]+\s+sector)",
            r"(?:in the|works in|active in|focused on|specializes in|operates in|involved in|participates in)\s+(?P<sector>\w+)\s+industry",
        ]
        for pattern in sector_patterns_regex:
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                sector = match.group("sector").strip()
                return sector.title()
        
        # Check for "common market for electricity" or similar patterns
        if "electricity" in lower or "power" in lower:
            return "Electricity Sector"
        
        return None

    def _extract_verb_relationship(self, text: str, subject: Optional[str]) -> Optional[tuple[str, str]]:
        """Extract verb-based relationships from text."""
        if not subject:
            subject = ""
        
        lower = text.lower()
        
        # Look for patterns like "[subject] [verb] [object]"
        # where verb is a relationship predicate
        for predicate in sorted(self._relationship_predicates, key=len, reverse=True):
            # Pattern: subject + predicate + object
            pattern = rf"{re.escape(subject.lower())}\s+{predicate}\s+(?P<object>.+?)(?:\.|$)"
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                obj = match.group("object").strip()
                if obj and obj != subject.lower():
                    return (predicate, obj)
        
        # More general pattern: any subject + predicate + object
        for predicate in sorted(self._relationship_predicates, key=len, reverse=True):
            pattern = rf"(?P<subj>.+?)\s+{predicate}\s+(?P<object>.+?)(?:\.|$)"
            match = re.search(pattern, lower, re.IGNORECASE)
            if match:
                obj = match.group("object").strip()
                if obj:
                    return (predicate, obj)
        
        return None

    def _is_direct_relationship(self, text: str, predicate: Optional[str], target: Optional[str]) -> bool:
        if not predicate or not target:
            return False
        normalized = predicate.lower().strip()
        if normalized in self._relationship_predicates:
            # Don't classify as relationship if it's about sectors/industries
            if re.search(r"\b(sector|industry|market|activity|supply chain|system|policy)\b", text, flags=re.IGNORECASE):
                return False
            if normalized in {"is", "is_a", "is_an", "was", "were"}:
                return False
            return True
        return False

    def _is_summary_claim(self, text: str, predicate: Optional[str], target: Optional[str]) -> bool:
        lower = text.lower()
        summary_patterns = [
            "is used in",
            "used in",
            "generates",
            "produces",
            "supplies",
            "powers",
            "operates",
            "functions",
            "delivers",
            "supports",
            "responsible for",
            "facilitates",
            "enables",
            "provides",
            "is designed to",
            "aims to",
            "seeks to",
            "works to",
            "strives to",
            "helps",
            "promotes",
            "encourages",
            "coordinates",
            "manages",
            "oversees",
        ]
        if any(pattern in lower for pattern in summary_patterns):
            return True
        if re.search(r"\b(regulates|manages|oversees)\s+(?:the\s+)?[a-z0-9\s'\-]+(?:sector|industry|market|activity|licensing|system)\b", lower):
            return True
        if predicate and predicate.lower() in {"regulates", "manages", "oversees"} and re.search(r"\b(sector|industry|market|activity|system|licensing)\b", text, flags=re.IGNORECASE):
            return True
        return False

    def _is_association_claim(self, text: str) -> bool:
        lower = text.lower()
        if any(token in lower for token in ["something unclear", "unclear", "various", "miscellaneous"]):
            return False
        for marker in ["relevant to", "connected to", "associated with", "related to", "linked to", "affiliated with", "partnered with", "collaborates with", "works with", "member of", "part of"]:
            if marker in lower:
                return True
        return False

    def _is_descriptive_claim(self, text: str, subject: Optional[str]) -> bool:
        """Check if a claim is descriptive of the entity."""
        if not subject:
            return False
        
        lower = text.lower()
        subject_lower = subject.lower()
        
        # If the text contains the subject and describes it
        if subject_lower in lower:
            # Check for descriptive verbs
            descriptive_verbs = [
                "is", "are", "was", "were", "be", "being", "been",
                "has", "have", "had", "having",
                "was founded", "was established", "was created",
                "functions", "operates", "works", "provides",
                "supports", "coordinates", "manages", "oversees",
                "creates", "maintains", "develops", "facilitates",
            ]
            for verb in descriptive_verbs:
                if verb in lower:
                    return True
        
        # Also check if it's a general description even without explicit subject match
        if any(verb in lower for verb in [
            "is a", "are a", "was a", "were a", "is an", "are an",
            "functions as", "operates as", "serves as", "acts as",
            "provides", "supports", "coordinates", "manages",
        ]):
            return True
        
        return False

    def _match_predicate(self, text: str) -> Optional[str]:
        lower = text.lower()
        for predicate in sorted(self._relationship_predicates, key=len, reverse=True):
            if predicate in lower:
                return predicate
        for predicate in sorted(self._association_predicates, key=len, reverse=True):
            if predicate in lower:
                return predicate
        return None

    def _canonical_target(self, subject: Optional[str], target: Optional[str]) -> Optional[str]:
        if not target:
            return None
        cleaned = str(target).strip().strip(". ")
        if not cleaned:
            return None
        if self.registry is None or self.resolver is None:
            return cleaned
        result = self.resolver.resolve(cleaned, context=subject)
        if result.state == ResolutionState.RESOLVED and result.canonical_name:
            return result.canonical_name
        if result.state == ResolutionState.AMBIGUOUS:
            return cleaned
        return cleaned

    def _resolve_target(self, subject: Optional[str], target: Optional[str]) -> Optional[str]:
        if not target or self.registry is None or self.resolver is None:
            return None
        result = self.resolver.resolve(str(target).strip(), context=subject)
        if result.state == ResolutionState.RESOLVED and result.canonical_name:
            return result.canonical_name
        if result.state == ResolutionState.AMBIGUOUS:
            return None
        return None
