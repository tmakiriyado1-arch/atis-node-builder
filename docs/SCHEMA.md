# ATIS Node Builder — Schema Registry

## Overview

Schema Registry maintains machine-readable metadata about the canonical ATIS Google Sheets schema.

**NOT a replacement schema** — Just a map of the existing one.

## Purpose

- Drive field-by-field research
- Validate populated rows
- Guide CSV export
- Support schema evolution

## Structure (TODO)

Will encode:
- Column names (exact from Google Sheets)
- Data types (string, list, date, etc.)
- Entity-bearing fields (for backlinking)
- Researchable fields (for query planning)
- Controlled vocabularies
- Required vs optional

## Implementation

TODO: Import actual ATIS Google Sheets schema and encode field metadata.
