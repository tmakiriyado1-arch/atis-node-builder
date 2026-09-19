"""Transform evidence-backed research claims into a deterministic ATIS node draft."""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from app.models import NodeDraft
from app.services.claim_classifier import ClaimClassifier
from app.services.research_engine import ResearchClaim


class NodeDraftBuilder:
    """Map validated research claims to a minimal markdown node representation."""

    claim_pattern = re.compile(
        r"^(?P<subject>.+?)\s+(?P<predicate>regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|is|has)\s+(?P<object>.+?)(?:\.|$)",
        re.IGNORECASE,
    )

    def __init__(self, registry=None, resolver=None):
        self.classifier = ClaimClassifier(registry=registry, resolver=resolver)

    def build(self, claims: Sequence[ResearchClaim] | Iterable[ResearchClaim]) -> NodeDraft:
        valid_claims = self._valid_claims(claims)
        if not valid_claims:
            return NodeDraft(title="", frontmatter={}, body="", source_claims=[])

        title = self._derive_title(valid_claims)
        sources = list(dict.fromkeys(
            url.strip()
            for claim in valid_claims
            for url in (self.classifier._evidence_urls(claim) if hasattr(self.classifier, "_evidence_urls") else [claim.source_url])
            if url and url.strip()
        ))

        summary_parts: List[str] = []
        relationship_entries: List[str] = []
        association_entries: List[str] = []
        metadata: dict[str, str] = {}
        review_entries: List[str] = []
        seen_relationships: set[str] = set()
        seen_associations: set[str] = set()

        for claim in valid_claims:
            classification = self.classifier.classify(claim)
            claim_text = classification.raw_claim or self._claim_text(claim)

            if classification.category == "SUMMARY":
                summary_parts.append(claim_text)

            elif classification.category == "RELATIONSHIP":
                summary_parts.append(claim_text)
                rendered = self._format_route(classification, claim_text)
                if rendered and rendered not in seen_relationships:
                    seen_relationships.add(rendered)
                    relationship_entries.append(rendered)

            elif classification.category == "ASSOCIATION":
                rendered = self._format_route(classification, claim_text)
                if rendered and rendered not in seen_associations:
                    seen_associations.add(rendered)
                    association_entries.append(rendered)

            elif classification.category == "METADATA":
                field = classification.metadata_field or "metadata"
                value = classification.target or classification.raw_claim
                if value and field not in metadata:
                    metadata[field] = str(value).strip()

            elif classification.category == "UNCLASSIFIED":
                if claim_text:
                    review_entries.append(claim_text)

        body_lines: List[str] = []
        if summary_parts:
            body_lines.append("## Summary")
            for part in summary_parts:
                body_lines.append(f"- {part}")
        if relationship_entries:
            body_lines.append("## Relationships")
            for entry in relationship_entries:
                body_lines.append(f"- {self._arrowize(entry)}")
        if association_entries:
            body_lines.append("## Associations")
            for entry in association_entries:
                body_lines.append(f"- {self._arrowize(entry)}")
        if review_entries:
            body_lines.append("## Review")
            for entry in review_entries:
                body_lines.append(f"- {entry}")
        body = "\n".join(body_lines)

        frontmatter = {
            "title": title,
            "entity": title,
            "sources": sources,
        }
        if relationship_entries:
            frontmatter["relationships"] = relationship_entries
        if association_entries:
            frontmatter["associations"] = association_entries
        if metadata:
            frontmatter.update(metadata)
        if review_entries:
            frontmatter["unclassified"] = review_entries

        return NodeDraft(title=title, frontmatter=frontmatter, body=body, source_claims=valid_claims)

    def _valid_claims(self, claims: Sequence[ResearchClaim] | Iterable[ResearchClaim]) -> List[ResearchClaim]:
        valid: List[ResearchClaim] = []
        for claim in claims:
            if claim is None:
                continue
            if not isinstance(claim, ResearchClaim):
                continue
            text = (getattr(claim, "claim_text", getattr(claim, "claim", "") or "") or "").strip()
            if not text:
                continue
            valid.append(claim)
        return valid

    def _derive_title(self, claims: Sequence[ResearchClaim]) -> str:
        first = claims[0]
        text = (getattr(first, "claim_text", getattr(first, "claim", "") or "") or "").strip()
        match = self.claim_pattern.match(text)
        if match:
            return match.group("subject").strip(" .")
        return self._fallback_title_from_text(text)

    def _fallback_title_from_text(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip(" .")
        if not cleaned:
            return ""
        sentence = cleaned.split(".", 1)[0].strip()
        if not sentence:
            return ""
        return sentence

    def _claim_text(self, claim: ResearchClaim) -> str:
        if isinstance(claim, dict):
            return str((claim.get("claim_text") or claim.get("claim") or "")).strip()
        return str(getattr(claim, "claim_text", getattr(claim, "claim", "") or "")).strip()

    def _format_route(self, classification, claim_text: str) -> str:
        if not classification or not classification.target:
            return ""

        target = classification.resolved_target or classification.target
        subject = None
        if hasattr(classification, "raw_claim") and classification.raw_claim:
            text = classification.raw_claim
            match = re.match(r"^(?P<subject>.+?)\s+(?:is|are|was|were|regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|connected to|relevant to|associated with|related to)\s+(?P<object>.+)$", text, flags=re.IGNORECASE)
            if match:
                subject = match.group("subject").strip(" .")

        if subject and target and target.strip().lower() == subject.lower() and classification.resolved_target is None:
            return f"{(classification.predicate or 'related_to').lower()}::{target.strip()}"

        return f"{(classification.predicate or 'related_to').lower()}::[[{target.strip()}]]"

    def _arrowize(self, value: str) -> str:
        if "::[[" in value and "]]" in value:
            prefix, target = value.split("::[[", 1)
            target = target.rsplit("]]", 1)[0]
            return f"{prefix} → {target}"
        if "::" in value:
            prefix, target = value.split("::", 1)
            return f"{prefix} → {target}"
        return value
