# Phase 4: Frontend + Dead Code Cleanup - Research

**Researched:** 2026-02-18
**Domain:** React rendering efficiency, accessibility, dead code removal
**Confidence:** HIGH

## Summary

This phase is a stabilization pass -- no new features, just fixing rendering inefficiencies, adding accessibility attributes, and removing dead code across frontend and backend. The codebase is a React 18 + TypeScript + Vite frontend with a Python FastAPI backend and a Python eval runner.

The main frontend issues are: (1) message list keyed by array index causing unnecessary remounts, (2) `setInterval`-based polling in `useIngestionTask` that can overlap and leak, (3) an inline `onClose` callback in ChatPage creating a new reference every render causing `useEffect` churn in SourceViewer, and (4) missing `aria-label` attributes on most interactive elements. Dead code spans a React component (`CitationLink.tsx`), a backend function (`require_auth`), and an eval function with a potential division-by-zero. The `orig_idx` variable in `openai_embedder.py` has already been removed in a prior change. The `Content-Type: application/json` header is sent on all `request()` calls including GET requests.

**Primary recommendation:** Address each requirement as a focused, testable change -- most are single-file edits. The `onClose` useCallback fix and the `setInterval` to `setTimeout` conversion are the most architecturally significant changes.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Accessibility labels: Scope is all interactive elements project-wide (not just the 3 listed pages). Audit every page/component for missing aria-labels. The 3 listed pages (SearchFilters, DocumentsPage, ChatPage) are minimum -- extend to all others.
- Chat message keys: Smart scroll behavior: auto-scroll if user is at bottom, stay put if user scrolled up (Slack/Discord pattern). Check codebase for existing message IDs before deciding key strategy. If backend IDs exist, use those; otherwise generate stable client-side keys.
- Polling lifecycle: Switch from setInterval to chained setTimeout (per requirement FE-03). Exponential backoff on consecutive errors, reset interval on success. Clean up on unmount -- no leaked timers.

### Claude's Discretion
- Aria-label text style (action-based vs name-based, per element)
- Background tab polling behavior (pause vs continue)
- Exact exponential backoff parameters (initial interval, max interval, multiplier)
- Message key generation strategy if no backend IDs exist
- Smart scroll implementation details (threshold for "at bottom" detection)

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FE-01 | React message list uses stable keys instead of array index | Messages lack unique IDs from backend; `ChatMessage` type has no `id` field. Need client-side stable key generation -- see Architecture Patterns section |
| FE-02 | useCallback added for onClose in SourceViewer to prevent effect churn | ChatPage line 49 passes `() => setViewingSegmentId(null)` inline, recreating reference every render. SourceViewer's Escape-key effect depends on `onClose` -- see Code Examples section |
| FE-03 | useIngestionTask uses chained setTimeout instead of setInterval | Current code uses `setInterval` (line 38) with potential overlap if API calls take >1500ms. Need chained setTimeout with exponential backoff -- see Architecture Patterns section |
| FE-04 | Dead CitationLink.tsx component removed | File exists at `web/src/components/CitationLink.tsx`. Not imported anywhere in codebase (verified via grep). Safe to delete. |
| FE-05 | Dead require_auth function removed from auth.py | Defined at `src/pam/api/auth.py:85-94`. Not imported by any route. Only referenced in its own test class `TestRequireAuth` at `tests/test_api/test_auth.py:258-280`. Both definition and tests must be removed. |
| FE-06 | Unused orig_idx variable removed from openai_embedder.py | **Already removed** -- verified via grep, not present in current `src/pam/ingestion/embedders/openai_embedder.py`. This requirement is pre-satisfied. |
| FE-07 | aria-label added to interactive elements in SearchFilters, DocumentsPage, ChatPage | Currently only 3 aria-labels exist in entire frontend: CodeBlock "Copy code", SourceViewer "Close", App "Open menu". Full audit shows 15+ interactive elements missing labels -- see Accessibility Audit section |
| FE-08 | Division by zero guarded in eval print_summary | `eval/run_eval.py` `print_summary` function has conditional guards on most divisions but relies on Python ternary precedence for correctness. Should be hardened with explicit parentheses and an early return for empty `questions` -- see Code Examples section |
| FE-09 | Content-Type: application/json removed from GET requests in client.ts | The `request()` function at line 173-174 unconditionally sets `Content-Type: application/json` for all calls. GET requests (`listDocuments`, `getTaskStatus`, `listTasks`, `getSegment`, `getStats`, `getAuthStatus`, `getMe`) inherit this. Fix: only set Content-Type when body is present -- see Code Examples section |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React | 18.3.1 | UI framework | Already in use |
| TypeScript | 5.6.3 | Type safety | Already in use |
| Vite | 6.0.3 | Build tooling | Already in use |
| Vitest | 4.0.18 | Unit testing | Already in use |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| @testing-library/react | 16.3.2 | React hook/component testing | Already in use for useChat tests |

