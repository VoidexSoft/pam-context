"""Structured logging with structlog, correlation IDs, and cost tracking."""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field

import structlog

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")


def get_correlation_id() -> str:
    return correlation_id_var.get()


def set_correlation_id(cid: str | None = None) -> str:
    cid = cid or uuid.uuid4().hex[:16]
    correlation_id_var.set(cid)
    return cid


def add_correlation_id(logger: structlog.types.WrappedLogger, method_name: str, event_dict: dict) -> dict:
    cid = correlation_id_var.get()
    if cid:
        event_dict["correlation_id"] = cid
    return event_dict


def configure_logging(log_level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            add_correlation_id,  # type: ignore[list-item]
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@dataclass
class CostTracker:
    """Tracks LLM token usage and estimated cost per request."""

    calls: list[dict] = field(default_factory=list)

    def log_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: float,
    ) -> None:
        cost = self._estimate_cost(model, input_tokens, output_tokens)
        call_info = {
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": round(latency_ms, 1),
            "estimated_cost_usd": round(cost, 6),
        }
        self.calls.append(call_info)
        log = structlog.get_logger()
        log.info("llm_call", **call_info)

    def log_embedding_call(
        self,
        model: str,
        input_tokens: int,
        latency_ms: float,
    ) -> None:
        cost = self._estimate_embedding_cost(model, input_tokens)
        call_info = {
            "model": model,
            "input_tokens": input_tokens,
            "latency_ms": round(latency_ms, 1),
            "estimated_cost_usd": round(cost, 6),
        }
        self.calls.append(call_info)
        log = structlog.get_logger()
        log.info("embedding_call", **call_info)

    @property
    def total_cost(self) -> float:
        return float(sum(c.get("estimated_cost_usd", 0) for c in self.calls))

    @property
    def total_tokens(self) -> int:
        return sum(c.get("input_tokens", 0) + c.get("output_tokens", 0) for c in self.calls)

    @staticmethod
    def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
        # Approximate pricing per 1M tokens (as of 2025)
        pricing = {
            "claude-sonnet-4-5-20250514": {"input": 3.0, "output": 15.0},
            "claude-opus-4-6": {"input": 15.0, "output": 75.0},
        }
        # Default to sonnet pricing
        rates = pricing.get(model, pricing["claude-sonnet-4-5-20250514"])
        return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000

    @staticmethod
    def _estimate_embedding_cost(model: str, input_tokens: int) -> float:
        pricing = {
            "text-embedding-3-large": 0.13,  # per 1M tokens
            "text-embedding-3-small": 0.02,
        }
        rate = pricing.get(model, 0.13)
        return input_tokens * rate / 1_000_000
