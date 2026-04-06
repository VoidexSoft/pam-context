# PAM Context: Messaging Platform Integrations

**Date:** 2026-04-06
**Status:** Approved
**Parent spec:** [Universal Memory Layer Design](2026-03-30-universal-memory-layer-design.md)

## Vision

Extend PAM Context's reach beyond the web UI and MCP clients by adding bot integrations for messaging platforms. Users interact with PAM through natural language or slash commands in Discord and Telegram, with full access to all PAM capabilities — chat, memory, search, ingestion, and graph queries.

## Scope

**Phase 1:** Discord + Telegram
**Future:** Slack, WhatsApp (same adapter pattern)

## Requirements

| Requirement | Decision |
|-------------|----------|
| Platforms | Discord + Telegram first, extensible to others |
| Feature scope | Full PAM access (chat, memory, search, ingest, graph) |
| Authentication | Linked accounts via one-time code → existing PAM user + RBAC |
| Response handling | Configurable: split messages OR truncate-with-link (default) |
| Deployment | Separate `pam-bots` service, calls PAM REST API as a client |
| Interaction model | Natural language default + slash commands for direct actions |
| Context | DMs (private) + channels (require @mention or slash command) |

## Architecture

### Service Structure

The `pam-bots` service lives in `src/pam/bots/` within the existing package. It runs as its own process via `python -m pam.bots`, separate from the FastAPI server. It shares the same Docker image — different entrypoint.

```
                              ┌─────────────────┐
                              │   PAM REST API   │
                              │   (FastAPI)      │
                              └────────▲─────────┘
                                       │
                                  httpx (async)
                                       │
┌──────────────────────────────────────┼────────────────────────────────────┐
│                           pam-bots service                                │
│                                      │                                    │
│  ┌─────────────────┐    ┌────────────┴────────────┐    ┌──────────────┐  │
│  │ Discord Adapter  │───►                          │    │  Formatter   │  │
│  │ (discord.py)     │    │        BotCore          │───►│  (split /    │  │
│  └─────────────────┘    │  - Auth (resolve/link)   │    │   truncate)  │  │
│                          │  - Command routing       │    └──────────────┘  │
│  ┌─────────────────┐    │  - PAM API client        │                      │
│  │ Telegram Adapter │───►│  - Rate limiting         │    ┌──────────────┐  │
│  │ (python-telegram │    │  - Conversation tracking │───►│    Redis      │  │
│  │  -bot)           │    └─────────────────────────┘    │  (cache +    │  │
│  └─────────────────┘                                     │   sessions)  │  │
│                                                          └──────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
```

### File Layout

```
src/pam/bots/
├── __main__.py          # Entrypoint: starts BotCore + adapters
├── core.py              # BotCore: command routing, PAM API client, shared logic
├── config.py            # BotSettings (Pydantic Settings, from .env)
├── models.py            # BotRequest, BotResponse, BotUser, LinkSession
├── api_client.py        # Async PAM REST API client (httpx)
├── auth.py              # Account linking flow + token management
├── formatter.py         # Response formatting (split vs truncate-with-link)
├── commands/
│   ├── __init__.py
│   ├── registry.py      # Command registry (decorators + dispatch)
│   ├── chat.py          # Natural language → /api/chat
│   ├── search.py        # /search → /api/search
│   ├── memory.py        # /remember, /recall, /forget → /api/memory/*
│   ├── documents.py     # /documents, /ingest → /api/documents/*, /api/ingest/*
│   └── graph.py         # /graph → /api/graph/*
├── adapters/
│   ├── __init__.py
│   ├── base.py          # Abstract PlatformAdapter interface
│   ├── discord.py       # Discord adapter (discord.py library)
│   └── telegram.py      # Telegram adapter (python-telegram-bot library)
└── tests/
    ├── test_core.py
    ├── test_formatter.py
    ├── test_commands.py
    └── test_adapters.py
```

### Data Flow

