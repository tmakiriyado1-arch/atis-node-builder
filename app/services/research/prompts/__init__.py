"""Entity-Centric Evidence Extraction Prompts.

This module contains the maintainable prompts/templates that define:
- Field meaning
- Field question
- Allowed source of evidence
- Inclusion criteria
- Exclusion criteria
- Examples
- Ontology constraints
- Null behavior
- Traceability requirement

These prompts are stored as maintainable templates rather than buried in code.
The application enforces schema, types, ontology membership, length limits,
relationship validity, backlink validity, required fields, and evidence references.

LLM = semantic extraction/reasoning.
Application = structural authority.
"""
from __future__ import annotations

from typing import Dict, Any, FrozenSet

from app.services.ontology import get_ontology


# =============================================================================
# Field Semantic Definitions
# =============================================================================

# These definitions are used both in prompts and for application-level validation

FIELD_SEMANTIC_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "entity": {
        "meaning": "The canonical name of the entity represented by the node.",
        "question": "What is the authoritative name of this entity?",
        "allowed_source": "RITA seed entity name (PRIMARY), explicit entity name from authoritative source",
        "inclusion_criteria": [
            "Proper/canonical name of the entity",
            "Matches RITA seed entity when available",
            "Exactly one entity per node",
        ],
        "exclusion_criteria": [
            "Descriptions",
            "Slogans",
            "Missions",
            "Programs",
            "Status",
            "URLs",
            "Marketing text",
            "Multiple entities",
        ],
        "examples": [
            {"valid": "Theotechnic College"},
            {"valid": "ZERA"},
            {"invalid": "Theotechnic College is a Christian educational institution", "reason": "Contains description"},
            {"invalid": "Now Open! All applicants will be placed", "reason": "Contains CTA/marketing"},
        ],
        "ontology_constraints": None,  # No ontology constraint - must be proper name
        "null_behavior": "REQUIRED - must never be null",
        "max_length": 200,
        "traceability": "REQUIRED - must be traceable to RITA seed or authoritative source",
    },
    "aliases": {
        "meaning": "Alternative names that people actually use to refer to the SAME entity.",
        "question": "What other names are used to refer to this exact entity?",
        "allowed_source": "Evidence explicitly stating alternate names, acronyms, or institutional variations",
        "inclusion_criteria": [
            "Actually used as alternative names for the same entity",
            "Acronyms (e.g., TC for Theotechnic College)",
            "Shortened names (e.g., Theotechnic for Theotechnic College)",
            "Institutional variations",
            "Domain-associated names",
        ],
        "exclusion_criteria": [
            "Slogans",
            "Taglines",
            "Program names",
            "Bible verses",
            "Mission statements",
            "Fragments",
            "Random extracted words",
            "Names of parent/supporting organizations",
            "Sentences",
            "CTA text",
            "Single letters (unless known acronym)",
        ],
        "examples": [
            {"valid": ["Theotechnic College", "Theotechnic"], "for_entity": "Theotechnic College"},
            {"valid": ["ZERA", "Zimbabwe Energy Regulatory Authority"], "for_entity": "ZERA"},
            {"invalid": "c", "reason": "Single letter, not a valid alias"},
            {"invalid": "2 Timothy 2:15", "reason": "Bible verse, not an alias"},
            {"invalid": "Now Open! All applicants...", "reason": "CTA text, not an alias"},
            {"invalid": "STUDENTSYour Journey...", "reason": "Navigation/fragment, not an alias"},
            {"invalid": "Comprehensive", "reason": "Adjective, not an alias"},
        ],
        "ontology_constraints": None,
        "null_behavior": "OPTIONAL - empty list if no aliases found",
        "max_length_per_item": 200,
        "max_items": 20,
        "traceability": "REQUIRED - each alias must be traceable to evidence",
        "semantic_test": "If I searched for this alias independently, would I reasonably expect it to refer to the same entity?",
    },
    "entity_type": {
        "meaning": "The broad ontological class of the entity. Answers: What KIND of thing is this?",
        "question": "What ontological category does this entity belong to?",
        "allowed_source": "Evidence explicitly stating entity type, or inference from authoritative description",
        "inclusion_criteria": [
            "Valid ontology value from ATIS ontology",
            "Short, descriptive classification",
            "Answers 'What kind of thing is this?'",
        ],
        "exclusion_criteria": [
            "Descriptive prose",
            "Mission statements",
            "Sector values",
            "Program names",
            "Status values",
            "Sentences",
            "CTA language",
            "Webpage prose",
        ],
        "examples": [
            {"valid": "College", "for_entity": "Theotechnic College"},
            {"valid": "Regulatory Authority", "for_entity": "ZERA"},
            {"valid": "Nonprofit Organization", "for_entity": "ACTIVE Ministry"},
            {"invalid": "Now Open! All applicants will be placed on a prospective list", "reason": "Webpage prose, not ontology value"},
            {"invalid": "STUDENTSYour Journey of Faith and Learning Begins Here", "reason": "Navigation/fragment, not ontology value"},
        ],
        "ontology_constraints": lambda: list(get_ontology().all_entity_types),
        "null_behavior": "OPTIONAL - use None if evidence does not support a classification",
        "max_length": 100,
        "traceability": "REQUIRED - must be traceable to evidence or ontology",
    },
    "subtype": {
        "meaning": "A more specific classification within entity_type. Answers: What specific kind of entity is this?",
        "question": "What is the specific subtype of this entity within its entity_type?",
        "allowed_source": "Evidence explicitly stating subtype, or ontology mapping",
        "inclusion_criteria": [
            "Valid subtype from ATIS ontology",
            "More specific than entity_type",
            "Supported by evidence",
        ],
        "exclusion_criteria": [
            "Invented subtypes",
            "Non-ontology values",
            "Generic placeholders",
        ],
        "examples": [
            {"valid": "College", "for_entity": "Theotechnic College (entity_type: Educational Institution)"},
            {"valid": None, "for_entity": "ZERA", "reason": "No subtype in ontology"},
            {"invalid": "-", "reason": "Generic placeholder, not a valid subtype"},
        ],
        "ontology_constraints": lambda: list(get_ontology().organization_subtypes | get_ontology().concept_subtypes),
        "null_behavior": "OPTIONAL - use None if ontology does not support a meaningful subtype",
        "max_length": 100,
        "traceability": "OPTIONAL - if provided, must be traceable to evidence",
    },
    "country": {
        "meaning": "The primary country associated with the entity as an organization/institution.",
        "question": "In which country is this entity primarily located/operating?",
        "allowed_source": "Evidence explicitly stating country, location, or headquarters",
        "inclusion_criteria": [
            "Primary country of the entity as organization/institution",
            "Valid country from ATIS ontology",
            "Direct evidence or strong corroborating evidence",
        ],
        "exclusion_criteria": [
            "Nationality of founders",
            "Country mentioned in a Bible verse",
            "Country of a partner",
            "Country of a linked organization",
            "Country appearing somewhere on the webpage without context",
        ],
        "examples": [
            {"valid": "Zimbabwe", "for_entity": "ZERA"},
            {"valid": "Zimbabwe", "for_entity": "Theotechnic College"},
            {"invalid": "Mars", "reason": "Not a valid country in ontology"},
            {"invalid": "2 Timothy 2:15", "reason": "Bible verse reference, not a country"},
        ],
        "ontology_constraints": lambda: list(get_ontology().countries),
        "null_behavior": "OPTIONAL - use None if evidence does not support country identification",
        "max_length": 100,
        "traceability": "REQUIRED - must be traceable to evidence",
    },
    "sector": {
        "meaning": "The primary economic/functional sector in which the entity operates. Answers: What broad domain does this entity operate in?",
        "question": "What is the primary sector/industry of this entity?",
        "allowed_source": "Evidence explicitly stating sector, industry, or domain of operation",
        "inclusion_criteria": [
            "Valid sector from ATIS ontology",
            "Primary economic/functional domain",
            "Supported by evidence of entity's actual activities",
        ],
        "exclusion_criteria": [
            "Keywords found on page without context",
            "Random ontology values",
            "Industry mentioned in a program description",
            "Word found on page without sector context",
        ],
        "examples": [
            {"valid": "Education Sector", "for_entity": "Theotechnic College"},
            {"valid": "Energy Sector", "for_entity": "ZERA"},
            {"invalid": "Power", "reason": "Keyword collision without context - 'Power' appears in many contexts"},
            {"invalid": "Comprehensive", "reason": "Adjective, not a sector"},
        ],
        "ontology_constraints": lambda: list(get_ontology().sectors),
        "null_behavior": "OPTIONAL - use None if evidence does not support sector identification",
        "max_length": 100,
        "traceability": "REQUIRED - must be traceable to evidence",
    },
    "status": {
        "meaning": "The current operational state of the entity.",
        "question": "What is the current operational status of this entity?",
        "allowed_source": "Evidence explicitly stating operational status",
        "inclusion_criteria": [
            "Valid status from ATIS ontology",
            "Concise canonical state",
            "Converted from evidence (e.g., 'Now Open!' -> 'Active')",
        ],
        "exclusion_criteria": [
            "Webpage content",
            "Sentences",
            "Punctuation-heavy prose",
            "CTA language",
            "Marketing text",
        ],
        "examples": [
            {"valid": "Active", "for_entity": "ZERA"},
            {"valid": "Operational", "for_entity": "Theotechnic College"},
            {"invalid": "Now Open! All applicants will be placed on a prospective list", "reason": "Webpage content, not canonical status"},
            {"invalid": "STUDENTSYour Journey of Faith and Learning Begins Here", "reason": "Navigation/fragment, not status"},
        ],
        "ontology_constraints": lambda: list(get_ontology().statuses),
        "null_behavior": "OPTIONAL - use None if evidence does not support status identification",
        "max_length": 50,
        "traceability": "REQUIRED - must be traceable to evidence",
    },
    "summary": {
        "meaning": "A concise identity statement about the entity. Answers ONLY: (1) What is this entity? (2) What does it primarily do? (3) What is its primary distinguishing function/relevance?",
        "question": "What is this entity and what does it primarily do?",
        "allowed_source": "Evidence explicitly describing the entity's identity, function, and relevance",
        "inclusion_criteria": [
            "Concise identity statement",
            "Answers: What is this entity?",
            "Answers: What does it primarily do?",
            "Answers: What is its primary distinguishing function/relevance?",
            "Every sentence directly describes the target entity",
            "Factual statements traceable to accepted evidence claims",
            "Appropriate use of [[backlinks]] to other entities",
        ],
        "exclusion_criteria": [
            "Page summaries",
            "Research reports",
            "Histories of every activity",
            "Lists of programs",
            "Marketing descriptions",
            "Mission statements",
            "Collections of evidence",
            "Biographies of related organizations",
            "Dumps of claims",
            "Navigation text",
            "Webpage boilerplate",
            "CTA language",
            "Unrelated entity information",
            "Unsupported claims",
            "Repetition",
        ],
        "examples": [
            {
                "valid": "[[Theotechnic College]] is a Christian educational institution focused on theological education, practical ministry training, and vocational development. It combines biblical studies with practical skills intended to prepare students for ministry, entrepreneurship, and community service.",
                "for_entity": "Theotechnic College"
            },
            {
                "valid": "[[ZERA]] is the Zimbabwe Energy Regulatory Authority, a statutory body responsible for regulating the energy sector in Zimbabwe. It oversees electricity generation, transmission, distribution, and pricing.",
                "for_entity": "ZERA"
            },
            {
                "invalid": "Now Open! All applicants will be placed on a prospective list... [thousands of words]",
                "reason": "Webpage content dump, not concise identity statement"
            },
            {
                "invalid": "Theotechnic College. STUDENTSYour Journey of Faith and Learning Begins Here...",
                "reason": "Contains navigation/fragment text"
            },
        ],
        "ontology_constraints": None,
        "null_behavior": "REQUIRED - must never be null, but can be minimal",
        "max_length": 2000,  # ~500 words
        "max_sentences": 4,
        "traceability": "REQUIRED - every factual statement must be traceable to evidence claim IDs",
    },
    "relationships": {
        "meaning": "A meaningful, explicit connection between the target entity and ANOTHER entity.",
        "question": "What explicit relationships does this entity have with other entities?",
        "allowed_source": "Evidence explicitly stating a relationship between target and another entity",
        "inclusion_criteria": [
            "Meaningful, explicit connection",
            "Target is a real entity",
            "Valid relationship predicate from ontology",
            "Format: predicate::[[TargetEntity]]",
            "Supported by evidence",
        ],
        "exclusion_criteria": [
            "Adjectives as targets",
            "Sentence fragments as targets",
            "CTA text as targets",
            "Navigation text as targets",
            "Generic statements without explicit relationship",
            "Inferred relationships (must be explicit in evidence)",
        ],
        "examples": [
            {"valid": ["supported_by::[[ACTIVE Ministry]]"], "for_entity": "Theotechnic College"},
            {"valid": ["regulates::[[Energy Sector]]"], "for_entity": "ZERA"},
            {"invalid": ["provides::[[Comprehensive]]"], "reason": "'Comprehensive' is an adjective, not an entity"},
            {"invalid": ["provides::[[Foundational]]"], "reason": "'Foundational' is an adjective, not an entity"},
            {"invalid": ["provides::[[Quality]]"], "reason": "'Quality' is an adjective, not an entity"},
            {"invalid": ["member_of::[[College Family Dedicates Themselves To The Great Commission...]]"], "reason": "Sentence fragment as target"},
        ],
        "ontology_constraints": lambda: list(get_ontology().relationship_predicates),
        "null_behavior": "OPTIONAL - empty list if no relationships found",
        "max_length_per_item": 200,
        "traceability": "REQUIRED - each relationship must have supporting evidence",
        "validation_rules": {
            "predicate": "Must be in ontology relationship_predicates",
            "target": "Must be a valid backlink target (resolvable entity or ontology concept)",
        },
    },
    "associations": {
        "meaning": "Meaningful conceptual/entity links that are useful to the knowledge graph but do not fit the stronger relationship categories.",
        "question": "What conceptual or entity links does this entity have that don't fit relationship categories?",
        "allowed_source": "Evidence explicitly stating an association between target and another entity/concept",
        "inclusion_criteria": [
            "Meaningful conceptual/entity link",
            "Target is a meaningful canonical entity or ontology concept",
            "Valid association predicate from ontology",
            "Format: predicate::[[Target]]",
            "Supported by evidence",
        ],
        "exclusion_criteria": [
            "Sentence fragments inside backlinks",
            "Adjectives as targets",
            "Unresolvable targets",
            "No evidence support",
        ],
        "examples": [
            {"valid": ["related_to::[[Vocational Training]]"], "for_entity": "Theotechnic College"},
            {"valid": ["part_of::[[ACTIVE Ministry]]"], "for_entity": "Theotechnic College"},
            {"invalid": ["related_to::[[College Family Dedicates Themselves To The Great Commission...]]"], "reason": "Sentence fragment as target"},
            {"invalid": ["connected_to::[[Comprehensive]]"], "reason": "Adjective as target"},
        ],
        "ontology_constraints": lambda: list(get_ontology().association_predicates),
        "null_behavior": "OPTIONAL - empty list if no associations found",
        "max_length_per_item": 200,
        "traceability": "REQUIRED - each association must have supporting evidence",
        "validation_rules": {
            "predicate": "Must be in ontology association_predicates",
            "target": "Must be a valid backlink target (resolvable entity or ontology concept)",
        },
    },
    "sources": {
        "meaning": "List of source URLs that provided evidence for this node.",
        "question": "What sources were used to create this node?",
        "allowed_source": "URLs that were actually retrieved and verified",
        "inclusion_criteria": [
            "URLs that were actually retrieved",
            "URLs that provided usable evidence",
        ],
        "exclusion_criteria": [
            "Manufactured URLs",
            "URLs that were never retrieved",
            "URLs that were never verified",
        ],
        "examples": [
            {"valid": ["https://www.theotec.org/about", "https://www.activeministry.org/theotechnic"]},
            {"invalid": [], "reason": "No sources provided"},
        ],
        "ontology_constraints": None,
        "null_behavior": "REQUIRED - must have at least one source",
        "traceability": "IMPLICIT - sources are the provenance",
    },
}


