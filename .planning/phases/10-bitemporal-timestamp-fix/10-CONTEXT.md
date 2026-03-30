# Phase 10: Bi-temporal Timestamp Pipeline Fix - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire document modification timestamps (`modified_at`) through the ingestion pipeline to graph extraction, so that `add_episode()` uses the document's actual modification time as `reference_time` — not ingestion time. Closes EXTRACT-02 gap from v2.0 audit.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation details are at Claude's discretion. The success criteria from the roadmap are specific enough to guide implementation:

- **Timestamp source per connector**: Claude decides how each connector (filesystem, etc.) populates `modified_at` from available metadata
- **Existing data handling**: Claude decides whether already-ingested documents without `modified_at` need backfill or can remain as-is
- **Re-ingestion trigger**: Claude decides how `modified_at` changes interact with content-hash-based change detection
- **Fallback behavior**: Success criteria specify fallback to `datetime.now(UTC)` when `modified_at` is None — Claude handles logging/warning details
- **Timezone handling**: Claude decides normalization approach for timezone-naive vs timezone-aware timestamps
- **Database migration**: Claude decides Alembic migration strategy for adding the `modified_at` column

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. Implementation guided by the three success criteria in ROADMAP.md.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 10-bitemporal-timestamp-fix*
*Context gathered: 2026-02-22*