```
User types in Discord/Telegram
        │
        ▼
Platform Adapter
  - Receives platform event
  - Translates to BotRequest
  - Filters: DM → always process; channel → only @mention or /command
  - Ignores messages from bots (including self)
        │
        ▼
BotCore.handle(request)
  1. Auth check: resolve platform user → PAM user (or prompt to /link)
  2. Route: slash command → specific handler, plain text → chat handler
  3. Handler calls PAM REST API via api_client
  4. Pass API response to formatter
        │
        ▼
ResponseFormatter
  - Applies response_mode (split vs truncate-with-link)
  - Returns list[BotResponse]
        │
        ▼
Platform Adapter
  - Translates BotResponse → platform-specific message (embeds, markdown, buttons)
  - Sends to user/channel
```

## Platform Adapter Interface

```python
class PlatformAdapter(ABC):
    name: str                           # "discord" | "telegram"
    core: BotCore

    @abstractmethod
    async def start(self) -> None:
        """Connect to platform (WebSocket gateway, long-polling, etc.)"""

    @abstractmethod
    async def stop(self) -> None:
        """Graceful shutdown"""

    @abstractmethod
    async def send(self, channel_id: str, response: BotResponse) -> None:
        """Send a response back to the platform"""

    async def _on_message(self, raw_event: Any) -> None:
        """
        1. Translate platform event → BotRequest
        2. Filter: ignore if channel and not @mentioned/slash
        3. Call self.core.handle(request) → list[BotResponse]
        4. Call self.send() for each response
        """
```

**Platform libraries:**
- Discord: `discord.py` (2.x) — async-native, slash command support
- Telegram: `python-telegram-bot` (21.x) — async-native, inline keyboards

Both run in the same asyncio event loop, started as background tasks from `__main__.py`.

## Common Data Models

```python
class BotRequest(BaseModel):
    platform: str                       # "discord" | "telegram"
    platform_user_id: str               # Raw platform user ID
    platform_username: str              # Display name for logging
    channel_id: str                     # DM or channel/group ID
    is_dm: bool
    message_id: str                     # For reply threading
    text: str                           # Full message text (minus @mention)
    command: str | None                 # Slash command name if applicable
    command_args: str                   # Remainder after command name
    attachments: list[Attachment]       # File uploads (for ingest)

class BotResponse(BaseModel):
    text: str                           # Markdown text
    citations: list[Citation]           # From PAM ChatResponse
    embed_type: str | None              # "answer" | "error" | "link" | "list"
    buttons: list[Button]               # Platform-agnostic action buttons
    reply_to_message_id: str | None     # For thread/reply context

class Attachment(BaseModel):
    filename: str
    content_type: str                   # MIME type
    url: str                            # Platform CDN URL for the file
    size_bytes: int

class Button(BaseModel):
    label: str
    action: str                         # "next_page" | "prev_page" | "view_full" | "delete_memory"
    payload: dict                       # Handler-specific data
```

Button clicks route back through `_on_message` as a `BotRequest` with `command = "_button_click"` and the action + payload in `command_args`. `BotCore` dispatches to the original handler for pagination or follow-up.

## Command System

Commands are registered via a decorator pattern and dispatched by `BotCore`. Plain text without `/` routes to the chat handler.

### Command Registry

```python
command_registry: dict[str, CommandHandler] = {}

def command(name: str, description: str, args_hint: str = ""):
    def decorator(func):
        command_registry[name] = CommandHandler(
            name=name,
            description=description,
            args_hint=args_hint,
            handler=func,
        )
        return func
    return decorator
```

### Dispatch Logic

```python
async def handle(self, req: BotRequest) -> list[BotResponse]:
    # 1. Resolve PAM user
    pam_user = await self.auth.resolve(req.platform, req.platform_user_id)
    if not pam_user and req.command != "link":
        return [unauth_response()]

    ctx = BotContext(request=req, pam_user_id=pam_user.id, api=self.api_client)

    # 2. Route
    if req.command:
        handler = command_registry.get(req.command)
        if not handler:
            return [BotResponse(text=f"Unknown command: /{req.command}")]
        raw = await handler.handler(ctx, req.command_args)
    else:
        raw = await chat_cmd(ctx, req.text)

    # 3. Format
    return self.formatter.format(raw, ctx)
```

