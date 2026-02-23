# Phase 11: Graph Polish + Tech Debt Cleanup - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Resolve all v2.0 spec mismatches and tech debt identified by the milestone audit so the milestone can be archived cleanly. Delivers VIZ-06 (empty state), graph endpoint null guards, a lint fix (ruff B904), and SUMMARY.md frontmatter standardization. No new capabilities — strictly cleanup and polish.

</domain>

<decisions>
## Implementation Decisions

### Empty state design (VIZ-06)
- Icon + message treatment for both empty states — relevant icon above centered status text
- **"Indexing in progress" state:** Show document count pending graph sync (e.g., "5 documents awaiting graph indexing") using existing `graph_synced` data
- **"No documents" state:** Include a clickable link/button that navigates to the ingest page — reduces friction for new users
- Use the same color palette as the rest of the graph explorer — consistent with active content styling, not muted

### Graph degradation UX
- Graph nav item always visible even when Neo4j is unavailable — user clicks and sees unavailable message
- API endpoints return 503 with JSON body: `{"detail": "Graph service unavailable"}` — structured error the frontend can parse
- Manual refresh only — no auto-retry or polling. User refreshes page to check if service is back
- Frontend display approach for unavailable state: Claude's discretion based on existing error patterns

### SUMMARY frontmatter format
- `requirements_completed` field uses ID + short description pairs format:
  ```yaml
  requirements_completed:
    - id: GRAPH-01
      desc: Neo4j graph database running
  ```
- Plans with no requirement mapping use empty list: `requirements_completed: []`
- Description is a short 5-10 word summary, not full requirement text
- Field placement in frontmatter: Claude's discretion based on existing structure

### Claude's Discretion
- Exact icon choices for empty states
- Frontend error display pattern when graph service is unavailable (banner vs inline message)
- Placement of `requirements_completed` field within existing SUMMARY.md frontmatter structure
- Loading skeleton or transition animations

</decisions>

<specifics>
## Specific Ideas

- Empty states should feel like part of the graph explorer — not a separate error page
- The "indexing in progress" state should feel informative and alive (document count provides this)
- The "no documents" state should gently guide the user toward action (link to ingest)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 11-graph-polish-tech-debt*
*Context gathered: 2026-02-23*
