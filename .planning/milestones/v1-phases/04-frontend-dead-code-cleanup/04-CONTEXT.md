# Phase 4: Frontend + Dead Code Cleanup - Context

**Gathered:** 2026-02-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix React rendering inefficiencies (stable keys, proper cleanup), add accessibility attributes to all interactive elements, and remove dead code across the full codebase. No new features — this is stabilization and cleanup of existing code.

Requirements: FE-01 through FE-09.

</domain>

<decisions>
## Implementation Decisions

### Accessibility labels
- Scope: all interactive elements project-wide (not just the 3 listed pages)
- Audit every page/component for missing aria-labels
- The 3 listed pages (SearchFilters, DocumentsPage, ChatPage) are minimum — extend to all others

### Chat message keys
- Smart scroll behavior: auto-scroll if user is at bottom, stay put if user scrolled up (Slack/Discord pattern)
- Claude should check codebase for existing message IDs before deciding key strategy
- If backend IDs exist, use those; otherwise generate stable client-side keys

### Polling lifecycle
- Switch from setInterval to chained setTimeout (per requirement FE-03)
- Exponential backoff on consecutive errors, reset interval on success
- Clean up on unmount — no leaked timers

### Claude's Discretion
- Aria-label text style (action-based vs name-based, per element)
- Background tab polling behavior (pause vs continue)
- Exact exponential backoff parameters (initial interval, max interval, multiplier)
- Message key generation strategy if no backend IDs exist
- Smart scroll implementation details (threshold for "at bottom" detection)

</decisions>

<specifics>
## Specific Ideas

- Smart scroll should feel like Slack/Discord — auto-follow when at bottom, freeze position when scrolled up
- Accessibility audit should be thorough since we're touching it anyway — no point doing half a job

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-frontend-dead-code-cleanup*
*Context gathered: 2026-02-17*