### Command List

| Command | Description | Maps To |
|---------|-------------|---------|
| `/link <code>` | Link platform account to PAM user | Account linking flow |
| `/unlink` | Remove account link | Account linking flow |
| `/whoami` | Show linked PAM user info | Local |
| `/help` | Show available commands | Local |
| *(plain text)* | Ask a question | `POST /api/chat` |
| `/ask <text>` | Explicit chat (same as plain text) | `POST /api/chat` |
| `/search <query>` | Hybrid search without agent | `POST /api/search` |
| `/documents` | List documents (paginated) | `GET /api/documents` |
| `/document <id>` | Get document details | `GET /api/documents/{id}` |
| `/ingest <url\|folder>` | Trigger ingestion | `POST /api/ingest/*` |
| `/tasks` | List ingestion tasks | `GET /api/ingest/tasks` |
| `/remember <text>` | Store a memory | `POST /api/memory` |
| `/recall <query>` | Search memories | `GET /api/memory/search` |
| `/memories` | List my memories | `GET /api/memory/user/{id}` |
| `/forget <id>` | Delete a memory | `DELETE /api/memory/{id}` |
| `/graph <query>` | Graph relationship search | `POST /api/graph/search` |
| `/entities <type>` | List entities by type | `GET /api/graph/entities` |
| `/history <entity>` | Entity change history | `GET /api/graph/entities/{id}/history` |
| `/conversations` | List my conversations | `GET /api/conversations/user/{id}` |
| `/new` | Start new conversation | Local (reset conversation_id) |

### Conversation Continuity

- `BotCore` maintains `{(platform, channel_id, pam_user_id): conversation_id}` in Redis
- Plain text messages continue the same conversation
- `/new` clears the mapping and starts fresh
- DMs: one conversation per user until `/new`
- Channels: one conversation per `(channel, user)` pair
- Conversations auto-reset after `conversation_idle_ttl_seconds` (default: 1 hour)

## Authentication & Account Linking

### PlatformIdentity Data Model

New table in PAM core:

```python
class PlatformIdentity(Base):
    __tablename__ = "platform_identities"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str]                     # "discord" | "telegram"
    platform_user_id: Mapped[str]             # Raw ID from platform
    platform_username: Mapped[str | None]     # Display name for audit
    linked_at: Mapped[datetime]
    last_seen_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id"),
    )
```

### New REST Endpoints (PAM Core)

```
POST   /api/auth/link/code       — Authenticated user generates a one-time link code
POST   /api/auth/link/exchange   — Bot exchanges code → creates PlatformIdentity
GET    /api/auth/link/resolve    — Bot resolves (platform, platform_user_id) → user
DELETE /api/auth/link/{id}       — Unlink identity
```

### Linking Flow

```
1. User (logged into PAM web UI) generates a link code
   → POST /api/auth/link/code
   → Returns: { code: "ABCD-1234", expires_at, ttl_seconds: 600 }

2. User DMs the bot: /link ABCD-1234
   → Bot calls POST /api/auth/link/exchange with:
     { code, platform, platform_user_id, platform_username }
   → PAM validates code (unused, not expired)
   → Creates PlatformIdentity row
   → Bot replies: "Linked to alice@company.com"

3. Subsequent messages:
   → Bot calls GET /api/auth/link/resolve?platform=discord&platform_user_id=123
   → PAM returns user (or 404 if not linked)
   → Response cached in Redis for 5 minutes
```

### Bot-to-PAM Authentication

The `pam-bots` service uses a **service account JWT** with `bot_service` role. Each request includes:
- `Authorization: Bearer <service_token>` — authenticates the bot service
- `X-On-Behalf-Of: <pam_user_id>` — attributes the action to the linked user

PAM validates that the caller has `bot_service` role before honoring `X-On-Behalf-Of`. The on-behalf-of user's RBAC still applies to all data access.

