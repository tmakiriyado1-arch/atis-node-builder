"""Build a canonical import row from an evidence-backed node draft."""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence

from app.models import CanonicalNodeRow, NodeDraft
from app.services.research_engine import ResearchClaim


class CanonicalNodeRowBuilder:
    """Deterministic row builder for ATIS import artifacts."""

    _relationship_patterns = [
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
    ]

    def build(self, node_draft: NodeDraft) -> CanonicalNodeRow:
        if node_draft is None:
            raise ValueError("node_draft is required")

        entity = (node_draft.frontmatter.get("entity") or node_draft.title or "").strip()
        if not entity:
            raise ValueError("node draft must include an entity name")

        claims = list(node_draft.source_claims or [])
        if not claims:
            raise ValueError("node draft must include at least one source-backed claim")

        # Try to extract summary from NodeDraft body if it has a Summary section
        summary = self._extract_summary_from_draft(node_draft, entity, claims)
        relationships = self._extract_relationships(claims)
        associations = self._extract_associations(claims)
        sources = self._extract_sources(node_draft, claims)
        aliases = self._extract_aliases(entity, node_draft, claims)
        frontmatter = node_draft.frontmatter or {}

        return CanonicalNodeRow(
            uid=self._uid_from_entity(entity),
            entity=entity,
            aliases=aliases,
            entity_type=frontmatter.get("entity_type") or frontmatter.get("entityType") or None,
            subtype=frontmatter.get("subtype") or None,
            country=frontmatter.get("country") or None,
            sector=frontmatter.get("sector") or None,
            status=frontmatter.get("status") or "draft",
            summary=summary,
            relationships=relationships,
            associations=associations,
            sources=sources,
        )

    def _extract_summary_from_draft(self, node_draft: NodeDraft, entity: str, claims: Sequence[ResearchClaim]) -> str:
        """Extract summary from NodeDraft body, preferring explicit Summary section."""
        body = node_draft.body or ""
        
        # Try to extract from body Summary section
        if "## Summary" in body:
            lines = body.split("\n")
            summary_lines = []
            in_summary = False
            for line in lines:
                stripped = line.strip()
                if stripped == "## Summary":
                    in_summary = True
                    continue
                if in_summary:
                    if stripped.startswith("##"):
                        break
                    if stripped:
                        summary_lines.append(stripped)
            if summary_lines:
                # Join summary lines, remove bullet points
                summary_text = " ".join(line.lstrip("- ") for line in summary_lines if line.strip())
                return summary_text.strip()
        
        # Fall back to old behavior
        return self._build_summary(entity, claims)

    def _uid_from_entity(self, entity: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "-", entity.lower()).strip("-")
        return cleaned or "entity"

    def _extract_aliases(self, entity: str, node_draft: NodeDraft, claims: Sequence[ResearchClaim]) -> List[str]:
        aliases = []
        frontmatter = node_draft.frontmatter or {}
        if isinstance(frontmatter.get("aliases"), list):
            aliases.extend(str(item).strip() for item in frontmatter["aliases"] if str(item).strip())
        if node_draft.title and node_draft.title.strip():
            aliases.append(node_draft.title.strip())
        for claim in claims:
            if not isinstance(claim, ResearchClaim):
                continue
            text = (claim.claim or "").strip()
            if not text:
                continue
            if "(" in text and ")" in text:
                match = re.search(r"\(([^)]+)\)", text)
                if match and match.group(1).strip() and match.group(1).strip() != entity:
                    aliases.append(match.group(1).strip())
        deduped: List[str] = []
        seen = set()
        for alias in aliases:
            if alias and alias not in seen:
                deduped.append(alias)
                seen.add(alias)
        return deduped

    def _extract_sources(self, node_draft: NodeDraft, claims: Sequence[ResearchClaim]) -> List[str]:
        sources = []
        frontmatter_sources = node_draft.frontmatter.get("sources") if isinstance(node_draft.frontmatter, dict) else []
        if isinstance(frontmatter_sources, list):
            sources.extend(str(item).strip() for item in frontmatter_sources if str(item).strip())
        for claim in claims:
            if hasattr(claim, "source_url"):
                url = (claim.source_url or "").strip()
                if url:
                    sources.append(url)
        seen = set()
        ordered: List[str] = []
        for source in sources:
            if source and source not in seen:
                ordered.append(source)
                seen.add(source)
        return ordered

    def _extract_relationships(self, claims: Sequence[ResearchClaim]) -> List[str]:
        lines: List[str] = []
        for claim in claims:
            text = (getattr(claim, "claim", "") or "").strip()
            if not text:
                continue
            relationship = self._serialize_relationship(text)
            if relationship:
                lines.append(relationship)
        return lines

    def _extract_associations(self, claims: Sequence[ResearchClaim]) -> List[str]:
        lines: List[str] = []
        for claim in claims:
            text = (getattr(claim, "claim", "") or "").strip()
            if not text:
                continue
            association = self._serialize_association(text)
            if association:
                lines.append(association)
        return lines

    def _build_summary(self, entity: str, claims: Sequence[ResearchClaim]) -> str:
        summary_claim = None
        for claim in claims:
            text = (getattr(claim, "claim", "") or "").strip()
            if text:
                summary_claim = text
                break

        if summary_claim is None:
            return f"[[{entity}]] is a relevant entity with traceable source provenance."

        relationship = self._serialize_relationship(summary_claim)
        association = self._serialize_association(summary_claim)
        if relationship:
            label = relationship.split("::", 1)[0]
            object_name = self._extract_object(summary_claim) or relationship.split("::", 1)[1].strip().replace("[[", "").replace("]]", "")
            return f"[[{entity}]] {label} [[{object_name.lower()}]]. It functions by carrying out this relationship and maintaining operational continuity."
        if association:
            label = association.split("::", 1)[0]
            target = self._extract_association_target(summary_claim) or association.split("::", 1)[1].strip().replace("[[", "").replace("]]", "")
            return f"[[{entity}]] is relevant to [[{target.lower()}]]. It supports related operational context and connects to this area."

        lower = summary_claim.lower()
        if " regulates " in lower:
            object_name = self._extract_object(summary_claim)
            if object_name:
                return f"[[{entity}]] regulates [[{object_name}]]. It functions within the operating framework for this responsibility."
        if " oversees " in lower:
            object_name = self._extract_object(summary_claim)
            if object_name:
                return f"[[{entity}]] oversees [[{object_name}]]. It functions by monitoring and coordinating the associated activity."
        object_name = self._extract_object(summary_claim)
        if object_name:
            return f"[[{entity}]] is connected to [[{object_name}]]. It functions by supporting the activity described in its source-backed claim."
        return f"[[{entity}]] is a traceable entity described in source-backed evidence."

    def _extract_object(self, text: str) -> str:
        match = re.search(r"(?:regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads)\s+(?:the\s+)?(.+?)(?:\.|$)", text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().rstrip(".")
            return value
        return ""

    def _extract_association_target(self, text: str) -> str:
        match = re.search(r"(?:relevant to|connected to|associated with)\s+(?:the\s+)?(.+?)(?:\.|$)", text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().rstrip(".")
            return value
        return ""

    def _serialize_relationship(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        for keyword in self._relationship_patterns:
            match = re.search(rf"(?i)(?:^|\s){keyword}\s+(?:the\s+)?(.+?)(?:\.|$)", cleaned)
            if match:
                target = match.group(1).strip().rstrip(".")
                if not target:
                    continue
                target_words = target.split()
                if len(target_words) > 1:
                    display = target_words[0].capitalize()
                else:
                    display = target_words[0].capitalize() if target_words else "Entity"
                return f"{keyword}::[[{display}]]"
        return ""

    def _serialize_association(self, text: str) -> str:
        cleaned = (text or "").strip()
        if not cleaned:
            return ""
        association_patterns = [
            ("relevant_to", r"relevant to\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("connected_to", r"connected to\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("associated_with", r"associated with\s+(?:the\s+)?(.+?)(?:\.|$)"),
        ]
        for label, pattern in association_patterns:
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                target = match.group(1).strip().rstrip(".")
                return f"{label}::[[{target.title()}]]"
        return ""