# =============================================================================
# Entity-Centric Evidence Extraction Prompt
# =============================================================================

ENTITY_CENTRIC_EVIDENCE_EXTRACTION_PROMPT_TEMPLATE = """You are NORA's entity-centric evidence extraction engine.

## CORE PRINCIPLE

You are extracting evidence about **ONE TARGET ENTITY**.

**TARGET ENTITY:**
{{target_entity}}

Your task is NOT to:
- Summarize the webpage
- Extract everything interesting from the webpage
- Preserve all text
- Treat all text on a page about the target as evidence about the target

Your task IS to:
- Identify **ONLY** factual statements that establish something about the target entity
- OR identify factual statements that establish a **concrete relationship** involving the target entity

## THE FUNDAMENTAL DISTINCTION

A webpage may contain information about many entities.
**Do NOT attribute information to the target merely because it appears on the same webpage.**

For every candidate fact, ask:
1. **Is the target entity explicitly the subject?**
   - If YES: This is DIRECT evidence about the target
   - If NO: Continue to question 2

2. **Does the statement establish a concrete relationship involving the target?**
   - If YES: This is RELATED evidence (may support a relationship field)
   - If NO: Continue to question 3

3. **If neither is true: DISCARD IT.**

## RELEVANCE CLASSIFICATION

### DIRECT
The evidence explicitly describes the target entity.

**Examples:**
- "{{target_entity}} offers a Bachelor of Arts in Biblical Studies with Vocational Pathways."
- "{{target_entity}} is a Christian educational institution."
- "{{target_entity}} was established in 2020."

**These are DIRECT evidence about {{target_entity}}.**

### RELATED
The evidence describes another entity that has a meaningful relationship with the target.

**Examples:**
- "ACTIVE Ministry provides operational and strategic support to {{target_entity}}."
- "{{target_entity}} operates under the authority of ZERA."

**These are RELATED evidence.**
They may support relationships like:
- `supported_by::[[ACTIVE Ministry]]`
- `regulated_by::[[ZERA]]`

But they should NOT automatically become part of {{target_entity}}'s general summary.

### IRRELEVANT
Anything that does NOT materially establish a fact about the target or a meaningful relationship involving the target.

**DISCARD these examples:**
- Navigation: "Home", "About", "Programs", "Apply Now", "Contact"
- Marketing slogans: "Join us today!", "Discover your future!", "Take the first step!"
- Footer text: "Copyright 2024", "Privacy Policy", "Terms of Service"
- Generic institutional language: "Welcome to our website", "About Us", "Our Mission"
- Boilerplate: "Page not found", "Loading...", "Under Construction"
- Duplicated text: Repeated content across pages
- Testimonials: "I loved this program!" (unless directly relevant)
- Unrelated organizations: Information about other organizations not connected to target
- Generic statistics: "100% satisfaction", "500+ students" (without clear attribution)
- Fragments: "Our students", "The college", "We provide"
- Adjectives without factual meaning: "Comprehensive", "Foundational", "Quality" (as standalone)
- Incomplete sentences: "And then we...", "The best..."
- Webpage formatting artifacts: HTML tags, CSS classes, JavaScript code
- Scripture quotations: "2 Timothy 2:15" (unless they establish an actual institutional fact)
- Contact instructions: "Call us at 555-1234", "Email info@org.com"

## EVIDENCE MUST BE ATOMIC

Do NOT pass giant webpage sections as "evidence."

**BAD:**
```
{
  "evidence": "The entire 30,000 character webpage..."
}
```

**GOOD:**
```json
{
  "subject": "{{target_entity}}",
  "predicate": "offers",
  "object": "theological and vocational education",
  "passage": "The college combines theological studies with practical vocational training.",
  "evidence_type": "SUMMARY",
  "relevance": "DIRECT",
  "source_url": "https://example.org",
  "confidence": 0.9
}
```

**Each claim must answer:**
> What exactly does this evidence prove about the target entity?

If the answer is unclear, **DISCARD IT.**

## FIELD SEMANTIC DEFINITIONS

These are the authoritative definitions for each ATIS node field:

{% for field_name, field_def in field_semantic_definitions.items() %}
### `{{field_name}}`

**Meaning:** {{field_def.meaning}}

**Question:** {{field_def.question}}

**Allowed Source:** {{field_def.allowed_source}}

**Inclusion Criteria:**
{{ '
'.join(f'- {c}' for c in field_def.inclusion_criteria) }}

**Exclusion Criteria:**
{{ '
'.join(f'- {c}' for c in field_def.exclusion_criteria) }}

**Examples:**
{% for example in field_def.examples %}
- {{ 'VALID' if 'valid' in example else 'INVALID' }}: {{ example.get('valid', example.get('invalid', '')) }}
  {% if 'for_entity' in example %}(for: {{example.for_entity}}){% endif %}
  {% if 'reason' in example %} Reason: {{example.reason}}{% endif %}
{% endfor %}

**Ontology Constraints:**
{% if field_def.ontology_constraints %}
{{ field_def.ontology_constraints() }}
{% else %}
None (must be proper value)
{% endif %}

**Null Behavior:** {{field_def.null_behavior}}

**Traceability:** {{field_def.traceability}}

{% endfor %}

## BACKLINK SEMANTICS

Every `[[...]]` represents a graph edge to a real node/concept.

**VALID targets:**
- Known canonical entities: `[[ACTIVE Ministry]]`, `[[ZERA]]`
- Valid ontology concepts: `[[Energy Sector]]`, `[[Education Sector]]`
- Proper nouns: `[[Theotechnic College]]`

**INVALID targets (NEVER use these):**
- Sentences: `[[College Family Dedicates Themselves To The Great Commission...]]`
- Phrases: `[[Comprehensive Education]]` (unless it's a known entity)
- Adjectives: `[[Comprehensive]]`, `[[Foundational]]`, `[[Quality]]`
- Slogans: `[[Now Open!]]`
- Webpage copy: `[[STUDENTSYour Journey...]]`
- CTA text: `[[Apply Now]]`
- Arbitrary noun phrases: `[[the provision of]]`

**Rule:** If you cannot resolve the target to a legitimate entity, **do NOT create the backlink.**

## ONTOLOGY CONSTRAINTS

**Entity Types:** {{ ontology.all_entity_types | join(', ') }}

**Relationship Predicates:** {{ ontology.relationship_predicates | join(', ') }}

**Association Predicates:** {{ ontology.association_predicates | join(', ') }}

**Sectors:** {{ ontology.sectors | join(', ') }}

**Countries:** {{ ontology.countries | join(', ') }}

**Statuses:** {{ ontology.statuses | join(', ') }}

**Use ONLY these canonical values.**
**Do NOT invent values.**
**Do NOT use values not in the ontology.**

## OUTPUT REQUIREMENTS

Return a JSON object with this structure:

```json
{
  "target_entity": "{{target_entity}}",
  "entity_match_verified": true,
  "atomic_claims": [
    {
      "subject": "{{target_entity}}",
      "predicate": "<predicate_from_ontology>",
      "object": "<target_or_value>",
      "claim_text": "<normalized_claim_text>",
      "evidence_passage": "<EXACT_VERBATIM_QUOTE_FROM_SOURCE>",
      "source_url": "<source_url>",
      "source_title": "<source_title>",
      "relevance": "DIRECT|RELATED",
      "evidence_type": "FACT|ATTRIBUTE|RELATIONSHIP|ASSOCIATION|SUMMARY",
      "confidence": 0.0-1.0,
      "quality_status": "VALID|INVALID|NEEDS_REVIEW"
    }
  ],
  "discarded_count": <number_of_irrelevant_items>,
  "discarded_reasons": [
    {"text": "<sample_of_discarded_text>", "reason": "<reason_for_discard>"}
  ]
}
```

## QUALITY CHECKS (APPLIED BY APPLICATION, NOT BY YOU)

The application will reject claims where:
- `subject` is empty or not related to target
- `predicate` is empty or not in ontology
- `object` is empty or not a valid target
- `evidence_passage` is empty or not a verbatim quote
- `source_url` is empty
- `evidence_passage` is excessively long (>1000 chars)
- `claim_text` contains CTA language
- `claim_text` contains navigation language
- `claim_text` is a sentence fragment
- `claim_text` is a Bible verse
- `claim_text` is a single letter
- `claim_text` has no identifiable factual proposition

**Your confidence scores do NOT override these structural checks.**

## FINAL RULES

1. **Be conservative:** When in doubt, discard.
2. **Be explicit:** Only extract what is explicitly stated.
3. **Be atomic:** Each claim should be one specific fact.
4. **Be traceable:** Every claim must have exact source passage.
5. **Be entity-centric:** Only extract facts about the target entity.
6. **Follow ontology:** Use only canonical ontology values.
7. **Validate backlinks:** Only use resolvable entity/concept targets.

**Remember:** The goal is NOT to extract as much as possible.
The goal is to extract ONLY what is provably true about the target entity.
"""