### X-On-Behalf-Of Middleware

```python
async def on_behalf_of_middleware(request: Request, call_next):
    on_behalf_of = request.headers.get("X-On-Behalf-Of")
    if on_behalf_of:
        caller = request.state.user
        if not caller or "bot_service" not in caller.roles:
            raise HTTPException(403, "X-On-Behalf-Of requires bot_service role")
        request.state.user = await get_user_by_id(on_behalf_of)
    return await call_next(request)
```

### One-Time Link Codes

Stored in Redis (no new DB table):
- Key: `link_code:{code}` → `{ user_id, created_at }`
- TTL: 600 seconds (10 minutes)
- Deleted after successful exchange (single-use)

### Service Account Provisioning

- New `bot_service` role added to PAM's RBAC enum
- Token generated via CLI: `python -m pam.cli auth.create_bot_token`
- Stored in bot's `.env` as `PAM_BOT_SERVICE_TOKEN`
- Permissions: call `/api/auth/link/*` and use `X-On-Behalf-Of` on any endpoint
- Does NOT bypass user-level RBAC

### Security Properties

- Users must authenticate to PAM web UI first → no unauthorized account creation
- One-time codes expire in 10 minutes, single-use
- `X-On-Behalf-Of` only honored from `bot_service` tokens
- Platform user IDs globally unique per platform (enforced by UniqueConstraint)
- Unlinking revokes access immediately
- All bot actions logged with both service token ID and on-behalf-of user ID

## Response Formatting

### Response Modes

```python
class ResponseMode(StrEnum):
    SPLIT = "split"                      # Split into multiple messages
    TRUNCATE_WITH_LINK = "truncate_link" # Truncate + link to web UI (default)
```

### Platform Limits

```python
PLATFORM_LIMITS = {
    "discord": 2000,    # chars per message
    "telegram": 4096,   # chars per message
}
```

### Formatter Logic

```python
class ResponseFormatter:
    def format(self, raw: list[BotResponse], ctx: BotContext) -> list[BotResponse]:
        limit = PLATFORM_LIMITS[ctx.request.platform]
        formatted = []

        for response in raw:
            rendered = self._render_with_citations(response)

            if len(rendered) <= limit:
                formatted.append(response.model_copy(update={"text": rendered}))
                continue

            if self.mode == ResponseMode.SPLIT:
                formatted.extend(self._split(response, rendered, limit))
            else:
                formatted.append(self._truncate_with_link(response, rendered, limit, ctx))

        return formatted
```

### Split Strategy (Mode B)

1. Split on paragraph boundaries (`\n\n`)
2. If a paragraph exceeds limit, split on sentence boundaries
3. If a sentence exceeds limit, hard-wrap on word boundaries
4. Never split mid-code-block — keep fenced blocks intact or split on line boundaries with continuation markers
5. Prefix continuation chunks: `(cont. 2/4)`, `(cont. 3/4)`, etc.
6. Citations appended as a final message

### Truncate-With-Link Strategy (Mode D)

1. Keep first ~70% of limit for content
2. Append `... [View full answer]({web_ui_url}/conversations/{id}#message-{msg_id})`
3. Citations inline (compact)

### Rich Output Handling

- **Tables**: compact Markdown tables if ≤5 columns, else bulleted list
- **Graph results**: indented list (`entity → relation → entity`)
- **Code blocks**: preserved with language hint
- **Errors**: prefixed with warning symbol and red embed (Discord) or bold (Telegram)
- **Long lists**: paginated with buttons (`page 1/5`)

### Typing Indicators

- Discord: `async with channel.typing()` while waiting for PAM response
- Telegram: `send_chat_action("typing")` every 4 seconds until response

### Streaming

Initial release uses non-streaming `POST /api/chat`. Messaging platforms don't support progressive token streaming well (Discord/Telegram message-edit rate limits would throttle). Streaming via message editing is a future enhancement.

## Configuration