### Alternatives Considered
No new libraries needed. This phase is entirely about fixing existing code.

## Architecture Patterns

### Pattern 1: Stable Message Keys Without Backend IDs

**What:** The `ChatMessage` type has no `id` field. Messages are stored in a `useState<ChatMessage[]>` array in `useChat.ts`. The current rendering in `ChatInterface.tsx` line 68-75 uses `key={i}` (array index).

**Why array-index keys are bad:** When a message is inserted or the array is reordered, React cannot tell which DOM node corresponds to which message. It will unmount and remount, losing focus, scroll position, and animation state.

**Strategy: Generate stable IDs at message creation time.** Since the backend does not provide message IDs (the `ChatMessage` interface only has `role`, `content`, `citations`), generate a unique ID client-side when each message is added to the array.

**Recommended approach:**
1. Extend `ChatMessage` type with an optional `id: string` field.
2. In `useChat.ts`, assign `id: crypto.randomUUID()` at the point where messages are created (both user messages and assistant placeholder messages).
3. In `ChatInterface.tsx`, use `msg.id` as the React key instead of `i`.

`crypto.randomUUID()` is available in all modern browsers and is the simplest approach. No external library needed.

**Smart scroll behavior (user decision):**
The current code uses `bottomRef.current?.scrollIntoView({ behavior: "smooth" })` on every `[messages, isStreaming]` change, which forces scroll to bottom even if the user has scrolled up to read history.

Implement the Slack/Discord pattern:
- Track whether user is "at the bottom" of the scroll container.
- Only auto-scroll when at the bottom; preserve position when scrolled up.
- Threshold: consider "at bottom" if within ~50px of the scroll end (accounts for rounding and subpixel rendering).
- Use `scrollHeight - scrollTop - clientHeight <= threshold` check.

### Pattern 2: Chained setTimeout with Exponential Backoff

**What:** Replace `setInterval` polling with chained `setTimeout` to prevent overlapping requests and add error resilience.

**Current code (useIngestionTask.ts):**
```typescript
// PROBLEM: setInterval fires every 1500ms regardless of whether
// the previous request has completed. If the server is slow,
// requests stack up.
intervalRef.current = setInterval(poll, POLL_INTERVAL);
```

**Replacement pattern:**
```typescript
// Each setTimeout schedules the NEXT one only after the current
// request completes, preventing overlap.
const poll = async () => {
  try {
    const status = await getTaskStatus(taskId);
    setTask(status);
    errorCountRef.current = 0; // Reset on success
    if (status.status === "completed" || status.status === "failed") {
      setPolling(false);
      return; // Don't schedule next poll
    }
    // Schedule next poll at base interval
    timeoutRef.current = setTimeout(poll, BASE_INTERVAL);
  } catch {
    errorCountRef.current += 1;
    // Exponential backoff: 1.5s, 3s, 6s, 12s, max 30s
    const backoff = Math.min(
      BASE_INTERVAL * Math.pow(2, errorCountRef.current),
      MAX_INTERVAL
    );
    timeoutRef.current = setTimeout(poll, backoff);
  }
};
```

