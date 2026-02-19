# Milestones

## v1 Code Quality Cleanup (Shipped: 2026-02-19)

**Phases completed:** 5 phases, 10 plans
**Timeline:** 3 days (2026-02-16 → 2026-02-18)
**Files modified:** 99 (+3,280 / -3,795 lines)
**Git range:** `44a9029..e786c9a`

**Key accomplishments:**
1. Migrated all service singletons to FastAPI lifespan + app.state — eliminated module-level globals in deps.py
2. Added database indexes and constraints via concurrent migration (content_hash, FK indexes, role CHECK)
3. Replaced BaseHTTPMiddleware with pure ASGI — fixed SSE streaming, added structured error events and cursor pagination
4. Hardened agent/retrieval layer — SearchService Protocol, fixed tool schemas, SHA-256 cache keys
5. Fixed React rendering and accessibility — stable keys, smart scroll, setTimeout polling, aria-labels
6. Closed all audit gaps — cast()-based type safety, conversation_id wiring, ChatResponse alignment, dead code removal

---