```python
class BotSettings(BaseSettings):
    # PAM API connection
    pam_api_url: str                          # "http://api:8000"
    pam_bot_service_token: SecretStr          # Service account JWT
    pam_web_ui_url: str                       # "https://pam.example.com"

    # Enabled platforms
    enabled_platforms: list[str] = ["discord", "telegram"]

    # Discord config
    discord_bot_token: SecretStr | None = None
    discord_application_id: str | None = None
    discord_guild_ids: list[str] = []         # Restrict to specific guilds

    # Telegram config
    telegram_bot_token: SecretStr | None = None
    telegram_allowed_chat_ids: list[str] = [] # Whitelist chats

    # Response behavior
    response_mode: ResponseMode = ResponseMode.TRUNCATE_WITH_LINK
    auto_export_threshold: int = 20

    # Conversation behavior
    conversation_idle_ttl_seconds: int = 3600

    # Redis
    redis_url: str = "redis://redis:6379/1"

    # Rate limiting
    rate_limit_per_minute: int = 30

    # Logging
    log_level: str = "INFO"
    correlation_id_header: str = "X-Correlation-ID"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="PAM_BOT_")
```

## Deployment

### Docker Compose Addition

```yaml
services:
  bots:
    build:
      context: .
      dockerfile: Dockerfile
    command: python -m pam.bots
    environment:
      PAM_BOT_PAM_API_URL: http://api:8000
      PAM_BOT_PAM_BOT_SERVICE_TOKEN: ${PAM_BOT_SERVICE_TOKEN}
      PAM_BOT_PAM_WEB_UI_URL: ${PAM_WEB_UI_URL:-http://localhost:5173}
      PAM_BOT_ENABLED_PLATFORMS: discord,telegram
      PAM_BOT_DISCORD_BOT_TOKEN: ${DISCORD_BOT_TOKEN}
      PAM_BOT_TELEGRAM_BOT_TOKEN: ${TELEGRAM_BOT_TOKEN}
      PAM_BOT_RESPONSE_MODE: truncate_link
      PAM_BOT_REDIS_URL: redis://redis:6379/1
      PAM_BOT_LOG_LEVEL: INFO
    depends_on:
      api:
        condition: service_healthy
      redis:
        condition: service_healthy
    restart: unless-stopped
```

Same Docker image as the API (shared `src/pam/` package), different entrypoint. No extra build step.

### Lifecycle

```python
async def main():
    settings = BotSettings()
    configure_logging(settings.log_level)

    api_client = PamApiClient(settings.pam_api_url, settings.pam_bot_service_token)
    redis = await aioredis.from_url(settings.redis_url)
    core = BotCore(api_client=api_client, redis=redis, formatter=ResponseFormatter(settings.response_mode), settings=settings)

    adapters: list[PlatformAdapter] = []
    if "discord" in settings.enabled_platforms:
        adapters.append(DiscordAdapter(core, settings))
    if "telegram" in settings.enabled_platforms:
        adapters.append(TelegramAdapter(core, settings))

    if not adapters:
        raise RuntimeError("No platforms enabled")

    stop_event = asyncio.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())

    await asyncio.gather(*(a.start() for a in adapters))
    await stop_event.wait()
    await asyncio.gather(*(a.stop() for a in adapters))
```

### Health Check

Minimal aiohttp server on `:8080/health` (separate from platform connections):
- Returns `{status: "ok", platforms: [...]}`
- Checks adapter connectivity and PAM API reachability

### New Dependencies

```toml
"discord.py>=2.4",
"python-telegram-bot>=21.0",
"aiohttp>=3.9",
```

## Error Handling & Observability

### Error Categories