**Recommended backoff parameters (Claude's discretion):**
- Base interval: 1500ms (preserves current behavior on success)
- Multiplier: 2x per consecutive error
- Max interval: 30000ms (30 seconds)
- Reset: back to base interval on first success

**Background tab behavior (Claude's discretion):** Continue polling. Pausing is unnecessary complexity for an ingestion task that typically completes in seconds to minutes. The browser already throttles timers in background tabs.

### Pattern 3: useCallback for Stable Callback References

**What:** Wrap callbacks passed to child components with `useCallback` to prevent unnecessary re-renders and effect re-runs.

**Current problem in ChatPage.tsx line 49:**
```tsx
<SourceViewer
  segmentId={viewingSegmentId}
  onClose={() => setViewingSegmentId(null)}  // New function every render
/>
```

SourceViewer has `useEffect` on line 30-37 that depends on `[segmentId, onClose]`. Every parent render creates a new `onClose` reference, causing the effect to detach and reattach the keydown listener.

**Fix:** Wrap the callback in `useCallback` in ChatPage:
```tsx
const handleCloseViewer = useCallback(() => setViewingSegmentId(null), []);
// ...
<SourceViewer segmentId={viewingSegmentId} onClose={handleCloseViewer} />
```

### Anti-Patterns to Avoid
- **Index keys on dynamic lists:** Never use array index as React key when items can be added, removed, or reordered. Causes full subtree re-mount.
- **setInterval for async polling:** The callback fires on schedule regardless of whether the previous invocation completed. Use chained setTimeout instead.
- **Inline arrow functions in JSX for deps:** When a child component uses the prop in a `useEffect` dependency array, inline arrows cause the effect to re-run every parent render.

## Accessibility Audit

Complete inventory of interactive elements missing `aria-label` across all components:

### ChatPage.tsx
| Element | Line | Current | Needed |
|---------|------|---------|--------|
| "New conversation" button | 27-34 | No aria-label | `aria-label="Start new conversation"` |

### ChatInterface.tsx
| Element | Line | Current | Needed |
|---------|------|---------|--------|
| Message input | 110-117 | `placeholder` only | `aria-label="Type a message"` |
| Stop button | 120-124 | No aria-label | `aria-label="Stop generating"` |
| Send button | 128-134 | No aria-label | `aria-label="Send message"` |

### SearchFilters.tsx
| Element | Line | Current | Needed |
|---------|------|---------|--------|
| Filter buttons (each) | 23-38 | No aria-label | `aria-label={`Filter by ${type.label}`}` with `aria-pressed={isActive}` |

### DocumentsPage.tsx
| Element | Line | Current | Needed |
|---------|------|---------|--------|
| Folder path input | 52-59 | `placeholder` only | `aria-label="Folder path to ingest"` |
| Ingest button | 61-67 | No aria-label | `aria-label="Start ingestion"` |
| Refresh button | 116-120 | No aria-label | `aria-label="Refresh document list"` |

### AdminDashboard.tsx
| Element | Line | Current | Needed |
|---------|------|---------|--------|
| Refresh button | 77-83 | No aria-label | `aria-label="Refresh dashboard"` |

### App.tsx (already has some)
| Element | Line | Current | Status |
|---------|------|---------|--------|
| Hamburger button | 106-114 | `aria-label="Open menu"` | OK |
| Sign out button | 117-122 | No aria-label | `aria-label="Sign out"` |
| Mobile overlay | 55-58 | No aria-label | `aria-label="Close menu"` (for the backdrop) |

### LoginPage.tsx
| Element | Line | Current | Status |
|---------|------|---------|--------|
| Email input | 46-53 | `htmlFor="email"` label | OK (associated via `<label>`) |
| Name input | 61-68 | `htmlFor="name"` label | OK (associated via `<label>`) |
| Submit button | 75-80 | No aria-label | Text content "Sign in" is sufficient, but consider `aria-label="Sign in"` for consistency |

### CitationTooltip.tsx
| Element | Line | Current | Needed |
|---------|------|---------|--------|
| Citation button | 37-39 | No aria-label | `aria-label={`View source: ${citation.title}`}` |

### SourceViewer.tsx (already has some)
| Element | Line | Current | Status |
|---------|------|---------|--------|
| Close button | 54-62 | `aria-label="Close"` | OK |
| Backdrop overlay | 44-47 | No aria-label | `aria-label="Close source viewer"` |

**Recommendation for aria-label style (Claude's discretion):** Use action-based labels for buttons ("Send message", "Start ingestion") and descriptive labels for inputs ("Folder path to ingest", "Type a message"). This is consistent with WCAG guidelines and the existing labels in the codebase.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Unique IDs | Custom counter/hash | `crypto.randomUUID()` | Built-in, zero deps, globally unique |
| Scroll detection | Manual scroll math | `scrollHeight - scrollTop - clientHeight` | Standard DOM API, no library needed |

**Key insight:** This phase requires no new libraries. Every fix uses existing React APIs, DOM APIs, and standard JavaScript.

## Common Pitfalls

### Pitfall 1: Stale Closure in setTimeout Chain
**What goes wrong:** The chained setTimeout callback captures stale `taskId` or state variables from the enclosing closure.
**Why it happens:** Each setTimeout callback closes over the variable values at the time it was created.
**How to avoid:** Store `taskId` in a ref or pass it as a parameter. Use refs for mutable values that the timeout needs to read.
**Warning signs:** Polling continues for a previous task after starting a new one.

### Pitfall 2: Memory Leak from Uncleared Timeout on Unmount
**What goes wrong:** Component unmounts but the setTimeout fires and calls `setState` on unmounted component.
**Why it happens:** Cleanup effect clears the ref, but a pending timeout may still fire.
**How to avoid:** Store the timeout ID in a ref and clear it in the cleanup function. Also use an `isMounted` ref or AbortController pattern.
**Warning signs:** React warning about "Can't perform a React state update on an unmounted component."

### Pitfall 3: Scroll Position Jump on Smart Scroll
**What goes wrong:** Adding smart scroll logic but checking scroll position at the wrong time (before vs after DOM update).
**Why it happens:** React batches state updates; the scroll container's dimensions change after render, not during.
**How to avoid:** Check "is at bottom" BEFORE the state update (e.g., in a ref that's updated on scroll events), then use that saved value in the `useEffect` to decide whether to auto-scroll.
**Warning signs:** Chat always scrolls to bottom, or never scrolls to bottom.

### Pitfall 4: Breaking Existing Tests When Removing Dead Code
**What goes wrong:** Removing `require_auth` from `auth.py` but forgetting to remove `TestRequireAuth` class from `tests/test_api/test_auth.py` and the import on line 17.
**Why it happens:** Dead code removal requires updating all references, including test files.
**How to avoid:** Search for all references before removing. For `require_auth`: definition (auth.py:85-94), import in test (test_auth.py:17), test class (test_auth.py:258-280).
**Warning signs:** Test imports fail, CI breaks.

### Pitfall 5: Content-Type Fix Breaking POST Requests
**What goes wrong:** Removing `Content-Type` header globally instead of conditionally, breaking POST requests that need it.
**Why it happens:** Over-broad fix that removes the header entirely instead of only for bodyless requests.
**How to avoid:** Only set `Content-Type: application/json` when `init?.body` is present (or when `init?.method` is POST/PUT/PATCH). GET/HEAD/DELETE without body should not send Content-Type.
**Warning signs:** POST requests start failing with 415 or 422 errors.

### Pitfall 6: Existing Test Assertions on Content-Type
**What goes wrong:** The existing test at `client.test.ts:42-46` ("includes Content-Type by default") asserts that `Content-Type` is always present. After the fix, this assertion will fail for GET requests.
**Why it happens:** The test was written to validate current (incorrect) behavior.
**How to avoid:** Update the test to validate the new correct behavior: Content-Type present on POST, absent on GET.
**Warning signs:** `npm test` fails after the client.ts fix.

## Code Examples

### Fix 1: Stable Message Keys (FE-01)

**Extend ChatMessage type** in `client.ts`:
```typescript
export interface ChatMessage {
  id?: string;  // Client-generated stable key
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
}
```

**Assign IDs in useChat.ts** at message creation points:
```typescript
// User message (line ~34)
const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content };

// Assistant placeholder (line ~52)
const assistantMsg: ChatMessage = { id: crypto.randomUUID(), role: "assistant", content: "", citations: [] };
```

**Use ID as key in ChatInterface.tsx** (line ~68):
```tsx
{messages.map((msg, i) => (
  <MessageBubble
    key={msg.id ?? i}  // Fallback to index for safety
    message={msg}
    // ...
  />
))}
```

### Fix 2: Smart Scroll (FE-01 related, user decision)

```typescript
// In ChatInterface.tsx
const scrollRef = useRef<HTMLDivElement>(null);
const isAtBottomRef = useRef(true);

function handleScroll() {
  const el = scrollRef.current;
  if (!el) return;
  const threshold = 50;
  isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
}

useEffect(() => {
  if (isAtBottomRef.current) {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }
}, [messages, isStreaming]);
```

### Fix 3: useCallback for onClose (FE-02)

In ChatPage.tsx:
```typescript
import { useCallback, useState } from "react";
// ...
const handleCloseViewer = useCallback(() => setViewingSegmentId(null), []);
// ...
<SourceViewer segmentId={viewingSegmentId} onClose={handleCloseViewer} />
```

### Fix 4: Content-Type Only on Body Requests (FE-09)

In `client.ts`, modify the `request()` function:
```typescript
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...((init?.headers as Record<string, string>) || {}),
  };
  // Only set Content-Type when there's a body (POST, PUT, PATCH)
  if (init?.body) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
  }
  if (authToken) {
    headers["Authorization"] = `Bearer ${authToken}`;
  }
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers,
  });
  // ... rest unchanged
}
```

### Fix 5: Division-by-Zero Guard in print_summary (FE-08)

In `eval/run_eval.py`, add early return:
```python
def print_summary(eval_results: dict) -> None:
    questions = eval_results["questions"]
    total = len(questions)

    if total == 0:
        print("\n" + "=" * 72)
        print("EVALUATION SUMMARY")
        print("=" * 72)
        print("\nNo questions to evaluate.")
        print("=" * 72)
        return
    # ... rest of function unchanged, total is guaranteed > 0
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `setInterval` for polling | Chained `setTimeout` | Best practice since React hooks | Prevents overlapping requests |
| Array index as `key` | Stable unique IDs | React guidance since inception | Prevents unnecessary remounts |
| Content-Type on all requests | Content-Type only on body requests | HTTP/1.1 spec (RFC 7231) | Technically correct, reduces noise |

**Deprecated/outdated:**
- None relevant to this phase. All changes align with current React 18 best practices.

## Codebase-Specific Findings

### File Inventory for Changes

**Frontend files to modify:**
| File | Requirement | Change |
|------|-------------|--------|
| `web/src/api/client.ts` | FE-01, FE-09 | Add `id` field to ChatMessage; fix Content-Type on GET |
| `web/src/hooks/useChat.ts` | FE-01 | Assign `crypto.randomUUID()` to message IDs |
| `web/src/components/ChatInterface.tsx` | FE-01, FE-07 | Use `msg.id` as key; add smart scroll; add aria-labels |
| `web/src/pages/ChatPage.tsx` | FE-02, FE-07 | Wrap onClose in useCallback; add aria-label to "New conversation" |
| `web/src/hooks/useIngestionTask.ts` | FE-03 | Replace setInterval with chained setTimeout + backoff |
| `web/src/components/SearchFilters.tsx` | FE-07 | Add aria-label + aria-pressed to filter buttons |
| `web/src/pages/DocumentsPage.tsx` | FE-07 | Add aria-labels to input, ingest button, refresh button |
| `web/src/pages/AdminDashboard.tsx` | FE-07 | Add aria-label to refresh button |
| `web/src/App.tsx` | FE-07 | Add aria-labels to sign-out button, mobile overlay |
| `web/src/components/chat/CitationTooltip.tsx` | FE-07 | Add aria-label to citation button |
| `web/src/components/SourceViewer.tsx` | FE-07 | Add aria-label to backdrop overlay |

**Frontend files to delete:**
| File | Requirement |
|------|-------------|
| `web/src/components/CitationLink.tsx` | FE-04 |

**Backend files to modify:**
| File | Requirement | Change |
|------|-------------|--------|
| `src/pam/api/auth.py` | FE-05 | Remove `require_auth` function (lines 85-94) |
| `tests/test_api/test_auth.py` | FE-05 | Remove `require_auth` import (line 17) and `TestRequireAuth` class (lines 258-280) |
| `eval/run_eval.py` | FE-08 | Add early return guard in `print_summary` for empty questions |

**Backend files -- no change needed:**
| File | Requirement | Reason |
|------|-------------|--------|
| `src/pam/ingestion/embedders/openai_embedder.py` | FE-06 | `orig_idx` already removed in prior work |

### Test Files to Update

| Test File | Change Reason |
|-----------|---------------|
| `web/src/api/client.test.ts` | FE-09: Update "includes Content-Type by default" test; add test that GET omits Content-Type |
| `tests/test_api/test_auth.py` | FE-05: Remove `TestRequireAuth` class and import |

## Open Questions

1. **FE-06 already resolved**
   - What we know: `orig_idx` does not exist anywhere in the current codebase (verified by global grep).
   - What's unclear: Whether it was removed intentionally in a prior phase or was never present in the current form.
   - Recommendation: Mark FE-06 as pre-satisfied. No action needed. Include a verification-only step in the plan.

2. **`streamChatMessage` also sets Content-Type**
   - What we know: Line 278-280 of `client.ts` sets `Content-Type: application/json` in `streamChatMessage`, which is a POST request -- this is correct and should NOT be changed.
   - What's unclear: Nothing -- just flagging to avoid accidental over-correction.
   - Recommendation: Only modify the `request()` function for FE-09. Leave `streamChatMessage` alone.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection of all files listed above
- React 18 documentation on keys and reconciliation
- MDN Web Docs on `crypto.randomUUID()`, `setTimeout`, `scrollHeight`/`scrollTop`/`clientHeight`
- WCAG 2.1 guidelines on aria-label usage

### Secondary (MEDIUM confidence)
- HTTP/1.1 RFC 7231 Section 3.1.1.5 on Content-Type header semantics for bodyless requests

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, all existing React 18 / Vite / Vitest
- Architecture: HIGH - patterns verified by direct code reading; all changes are straightforward
- Pitfalls: HIGH - enumerated from actual code structure and test dependencies
- Accessibility audit: HIGH - complete inventory from reading every component file

**Research date:** 2026-02-18
**Valid until:** 2026-03-18 (stable -- no fast-moving dependencies)
