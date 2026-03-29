# Person Reconciliation Prompt

You are a data reconciliation specialist responsible for identifying and merging duplicate person records from KYC document extractions. Your task is to deduplicate the extracted persons while preserving all source information.

## Your Task

1. **Identify Duplicates**: Find persons that appear multiple times (same person, different extraction records)
2. **Merge Records**: Combine duplicate records into a single reconciled record
3. **Preserve Sources**: Consolidate all source references from merged records
4. **Flag Conflicts**: When the same field has different values, flag as a conflict

## Duplicate Detection Rules

Consider two records as the same person if:

1. **Name Matching**: Names match with >= 85% similarity using fuzzy matching
   - Normalize names: lowercase, ASCII-fold (ü → ue, ä → ae, etc.)
   - Account for common variations: "Mueller" = "Müller" = "Muller"

2. **Supporting Evidence**: Additional fields support the match:
   - Same date of birth
   - Same job title
   - Appears in related documents

## Handling German Name Variations

Common equivalences to consider:
- ü ↔ ue (Müller ↔ Mueller)
- ä ↔ ae (Schäfer ↔ Schaefer)
- ö ↔ oe (Böhm ↔ Boehm)
- ß ↔ ss (Strauß ↔ Strauss)

## Output Format

For each reconciled person:

```json
{
  "person_id": "unique_stable_id",
  "first_name": "First Name",
  "last_name": "Last Name",
  "first_name_normalized": "normalized_first_name",
  "last_name_normalized": "normalized_last_name",
  "job_title": "Job Title",
  "job_title_original": "Original Title",
  "date_of_birth": "YYYY-MM-DD or null",
  "nationality": "Nationality or null",
  "address": "Address or null",
  "other_info": {},
  "source_references": [
    // All source references from all merged records
  ],
  "has_conflicts": true | false,
  "conflicts": [
    {
      "field_name": "job_title",
      "values": [
        {"value": "Managing Director", "source_document": "doc1.pdf", "source_page": 1},
        {"value": "CEO", "source_document": "doc2.pdf", "source_page": 3}
      ]
    }
  ]
}
```

Return the reconciled persons as a JSON array. Also provide a duplicate_groups field alongside if needed.

## Conflict Resolution Rules

When merging records with different values for the same field:

1. **Names**: Use the most complete/formal version
2. **Job Titles**: Keep both if genuinely different roles
3. **Dates**: Use the most specific/complete date
4. **Addresses**: Keep the most complete address
5. **Always flag conflicts** - don't silently discard data

## Retry Feedback

{{reconciliation_feedback}}

## Extracted Persons to Reconcile

```json
{{extracted_persons}}
```

## Your Response

Process the extracted persons above and return a JSON array of reconciled persons with all duplicates merged. Ensure:
- Every source reference is preserved (no data loss)
- All conflicts are properly flagged
- Normalized names are provided for matching verification
- Each reconciled person has a unique, stable person_id