# =============================================================================
# Field-Specific Extraction Prompts
# =============================================================================

FIELD_SPECIFIC_EXTRACTION_PROMPTS: Dict[str, str] = {
    "entity_type": """Extract the entity_type for {{target_entity}}.

**Definition:** The broad ontological class. Answers: "What KIND of thing is this?"

**Ontology Values:** {{ ontology.all_entity_types | join(', ') }}

**Rules:**
- Use ONLY values from the ontology above
- Return the EXACT ontology value (case-sensitive)
- If evidence does NOT explicitly support a classification, return null (do NOT invent)
- Be CONSERVATIVE: only extract what is EXPLICITLY stated

**Evidence to look for:**
- "{{target_entity}} is a [entity_type]"
- "{{target_entity}} is an [entity_type]"
- "[entity_type] called {{target_entity}}"
- Authoritative descriptions identifying the entity type

**Return:** JSON with {"entity_type": "<value>" or null, "evidence": "<exact_quote>" or null}
""",
    
    "sector": """Extract the sector for {{target_entity}}.

**Definition:** The primary economic/functional sector. Answers: "What broad domain does this entity operate in?"

**Ontology Values:** {{ ontology.sectors | join(', ') }}

**Rules:**
- Use ONLY values from the ontology above
- Return the EXACT ontology value (case-sensitive)
- Do NOT use keyword collisions (e.g., "power" in text does NOT mean sector = "Power")
- Evidence must explicitly support the sector classification
- If evidence does NOT support a sector, return null

**Evidence to look for:**
- "{{target_entity}} operates in the [sector]"
- "{{target_entity}} is a [sector] organization"
- "[sector] regulator: {{target_entity}}"
- Authoritative statements about the entity's domain

**Return:** JSON with {"sector": "<value>" or null, "evidence": "<exact_quote>" or null}
""",
    
    "country": """Extract the country for {{target_entity}}.

**Definition:** The primary country associated with the entity as an organization/institution.

**Ontology Values:** {{ ontology.countries | join(', ') }}

**Rules:**
- Use ONLY values from the ontology above
- Return the EXACT ontology value (case-sensitive)
- This is NOT: nationality of founders, country in Bible verse, country of partner
- Must be direct evidence or strong corroborating evidence
- If evidence does NOT support a country, return null

**Evidence to look for:**
- "{{target_entity}} is located in [country]"
- "{{target_entity}} is based in [country]"
- "{{target_entity}} operates in [country]"
- "Headquarters: [city], [country]"
- Authoritative location information

**Return:** JSON with {"country": "<value>" or null, "evidence": "<exact_quote>" or null}
""",
    
    "status": """Extract the status for {{target_entity}}.

**Definition:** The current operational state.

**Ontology Values:** {{ ontology.statuses | join(', ') }}

**Rules:**
- Use ONLY values from the ontology above
- Return the EXACT ontology value (case-sensitive)
- Convert evidence to canonical value (e.g., "Now Open!" -> "Active")
- Evidence must support an operational state
- If evidence does NOT support a status, return null

**Evidence to look for:**
- "{{target_entity}} is [status]"
- "{{target_entity}} was [status]"
- "Status: [status]"
- "Now Open! Applications are being accepted." -> "Active"
- Authoritative status statements

**Return:** JSON with {"status": "<value>" or null, "evidence": "<exact_quote>" or null}
""",
    
    "summary": """Extract summary for {{target_entity}}.

**Definition:** A concise identity statement. Answers ONLY:
1. What is this entity?
2. What does it primarily do?
3. What is its primary distinguishing function/relevance?

**Rules:**
- 2-4 sentences MAXIMUM
- Every sentence must directly describe {{target_entity}}
- Every factual statement must be traceable to evidence
- NO marketing CTA, navigation text, webpage boilerplate
- Use [[backlinks]] ONLY for resolvable entities/concepts
- If a factual statement cannot be traced to evidence, EXCLUDE it

**Evidence to look for:**
- Descriptions of what the entity is
- Descriptions of what the entity does
- Descriptions of the entity's primary function/relevance

**Return:** JSON with {
  "summary": "<concise_entity-focused_summary>",
  "evidence_passages": ["<exact_quote_1>", "<exact_quote_2>"],
  "sources": ["<source_url_1>", "<source_url_2>"]
}
""",
    
    "relationships": """Extract relationships for {{target_entity}}.

**Definition:** A meaningful, explicit connection between {{target_entity}} and ANOTHER entity.

**Ontology Predicates:** {{ ontology.relationship_predicates | join(', ') }}

**Rules:**
- Target must be a REAL entity (not an adjective, phrase, or sentence)
- Predicate must be from the ontology above
- Relationship must be EXPLICITLY stated in evidence
- Do NOT infer relationships
- Format: "predicate::[[TargetEntity]]"
- If target cannot be resolved, do NOT create the relationship

**Evidence to look for:**
- "{{target_entity}} [predicate] [target]"
- "[subject] [predicate] {{target_entity}}"
- Explicit relationship statements

**Valid Examples:**
- "supported_by::[[ACTIVE Ministry]]"
- "regulated_by::[[ZERA]]"
- "operates::[[Theotechnic College]]"

**Invalid Examples:**
- "provides::[[Comprehensive]]" (Comprehensive is an adjective, not an entity)
- "provides::[[Foundational]]" (Foundational is an adjective, not an entity)
- "provides::[[Quality]]" (Quality is an adjective, not an entity)
- "member_of::[[College Family Dedicates Themselves...]]" (Sentence fragment as target)

**Return:** JSON with {
  "relationships": ["predicate::[[Target]]", ...],
  "evidence": [{"relationship": "...", "passage": "...", "source_url": "..."}, ...]
}
""",
    
    "associations": """Extract associations for {{target_entity}}.

**Definition:** Meaningful conceptual/entity links that don't fit relationship categories.

**Ontology Predicates:** {{ ontology.association_predicates | join(', ') }}

**Rules:**
- Target must be a meaningful canonical entity or ontology concept
- Predicate must be from the ontology above
- Association must be supported by evidence
- NEVER put sentence fragments inside backlinks
- If target cannot be resolved, do NOT create the association

**Valid Examples:**
- "related_to::[[Vocational Training]]"
- "part_of::[[ACTIVE Ministry]]"
- "connected_to::[[Christian Education]]"

**Invalid Examples:**
- "related_to::[[College Family Dedicates Themselves...]]" (Sentence fragment)
- "connected_to::[[Comprehensive]]" (Adjective)
- "member_of::[[the provision of]]" (Phrase)

**Return:** JSON with {
  "associations": ["predicate::[[Target]]", ...],
  "evidence": [{"association": "...", "passage": "...", "source_url": "..."}, ...]
}
""",
}