| Error | Cause | User Sees |
|-------|-------|-----------|
| Not linked | Platform user not linked | "Link your account first. Run `/link` — see {web_ui_url}/settings/integrations" |
| Permission denied | RBAC forbids action | "You don't have permission. Contact your project admin." |
| PAM API unreachable | Network/service down | "PAM is temporarily unavailable. Try again in a moment." |
| PAM API 5xx | Internal error | "Something went wrong. Try again or check {web_ui_url}." |
| PAM API 4xx | Bad input | Forward sanitized API error message |
| Rate limited | Exceeds per-minute limit | "Slow down — limited to {n} requests per minute." |
| Command not found | Unknown `/command` | "Unknown command. Type /help for available commands." |
| Platform API error | Discord/Telegram rejects send | Log, retry once, drop silently |

### Error Handling in BotCore

```python
async def handle(self, req: BotRequest) -> list[BotResponse]:
    try:
        # routing logic
        return responses
    except PamApiError as e:
        log.error("pam_api_error", status=e.status, detail=e.detail, **req_context)
        return [error_response(e)]
    except RateLimitExceeded:
        return [rate_limit_response()]
    except Exception:
        log.exception("unhandled_error", **req_context)
        return [BotResponse(text="An unexpected error occurred.", embed_type="error")]
```

All exceptions caught — an unhandled error never crashes the adapter event loop.

### Rate Limiting

Per-user sliding window counter in Redis:
- Key: `ratelimit:{platform}:{platform_user_id}`
- TTL: 60 seconds
- Reject if count exceeds `rate_limit_per_minute`
- Separate from PAM's API-level rate limiting (slowapi). Both apply.

### Structured Logging

Follows PAM's existing structlog pattern. Every request logs:

```python
log.info("bot_request",
    platform=req.platform,
    platform_user_id=req.platform_user_id,
    channel_id=req.channel_id,
    is_dm=req.is_dm,
    command=req.command,
    pam_user_id=pam_user.id if pam_user else None,
    correlation_id=correlation_id,
)
```

Every response logs:

```python
log.info("bot_response",
    platform=req.platform,
    command=req.command,
    response_count=len(responses),
    latency_ms=elapsed_ms,
    pam_api_latency_ms=api_elapsed_ms,
    correlation_id=correlation_id,
)
```

### Correlation IDs

- `BotCore` generates a UUID per request
- Passed to PAM API via `X-Correlation-ID` header
- PAM's existing middleware propagates through structlog contextvars
- A single user message can be traced across bot logs and PAM API logs

### Health Monitoring

- Health endpoint at `:8080/health`
- Adapter heartbeat: log warning if no events from platform for 5 minutes
- Redis connectivity checked on health endpoint

## PAM Core Changes Summary

| Change | File |
|--------|------|
| `PlatformIdentity` ORM model | `src/pam/common/models.py` |
| Alembic migration | `alembic/versions/xxx_add_platform_identities.py` |
| Link code + exchange + resolve endpoints | `src/pam/api/routes/auth.py` |
| Pydantic schemas for link request/response | `src/pam/common/models.py` |
| `bot_service` role in RBAC enum | Existing role enum |
| `X-On-Behalf-Of` middleware | `src/pam/api/middleware/` |

## Testing Strategy

- **Unit tests**: BotCore routing, formatter (split/truncate), command handlers with mocked API client
- **Integration tests**: full request flow using `respx` to mock PAM API + fake adapter that emits BotRequest directly (no real platform connection)
- **Manual smoke test**: run against a test Discord server + Telegram test bot as part of release checklist

## Future Extensions

- **Slack adapter**: `slack-bolt` (async), same adapter pattern
- **WhatsApp adapter**: WhatsApp Business API via webhook, same pattern
- **Streaming via message editing**: edit-in-place for progressive responses (platform rate limits apply)
- **Rich platform features**: Discord thread support, Telegram inline mode, interactive forms
- **Bot management UI**: web UI page for managing linked accounts and bot settings

## Design Principles

- **Thin adapters**: platform-specific code stays in adapters, everything else in BotCore
- **Reuse PAM's REST API**: no logic duplication, bot is just another API client
- **Existing patterns**: Pydantic Settings, structlog, dependency injection, Redis
- **Security via delegation**: bot uses service token + X-On-Behalf-Of, user RBAC always applies
- **Configurable UX**: response mode and behavior tunable per deployment
