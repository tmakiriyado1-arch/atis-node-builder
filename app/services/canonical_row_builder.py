"""Build a canonical import row from an evidence-backed node draft.

This builder ensures all fields are properly extracted and preserved,
including entity type, subtype, country, sector, status, relationships, and associations.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence

from app.models import CanonicalNodeRow, NodeDraft
from app.services.research_engine import ResearchClaim


class CanonicalNodeRowBuilder:
    """Deterministic row builder for ATIS import artifacts.
    
    This builder extracts all available information from the node draft and claims
    to create a comprehensive canonical row.
    """

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
        "founded",
        "created",
        "develops",
        "implements",
        "executes",
        "advises",
        "consults",
        "represents",
        "participates",
        "collaborates",
        "partners",
    ]

    def build(self, node_draft: NodeDraft) -> CanonicalNodeRow:
        if node_draft is None:
            raise ValueError("node_draft is required")

        # Get entity from frontmatter or title
        entity = (node_draft.frontmatter.get("entity") or node_draft.title or "").strip()
        if not entity:
            raise ValueError("node draft must include an entity name")
        
        # Preserve canonical name if available
        canonical_name = node_draft.frontmatter.get("canonical_name")
        if canonical_name and canonical_name.strip():
            entity = canonical_name.strip()
        
        claims = list(node_draft.source_claims or [])
        if not claims:
            raise ValueError("node draft must include at least one source-backed claim")

        # Extract summary from NodeDraft body or build from claims
        summary = self._extract_summary_from_draft(node_draft, entity, claims)
        
        # Extract relationships and associations from frontmatter or claims
        relationships = self._extract_relationships_from_frontmatter(node_draft)
        if not relationships:
            relationships = self._extract_relationships(claims)
        
        associations = self._extract_associations_from_frontmatter(node_draft)
        if not associations:
            associations = self._extract_associations(claims)
        
        # Extract sources from frontmatter or claims
        sources = self._extract_sources(node_draft, claims)
        
        # Extract aliases from frontmatter or claims
        aliases = self._extract_aliases(node_draft, claims)
        
        # Extract metadata from frontmatter
        frontmatter = node_draft.frontmatter or {}
        entity_type = frontmatter.get("entity_type") or frontmatter.get("entityType")
        subtype = frontmatter.get("subtype") or frontmatter.get("subType")
        country = frontmatter.get("country") or frontmatter.get("Country")
        sector = frontmatter.get("sector") or frontmatter.get("Sector")
        status = frontmatter.get("status") or frontmatter.get("Status") or "draft"
        
        # If metadata not in frontmatter, try to extract from body
        if not entity_type:
            entity_type = self._extract_entity_type_from_body(node_draft.body)
        if not country:
            country = self._extract_country_from_body(node_draft.body)
        if not sector:
            sector = self._extract_sector_from_body(node_draft.body)
        if not status or status == "draft":
            status = self._extract_status_from_body(node_draft.body) or "draft"
        
        return CanonicalNodeRow(
            uid=self._uid_from_entity(entity),
            entity=entity,
            aliases=aliases,
            entity_type=entity_type,
            subtype=subtype,
            country=country,
            sector=sector,
            status=status,
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
        
        # Fall back to building from claims
        return self._build_summary(entity, claims)

    def _extract_relationships_from_frontmatter(self, node_draft: NodeDraft) -> List[str]:
        """Extract relationships from frontmatter."""
        frontmatter = node_draft.frontmatter or {}
        relationships = frontmatter.get("relationships")
        if isinstance(relationships, list):
            return [str(r).strip() for r in relationships if str(r).strip()]
        return []

    def _extract_associations_from_frontmatter(self, node_draft: NodeDraft) -> List[str]:
        """Extract associations from frontmatter."""
        frontmatter = node_draft.frontmatter or {}
        associations = frontmatter.get("associations")
        if isinstance(associations, list):
            return [str(a).strip() for a in associations if str(a).strip()]
        return []

    def _uid_from_entity(self, entity: str) -> str:
        cleaned = re.sub(r"[^a-z0-9]+", "-", entity.lower()).strip("-")
        return cleaned or "entity"

    def _extract_aliases(self, node_draft: NodeDraft, claims: Sequence[ResearchClaim]) -> List[str]:
        aliases = []
        frontmatter = node_draft.frontmatter or {}
        
        # Get aliases from frontmatter
        if isinstance(frontmatter.get("aliases"), list):
            aliases.extend(str(item).strip() for item in frontmatter["aliases"] if str(item).strip())
        
        # Get title as alias if different from entity
        if node_draft.title and node_draft.title.strip():
            title = node_draft.title.strip()
            entity = (frontmatter.get("entity") or title).strip()
            if title != entity:
                aliases.append(title)
        
        # Extract aliases from claims (acronyms, alternative names)
        for claim in claims:
            if not isinstance(claim, ResearchClaim):
                continue
            text = (claim.claim or "").strip()
            if not text:
                continue
            # Look for parentheses (acronyms)
            if "(" in text and ")" in text:
                match = re.search(r"\(([^)]+)\)", text)
                if match and match.group(1).strip():
                    alias = match.group(1).strip()
                    if alias not in aliases:
                        aliases.append(alias)
            # Look for "also known as" patterns
            aka_match = re.search(r"(?:also known as|aka|a\.k\.a\.)\s+([^\.]+)", text, re.IGNORECASE)
            if aka_match and aka_match.group(1).strip():
                alias = aka_match.group(1).strip()
                if alias not in aliases:
                    aliases.append(alias)
        
        # Deduplicate
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
        
        # Also extract from claims
        for claim in claims:
            if hasattr(claim, "source_url"):
                url = (claim.source_url or "").strip()
                if url and url not in sources:
                    sources.append(url)
            if hasattr(claim, "evidence_urls"):
                urls = claim.evidence_urls
                if isinstance(urls, list):
                    for url in urls:
                        url = str(url).strip()
                        if url and url not in sources:
                            sources.append(url)
        
        # Deduplicate while preserving order
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
            if relationship and relationship not in lines:
                lines.append(relationship)
        return lines

    def _extract_associations(self, claims: Sequence[ResearchClaim]) -> List[str]:
        lines: List[str] = []
        for claim in claims:
            text = (getattr(claim, "claim", "") or "").strip()
            if not text:
                continue
            association = self._serialize_association(text)
            if association and association not in lines:
                lines.append(association)
        return lines

    def _build_summary(self, entity: str, claims: Sequence[ResearchClaim]) -> str:
        """Build a comprehensive summary from entity and claims."""
        # Try to find the most descriptive claim
        best_claim = None
        best_length = 0
        
        for claim in claims:
            text = (getattr(claim, "claim", "") or "").strip()
            if text and len(text) > best_length:
                best_claim = text
                best_length = len(text)
        
        if best_claim:
            # Clean up the claim text
            # Remove entity name from beginning if redundant
            cleaned = re.sub(rf"^{re.escape(entity)}\s*(?:is|are|was|were|be|being|been)\s*", "", best_claim, flags=re.IGNORECASE).strip()
            # Ensure it starts with the entity in wikilink format
            if not cleaned.startswith("[["):
                cleaned = f"[[{entity}]] {cleaned}"
            # Ensure it ends with a period
            if not cleaned.endswith("."):
                cleaned = cleaned + "."
            # Ensure it has a verb that explains function
            if not re.search(r"\b(is|are|was|were|regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|created|has|functions|delivers|facilitates|enables)\b", cleaned, re.IGNORECASE):
                # Add a generic function description
                cleaned = f"{cleaned} It functions within its established framework."
            return cleaned
        
        # Fallback
        return f"[[{entity}]] is a traceable entity described in source-backed evidence."

    def _extract_entity_type_from_body(self, body: str) -> Optional[str]:
        """Extract entity type from body text."""
        if not body:
            return None
        
        # Look for "Entity Type: " or similar
        match = re.search(r"(?:entity\s+type|type)\s*[:=]\s*([^\n]+)", body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Look for "is a/an [type]" patterns
        match = re.search(r"\b(is|are|was|were)\s+(?:a|an|the)\s+([a-z0-9\s-]+)", body, re.IGNORECASE)
        if match:
            entity_type = match.group(2).strip()
            # Capitalize
            return entity_type.capitalize()
        
        return None

    def _extract_country_from_body(self, body: str) -> Optional[str]:
        """Extract country/region from body text."""
        if not body:
            return None
        
        # Look for "Country: " or "Country/Region: " or "located in" or "based in"
        match = re.search(r"(?:country|region|location|based\s+in|located\s+in|operates\s+in|headquartered\s+in)\s*[:=]\s*([^\n]+)", body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Look for country names
        country_patterns = [
            "Southern Africa",
            "SADC",
            "Southern African Development Community",
            "Africa",
            "Zimbabwe",
            "South Africa",
            "Mozambique",
            "Kenya",
            "Nigeria",
        ]
        for country in country_patterns:
            if country in body:
                return country
        
        return None

    def _extract_sector_from_body(self, body: str) -> Optional[str]:
        """Extract sector from body text."""
        if not body:
            return None
        
        # Look for "Sector: " or similar
        match = re.search(r"(?:sector|industry|field)\s*[:=]\s*([^\n]+)", body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Look for sector keywords
        sector_patterns = [
            "Energy Sector",
            "Power Sector",
            "Electricity Sector",
            "Infrastructure",
            "Energy",
            "Power",
            "Electricity",
        ]
        for sector in sector_patterns:
            if sector.lower() in body.lower():
                return sector
        
        return None

    def _extract_status_from_body(self, body: str) -> Optional[str]:
        """Extract status from body text."""
        if not body:
            return None
        
        # Look for "Status: " or similar
        match = re.search(r"(?:status|state|condition)\s*[:=]\s*([^\n]+)", body, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        # Look for status keywords
        status_patterns = [
            "active",
            "operational",
            "established",
            "founded",
            "launched",
            "running",
            "functional",
        ]
        for status in status_patterns:
            if status.lower() in body.lower():
                return status.capitalize()
        
        return None

    def _extract_object(self, text: str) -> str:
        match = re.search(r"(?:regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|develops|implements|executes|advises|consults|represents|participates|collaborates|partners|created|has)\s+(?:the\s+)?(.+?)(?:\.|$)", text, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().rstrip(".")
            return value
        return ""

    def _extract_association_target(self, text: str) -> str:
        match = re.search(r"(?:relevant to|connected to|associated with|related to|linked to|affiliated with|partnered with|collaborates with|works with|member of|part of)\s+(?:the\s+)?(.+?)(?:\.|$)", text, flags=re.IGNORECASE)
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
            ("related_to", r"related to\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("linked_to", r"linked to\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("affiliated_with", r"affiliated with\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("partnered_with", r"partnered with\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("collaborates_with", r"collaborates with\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("works_with", r"works with\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("member_of", r"member of\s+(?:the\s+)?(.+?)(?:\.|$)"),
            ("part_of", r"part of\s+(?:the\s+)?(.+?)(?:\.|$)"),
        ]
        for label, pattern in association_patterns:
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                target = match.group(1).strip().rstrip(".")
                return f"{label}::[[{target.title()}]]"
        return ""