# =============================================================================
# Helper Functions
# =============================================================================

def get_field_semantic_definitions() -> Dict[str, Dict[str, Any]]:
    """Get field semantic definitions."""
    return FIELD_SEMANTIC_DEFINITIONS


def get_entity_centric_prompt(target_entity: str) -> str:
    """Get the entity-centric evidence extraction prompt for a specific entity.
    
    Args:
        target_entity: The target entity name
        
    Returns:
        Formatted prompt string
    """
    ontology = get_ontology()
    
    # Format the template with field definitions
    field_defs_list = []
    for field_name, field_def in FIELD_SEMANTIC_DEFINITIONS.items():
        field_defs_list.append(f"### `{field_name}`\n\n")
        field_defs_list.append(f"**Meaning:** {field_def['meaning']}\n\n")
        field_defs_list.append(f"**Question:** {field_def['question']}\n\n")
        field_defs_list.append(f"**Allowed Source:** {field_def['allowed_source']}\n\n")
        
        if field_def.get('inclusion_criteria'):
            field_defs_list.append("**Inclusion Criteria:\n")
            for criterion in field_def['inclusion_criteria']:
                field_defs_list.append(f"- {criterion}\n")
            field_defs_list.append("\n")
        
        if field_def.get('exclusion_criteria'):
            field_defs_list.append("**Exclusion Criteria:\n")
            for criterion in field_def['exclusion_criteria']:
                field_defs_list.append(f"- {criterion}\n")
            field_defs_list.append("\n")
        
        if field_def.get('examples'):
            field_defs_list.append("**Examples:\n")
            for example in field_def['examples']:
                if 'valid' in example:
                    field_defs_list.append(f"- VALID: {example['valid']}")
                    if 'for_entity' in example:
                        field_defs_list.append(f" (for: {example['for_entity']})")
                    field_defs_list.append("\n")
                elif 'invalid' in example:
                    field_defs_list.append(f"- INVALID: {example['invalid']}")
                    if 'reason' in example:
                        field_defs_list.append(f" Reason: {example['reason']}")
                    field_defs_list.append("\n")
            field_defs_list.append("\n")
        
        # Ontology constraints
        ontology_vals = None
        if field_def.get('ontology_constraints'):
            try:
                ontology_vals = field_def['ontology_constraints']()
            except:
                pass
        
        if ontology_vals:
            field_defs_list.append(f"**Ontology Constraints:** {', '.join(ontology_vals)}\n\n")
        else:
            field_defs_list.append("**Ontology Constraints:** None (must be proper value)\n\n")
        
        field_defs_list.append(f"**Null Behavior:** {field_def.get('null_behavior', 'OPTIONAL')}\n\n")
        field_defs_list.append(f"**Traceability:** {field_def.get('traceability', 'REQUIRED')}\n\n")
    
    field_semantics_section = '\n'.join(field_defs_list)
    
    # Format ontology lists
    ontology_section = f"""
**Entity Types:** {', '.join(sorted(ontology.all_entity_types))}

**Relationship Predicates:** {', '.join(sorted(ontology.relationship_predicates))}

**Association Predicates:** {', '.join(sorted(ontology.association_predicates))}

**Sectors:** {', '.join(sorted(ontology.sectors))}

**Countries:** {', '.join(sorted(ontology.countries))}

**Statuses:** {', '.join(sorted(ontology.statuses))}
"""
    
    # Build the full prompt
    prompt = ENTITY_CENTRIC_EVIDENCE_EXTRACTION_PROMPT_TEMPLATE
    prompt = prompt.replace('{{target_entity}}', target_entity)
    prompt = prompt.replace('{{ field_semantic_definitions }}', field_semantics_section)
    prompt = prompt.replace('{{ ontology.all_entity_types }}', ', '.join(sorted(ontology.all_entity_types)))
    prompt = prompt.replace('{{ ontology.relationship_predicates }}', ', '.join(sorted(ontology.relationship_predicates)))
    prompt = prompt.replace('{{ ontology.association_predicates }}', ', '.join(sorted(ontology.association_predicates)))
    prompt = prompt.replace('{{ ontology.sectors }}', ', '.join(sorted(ontology.sectors)))
    prompt = prompt.replace('{{ ontology.countries }}', ', '.join(sorted(ontology.countries)))
    prompt = prompt.replace('{{ ontology.statuses }}', ', '.join(sorted(ontology.statuses)))
    
    return prompt


