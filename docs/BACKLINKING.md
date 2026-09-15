# ATIS Node Builder — Backlink Engine

## Overview

The Backlink Engine extracts entity mentions from prose and generates canonical backlinks.

**Critical Principle**: Generate backlinks for ALL resolved entities, regardless of whether the target node exists.

```
Input: "The Ministry collaborates with the Zimbabwe Energy Regulatory Authority..."
Processing: Extract mention "Zimbabwe Energy Regulatory Authority" → Resolve to canonical
Output: "The Ministry collaborates with the [[Zimbabwe Energy Regulatory Authority]]..."
Queue: Register "Zimbabwe Energy Regulatory Authority" for processing if node missing
```

## Components

### EntityMentionExtractor

Identifies potential entity mentions in text.

**Handles**:
- Capitalized phrases: "Zimbabwe Energy Regulatory Authority"
- Acronyms: "ZERA"
- Existing wikilinks: "[[Zimbabwe Energy Regulatory Authority]]"
- Deduplicates mentions

### BacklinkGenerator

Resolves mentions and generates backlinks for fields and prose.

**Key Methods**:
```python
generator = BacklinkGenerator(resolver)

# Backlink individual field
backlinked = generator.backlink_field("ZERA; Zimbabwe Energy Regulatory Authority")
# → "[[Zimbabwe Energy Regulatory Authority]]" (deduplicated)

# Backlink summary with entity extraction
summary, entities = generator.backlink_summary(summary_text)
# Returns: (backlinked_summary, [(mention, canonical, confidence), ...])
```

## Important Rules

1. **ALWAYS generate backlinks for resolved entities** — Even if node doesn't exist yet
2. **DEDUPLICATE on canonical name** — Not on raw text
3. **PRESERVE context** — Keep surrounding prose intact
4. **TRACK resolution quality** — Record confidence and reasoning
5. **REGISTER unknowns** — Queue entities that need nodes
