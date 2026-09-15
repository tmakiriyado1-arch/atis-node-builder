"""
Phase 4: Backlink Engine - Extract entity mentions and generate backlinks
Phase 5: Research Engine - Internet research and evidence extraction
Phase 6-8: Node Builder, Queue Processing, CSV Export
"""

# Backlink Engine (Phase 4)
The backlink engine extracts entity mentions from prose (summaries, descriptions, claims) and generates canonical backlinks.

**Key Principle**: Do NOT create backlinks only for missing nodes. Generate backlinks for ALL resolved entities, whether nodes exist or not.

**Components**:
1. **EntityMentionExtractor** - Finds potential entity mentions
2. **BacklinkGenerator** - Resolves mentions and creates backlinks

**Handles**:
- Capitalized phrases (e.g., "Zimbabwe Energy Regulatory Authority")
- Acronyms (e.g., "ZERA")
- Existing wikilinks (e.g., "[[Zimbabwe Energy Regulatory Authority]]")
- Entity-bearing fields (lists, individual values)
- Deduplication (don't backlink same entity twice)

# New Entity Queue (Phase 7)
Recursively discovered entities are registered with:
- Canonical name
- Source (which node discovered it)
- Source field
- Context
- Confidence
- Processing status

Deduplication via Entity Resolution (not string equality).

# Research Engine (Phase 5)
Placeholder for internet research with:
- SearchProvider interface (replaceable backend)
- LLM-based claim extraction
- Evidence passage retention
- Field-specific research
- Confidence tracking
- Full provenance

TODO: Implement with real search provider and Mistral integration.

# Node Builder (Phase 6)
TODO: Main orchestration that:
1. Takes RITA entity input
2. Resolves canonical identity
3. Researches using field-driven strategy
4. Extracts entities from prose
5. Populates ATIS fields
6. Generates backlinks
7. Validates against schema
8. Outputs CSV row

# CSV Export (Phase 8)
TODO: Export to canonical Google Sheets format with:
- Exact column names
- Correct data types
- Backlinked values
- Empty fields for unknowns
- Full validation

# Development Complete To This Point
✓ Phase 1: Repository Foundation
✓ Phase 2: Configuration
✓ Phase 3: Entity Resolution (core)
→ Phase 4: Backlink Engine (in progress)
→ Phase 5: Research Engine (placeholder)

Remaining:
→ Phase 6: Node Builder
→ Phase 7: Queue Processing
→ Phase 8: CSV Export
→ Phase 9: Web Interface (after backend stable)
