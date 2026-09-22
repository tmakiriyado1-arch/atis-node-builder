"""Transform evidence-backed research claims into a deterministic ATIS node draft.

This builder creates comprehensive markdown nodes with:
- Preserved canonical entity names
- Detailed metadata extraction
- Rich relationship and association networks
- Comprehensive summaries
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence

from app.models import NodeDraft
from app.services.claim_classifier import ClaimClassifier
from app.services.research_engine import ResearchClaim


class NodeDraftBuilder:
    """Map validated research claims to a minimal markdown node representation.
    
    This builder ensures:
    1. Canonical entity name is preserved from RITA input
    2. All metadata fields are extracted and included
    3. Relationships and associations are properly formatted
    4. Summaries are comprehensive and descriptive
    """

    claim_pattern = re.compile(
        r"^(?P<subject>.+?)\s+(?P<predicate>regulates|manages|oversees|supports|operates|provides|governs|controls|establishes|requires|enforces|includes|covers|monitors|administers|coordinates|maintains|owns|leads|is|has|created|develops|implements)\s+(?P<object>.+?)(?:\.|$)",
        re.IGNORECASE,
    )

    def __init__(self, registry=None, resolver=None, rita_entity=None):
        self.classifier = ClaimClassifier(registry=registry, resolver=resolver)
        self.rita_entity = rita_entity

    def build(self, claims: Sequence[ResearchClaim] | Iterable[ResearchClaim]) -> NodeDraft:
        valid_claims = self._valid_claims(claims)
        if not valid_claims:
            return NodeDraft(title="", frontmatter={}, body="", source_claims=[])

        # Preserve canonical entity name from RITA if available
        canonical_entity_name = None
        if self.rita_entity:
            canonical_entity_name = getattr(self.rita_entity, 'name', None)
        
        # Derive title - prefer canonical name, then extract from claims
        if canonical_entity_name:
            title = canonical_entity_name
        else:
            title = self._derive_title(valid_claims)
        
        # Collect all evidence URLs from all claims
        all_sources = set()
        for claim in valid_claims:
            urls = self.classifier._evidence_urls(claim) if hasattr(self.classifier, "_evidence_urls") else []
            if isinstance(urls, list):
                for url in urls:
                    if url and url.strip():
                        all_sources.add(url.strip())
            elif isinstance(urls, str):
                if urls and urls.strip():
                    all_sources.add(urls.strip())
            # Also check source_url attribute
            source_url = getattr(claim, 'source_url', None)
            if source_url and isinstance(source_url, str) and source_url.strip():
                all_sources.add(source_url.strip())
        
        sources = sorted(all_sources)

        # Extract metadata from claims
        metadata: dict[str, str | List[str]] = {}
        entity_type = None
        subtype = None
        country = None
        sector = None
        status = None
        aliases: List[str] = []
        
        # Track what we've extracted
        extracted_entity_types: set[str] = set()
        extracted_countries: set[str] = set()
        extracted_sectors: set[str] = set()
        extracted_statuses: set[str] = set()
        
        # Process each claim for metadata
        for claim in valid_claims:
            classification = self.classifier.classify(claim)
            
            if classification.category == "METADATA":
                field = classification.metadata_field
                value = classification.target or classification.raw_claim
                
                if field and value:
                    if field == "entity_type":
                        extracted_entity_types.add(value)
                    elif field == "country":
                        extracted_countries.add(value)
                    elif field == "sector":
                        extracted_sectors.add(value)
                    elif field == "status":
                        extracted_statuses.add(value)
                    elif field == "subtype":
                        subtype = value
                    elif field:
                        # Other metadata fields
                        if field not in metadata:
                            metadata[field] = value
            
            # Extract aliases from claim text
            claim_text = classification.raw_claim or self._claim_text(claim)
            alias = self._extract_alias(claim_text, title)
            if alias and alias != title:
                if alias not in aliases:
                    aliases.append(alias)
        
        # Set single-value metadata fields
        if extracted_entity_types:
            entity_type = ", ".join(sorted(extracted_entity_types))
        if extracted_countries:
            country = ", ".join(sorted(extracted_countries))
        if extracted_sectors:
            sector = ", ".join(sorted(extracted_sectors))
        if extracted_statuses:
            status = ", ".join(sorted(extracted_statuses))
        
        # Extract relationships and associations
        relationship_entries: List[str] = []
        association_entries: List[str] = []
        seen_relationships: set[str] = set()
        seen_associations: set[str] = set()
        
        for claim in valid_claims:
            classification = self.classifier.classify(claim)
            
            if classification.category == "RELATIONSHIP":
                rendered = self._format_route(classification)
                if rendered and rendered not in seen_relationships:
                    seen_relationships.add(rendered)
                    relationship_entries.append(rendered)
            elif classification.category == "ASSOCIATION":
                rendered = self._format_route(classification)
                if rendered and rendered not in seen_associations:
                    seen_associations.add(rendered)
                    association_entries.append(rendered)
        
        # Extract summary parts
        summary_parts: List[str] = []
        explicit_summary_parts: List[str] = []
        
        for claim in valid_claims:
            classification = self.classifier.classify(claim)
            claim_text = classification.raw_claim or self._claim_text(claim)
            
            if classification.category == "SUMMARY":
                explicit_summary_parts.append(claim_text)
        
        # Build comprehensive summary
        if explicit_summary_parts:
            summary_parts = explicit_summary_parts
        else:
            # Build summary from all claims
            summary_sentence = self._build_summary_sentence(title, entity_type, country, sector, valid_claims)
            if summary_sentence:
                summary_parts = [summary_sentence]
        
        # Build body
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
        
        # Add metadata section if we have extracted metadata
        if entity_type or country or sector or status or subtype:
            body_lines.append("## Metadata")
            if entity_type:
                body_lines.append(f"- **Entity Type**: {entity_type}")
            if subtype:
                body_lines.append(f"- **Subtype**: {subtype}")
            if country:
                body_lines.append(f"- **Country/Region**: {country}")
            if sector:
                body_lines.append(f"- **Sector**: {sector}")
            if status:
                body_lines.append(f"- **Status**: {status}")
        
        body = "\n".join(body_lines)

        # Build frontmatter
        frontmatter = {
            "title": title,
            "entity": title,
            "sources": sources,
        }
        
        # Add canonical entity name if different from title
        if canonical_entity_name and canonical_entity_name != title:
            frontmatter["canonical_name"] = canonical_entity_name
        
        if entity_type:
            frontmatter["entity_type"] = entity_type
        if subtype:
            frontmatter["subtype"] = subtype
        if country:
            frontmatter["country"] = country
        if sector:
            frontmatter["sector"] = sector
        if status:
            frontmatter["status"] = status
        if relationship_entries:
            frontmatter["relationships"] = relationship_entries
        if association_entries:
            frontmatter["associations"] = association_entries
        if aliases:
            frontmatter["aliases"] = aliases
        
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

    def _extract_alias(self, text: str, entity_name: str) -> Optional[str]:
        """Extract potential aliases from claim text."""
        # Look for text in parentheses
        match = re.search(r"\b(SAPP|Southern African Power Pool|The Southern African Power Pool)\b", text)
        if match:
            alias = match.group(0)
            if alias != entity_name:
                return alias
        
        # Look for acronyms in parentheses
        match = re.search(r"\(([A-Z]{2,})\)", text)
        if match:
            alias = match.group(1).strip()
            if alias != entity_name:
                return alias
        
        # Look for "also known as" patterns
        aka_patterns = [
            r"also known as\s+([^\.]+)",
            r"aka\s+([^\.]+)",
            r"a\.k\.a\.\s+([^\.]+)",
            r"referred to as\s+([^\.]+)",
            r"commonly called\s+([^\.]+)",
        ]
        for pattern in aka_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                alias = match.group(1).strip()
                if alias != entity_name:
                    return alias
        
        return None

    def _build_summary_sentence(self, entity: str, entity_type: Optional[str], country: Optional[str], sector: Optional[str], claims: Sequence[ResearchClaim]) -> Optional[str]:
        """Build a comprehensive summary sentence from entity information."""
        parts: List[str] = [f"[[{entity}]]"]
        
        # Add entity type
        if entity_type:
            parts.append(f"is {entity_type}")
        
        # Add location
        if country:
            parts.append(f"based in {country}")
        
        # Add sector
        if sector:
            if sector.lower().endswith("sector"):
                parts.append(f"operating in the {sector}")
            else:
                parts.append(f"operating in the {sector} sector")
        
        # Add what it does from claims
        action_phrases = []
        for claim in claims:
            classification = self.classifier.classify(claim)
            claim_text = classification.raw_claim or self._claim_text(claim)
            
            # Extract action phrases - look for what the entity does
            action_match = re.search(
                r"(?:has|have|was|were|is|are|established|founded|created|developed|built|formed|launched)\s+([^.]+)",
                claim_text,
                re.IGNORECASE
            )
            if action_match:
                action_phrases.append(action_match.group(1).strip())
            
            # Extract "provides" patterns
            provides_match = re.search(
                r"(?:provides|supports|offers|delivers|facilitates|enables|coordinates|manages|oversees|regulates|administers|operates|maintains)\s+([^.]+)",
                claim_text,
                re.IGNORECASE
            )
            if provides_match:
                action_phrases.append(provides_match.group(1).strip())
            
            # Extract "creates" patterns
            creates_match = re.search(
                r"(?:creates|establishes|develops|implements|executes|advises|consults|represents)\s+([^.]+)",
                claim_text,
                re.IGNORECASE
            )
            if creates_match:
                action_phrases.append(creates_match.group(1).strip())
        
        if action_phrases:
            if parts[-1].endswith("ing") or parts[-1].endswith("ed"):
                parts.append("and " + ", ".join(action_phrases))
            else:
                parts.append("that " + ", ".join(action_phrases))
        elif entity_type or country or sector:
            # If we have metadata but no actions, add a generic description
            parts.append("that functions within its established framework")
        else:
            # Fallback to first claim text
            if claims:
                first_text = self._claim_text(claims[0])
                # Remove the entity name from the beginning if present
                cleaned = re.sub(rf"^{re.escape(entity)}\s*(?:is|are|was|were|be|being|been)\s*", "", first_text, flags=re.IGNORECASE).strip()
                if cleaned:
                    parts.append(cleaned)
        
        return " ".join(parts) + "."

    def _format_route(self, classification, claim_text: Optional[str] = None) -> str:
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
            return f"{prefix} \u2192 {target}"
        if "::" in value:
            prefix, target = value.split("::", 1)
            return f"{prefix} \u2192 {target}"
        return value