def get_field_specific_prompt(field_name: str, target_entity: str) -> str:
    """Get a field-specific extraction prompt.
    
    Args:
        field_name: The field to extract
        target_entity: The target entity name
        
    Returns:
        Formatted prompt string for the specific field
    """
    if field_name not in FIELD_SPECIFIC_EXTRACTION_PROMPTS:
        return ""
    
    ontology = get_ontology()
    prompt_template = FIELD_SPECIFIC_EXTRACTION_PROMPTS[field_name]
    
    # Replace placeholders
    prompt = prompt_template.replace('{{target_entity}}', target_entity)
    
    # Replace ontology placeholders
    if '{{ ontology.all_entity_types }}' in prompt:
        prompt = prompt.replace('{{ ontology.all_entity_types }}', ', '.join(sorted(ontology.all_entity_types)))
    if '{{ ontology.relationship_predicates }}' in prompt:
        prompt = prompt.replace('{{ ontology.relationship_predicates }}', ', '.join(sorted(ontology.relationship_predicates)))
    if '{{ ontology.association_predicates }}' in prompt:
        prompt = prompt.replace('{{ ontology.association_predicates }}', ', '.join(sorted(ontology.association_predicates)))
    if '{{ ontology.sectors }}' in prompt:
        prompt = prompt.replace('{{ ontology.sectors }}', ', '.join(sorted(ontology.sectors)))
    if '{{ ontology.countries }}' in prompt:
        prompt = prompt.replace('{{ ontology.countries }}', ', '.join(sorted(ontology.countries)))
    if '{{ ontology.statuses }}' in prompt:
        prompt = prompt.replace('{{ ontology.statuses }}', ', '.join(sorted(ontology.statuses)))
    
    return prompt


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "FIELD_SEMANTIC_DEFINITIONS",
    "ENTITY_CENTRIC_EVIDENCE_EXTRACTION_PROMPT_TEMPLATE",
    "FIELD_SPECIFIC_EXTRACTION_PROMPTS",
    "get_field_semantic_definitions",
    "get_entity_centric_prompt",
    "get_field_specific_prompt",
]
