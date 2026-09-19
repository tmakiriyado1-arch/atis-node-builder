"""Deterministic routing of research claims into node sections."""
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
    """Route evidence-backed research claims into safe node sections without inventing fact content."""

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
    }

    _metadata_keywords = {
        "entity_type": [
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
        ],
        "country": [
            "located in",
            "based in",
            "situated in",
            "operates in",
            "in zimbabwe",
            "in south africa",
            "in mozambique",
            "in kenya",
            "in nigeria",
        ],
        "sector": [
            "energy sector",
            "water sector",
            "transport sector",
            "telecommunications sector",
            "mining sector",
            "agriculture sector",
            "technology sector",
        ],
        "status": [
            "active",
            "inactive",
            "proposed",
            "approved",
            "operational",
            "closed",
            "pending",
        ],
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
        metadata_field = self._metadata_field(text, target, predicate)
        if metadata_field:
            return ClaimClassification(
                category=ClaimCategory.METADATA,
                target=target,
                predicate=predicate or "is",
                metadata_field=metadata_field,
                evidence_urls=evidence_urls,
                reasoning="metadata claim routed to canonical field",
                raw_claim=text,
            )

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

        for claim in claims:
            result = self.classify(claim)
            category = result.category
            if category == ClaimCategory.METADATA:
                field = result.metadata_field or "metadata"
                buckets[ClaimCategory.METADATA].append(f"{field}::{result.target or ''}".strip())
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
                if summary_text:
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

        match = re.search(
            r"^(?P<subject>.+?)\s+(?P<predicate>is a|is an|is|regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|connected to|relevant to|associated with|related to|uses|generates|produces|powers|occupies|located in|based in|situated in|is used in)\s+(?P<object>.+)$",
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
        if predicate and predicate.lower() in {"regulates", "manages", "oversees", "supports", "provides", "governs", "controls", "establishes", "requires", "enforces", "includes", "covers", "monitors", "administers", "coordinates", "maintains", "owns", "leads"}:
            return False
        if re.search(r"\b(is|are)\s+(?:a|an)\s+", lower):
            if any(keyword in lower for keyword in self._metadata_keywords["entity_type"]):
                return True
        if any(keyword in lower for keyword in ["located in", "based in", "situated in", "operates in"]):
            return True
        if any(keyword in lower for keyword in ["in the energy sector", "energy sector", "water sector", "transport sector", "technology sector"]):
            return True
        if re.search(r"\b(active|inactive|proposed|approved|operational|closed|pending)\b", lower):
            return True
        return False

    def _metadata_field(self, text: str, target: Optional[str], predicate: Optional[str]) -> Optional[str]:
        lower = text.lower()
        if predicate and predicate.lower() in {"regulates", "manages", "oversees", "supports", "provides", "governs", "controls", "establishes", "requires", "enforces", "includes", "covers", "monitors", "administers", "coordinates", "maintains", "owns", "leads"}:
            return None
        if re.search(r"\b(is|are)\s+(?:a|an)\s+", lower) and any(keyword in lower for keyword in self._metadata_keywords["entity_type"]):
            return "entity_type"
        if any(keyword in lower for keyword in ["located in", "based in", "situated in"]):
            return "country"
        if any(keyword in lower for keyword in ["operates in", "in the energy sector", "energy sector", "water sector", "transport sector", "technology sector"]):
            return "sector"
        if re.search(r"\b(active|inactive|proposed|approved|operational|closed|pending)\b", lower):
            return "status"
        return None

    def _is_direct_relationship(self, text: str, predicate: Optional[str], target: Optional[str]) -> bool:
        if not predicate or not target:
            return False
        normalized = predicate.lower().strip()
        if normalized in self._relationship_predicates:
            if re.search(r"\b(sector|industry|market|activity|supply chain|system|policy)\b", text, flags=re.IGNORECASE):
                return False
            if normalized in {"is", "is_a", "is_an"}:
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
        for marker in ["relevant to", "connected to", "associated with", "related to", "linked to"]:
            if marker in lower:
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
