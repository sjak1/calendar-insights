"""Langfuse tracing for the BriefingIQ assistant.

Every helper here degrades to a no-op when LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
are missing, so the app runs unchanged without Langfuse configured.

``load_dotenv()`` runs at import time on purpose: the Langfuse client reads its
credentials from the environment when it is constructed, so this module must not
be imported before the .env file has been loaded.
"""

import os
import re
from contextlib import contextmanager
from typing import Any, Dict, Optional, Sequence

from dotenv import load_dotenv

load_dotenv()

from logging_config import get_logger

logger = get_logger(__name__)

# Trace names are treated like an API: evaluators, dashboards and saved filters
# target them by name, so keep them stable and free of dynamic values.
ROOT_OBSERVATION_NAME = "briefing-assistant"
GENERATION_NAME = "generate-response"
GUARDRAIL_NAME = "block-raw-dsl"

_client = None
_init_attempted = False


# --------------------------------------------------------------------------- #
# Masking
# --------------------------------------------------------------------------- #

# Credentials are always stripped. These patterns cover the secrets that can
# realistically reach a span: BriefingIQ bearer tokens, Bedrock/AWS API keys,
# OpenAI/Langfuse keys and inline passwords.
_SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"\bAB(?:SK|IA)[A-Za-z0-9+/=_\-]{16,}"), "[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED]"),
    (re.compile(r"\b(?:sk|pk)-(?:lf-)?[A-Za-z0-9_\-]{16,}"), "[REDACTED]"),
    (
        re.compile(r"(?i)(\"?(?:password|secret|api[_-]?key|token)\"?\s*[:=]\s*\"?)[^\"\s,}]{4,}"),
        r"\1[REDACTED]",
    ),
)

# Email addresses are the one piece of PII that flows through this app in bulk
# (attendee lists, presenter records, the caller's own identity). The local part
# is dropped and the domain kept, which is enough to debug a trace without
# storing who the individual is. Set LANGFUSE_MASK_PII=0 to trace them verbatim.
_EMAIL_PATTERN = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")

# Identity attributes must survive masking or the Users/Sessions views break.
_UNMASKED_ATTRIBUTES = frozenset(
    {
        "langfuse.user.id",
        "langfuse.session.id",
        "langfuse.trace.name",
        "langfuse.observation.type",
        "langfuse.environment",
        "langfuse.release",
        "langfuse.version",
    }
)


def _mask_pii_enabled() -> bool:
    return os.getenv("LANGFUSE_MASK_PII", "1").lower() in ("1", "true", "yes")


def capture_content() -> bool:
    """Whether observation payloads (input/output) are sent to Langfuse.

    Off by default. This app's payloads carry the internal OpenSearch schema
    reference and real customer briefing data, so shipping them to a hosted
    Langfuse project is a decision that has to be made deliberately rather than
    inherited from a default.

    With it off you still get the whole operational picture — models, tokens,
    cost, latency, which tools ran and in what order, errors and trace shape —
    just not the content. Turn it on for a self-hosted instance or local
    debugging, where seeing prompts and results is the point.
    """
    return os.getenv("LANGFUSE_CAPTURE_CONTENT", "0").lower() in ("1", "true", "yes")


def content(value: Any) -> Optional[Any]:
    """Pass a payload through only when content capture is enabled.

    Returning None means the SDK never creates the attribute at all, so the
    payload is not serialized rather than being redacted after the fact.
    """
    return value if capture_content() else None


def tool_result_metadata(result: Any) -> Dict[str, Any]:
    """Derive non-sensitive shape information from a tool result.

    Counts and status only, never values. This is what keeps a metadata-only
    trace useful: you can still see that a tool returned zero rows, or that it
    failed, without the rows themselves leaving the process.
    """
    meta: Dict[str, Any] = {"result_chars": len(str(result))}
    payload = result
    # Handlers wrap results as {tool_name: {...}} — unwrap one level.
    if isinstance(payload, dict) and len(payload) == 1:
        inner = next(iter(payload.values()))
        if isinstance(inner, dict):
            payload = inner
    if isinstance(payload, dict):
        for key in ("success", "count", "total_hits", "error"):
            if key in payload:
                meta[key] = payload[key] if key != "error" else True
        hits = payload.get("hits")
        if isinstance(hits, list):
            meta["hits_returned"] = len(hits)
    return meta


def _redact(value: str) -> str:
    """Strip credentials (always) and email local parts (unless opted out)."""
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    if _mask_pii_enabled():
        value = _EMAIL_PATTERN.sub(r"[EMAIL]@\1", value)
    return value


def _mask_otel_spans(*, params):
    """Export-stage masking hook.

    Runs on raw OpenTelemetry attributes after Langfuse has decided which spans
    to export, so it covers everything this client sends — including spans from
    third-party instrumentation we did not write.
    """
    from langfuse.types import MaskOtelSpansResult, OtelSpanPatch

    drop_content = not capture_content()
    patches = {}
    for identifier, span in params.spans.items():
        changed = {}
        dropped = []
        for key, value in span.attributes.items():
            # Hard guard: in metadata-only mode no payload attribute may leave,
            # including ones set by code paths that forgot to gate themselves or
            # by third-party instrumentation we do not control.
            if drop_content and key.endswith((".input", ".output")):
                dropped.append(key)
                continue
            if key in _UNMASKED_ATTRIBUTES or not isinstance(value, str):
                continue
            redacted = _redact(value)
            if redacted != value:
                changed[key] = redacted
        if changed or dropped:
            patches[identifier] = OtelSpanPatch(
                set_attributes=changed, delete_attributes=tuple(dropped)
            )

    return MaskOtelSpansResult(span_patches=patches) if patches else None


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #


def init_tracing():
    """Build the Langfuse client once. Returns None when Langfuse is not configured."""
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True

    if not (os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")):
        logger.info("Langfuse keys not set — tracing disabled")
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            mask_otel_spans=_mask_otel_spans,
            environment=os.getenv("LANGFUSE_TRACING_ENVIRONMENT")
            or os.getenv("APP_ENV")
            or "development",
            release=os.getenv("LANGFUSE_RELEASE"),
        )
        logger.info(
            f"Langfuse tracing enabled (host: {os.getenv('LANGFUSE_BASE_URL', 'default')})"
        )
    except Exception as e:  # never let observability break the app
        logger.warning(f"Langfuse init failed, continuing without tracing: {e}")
        _client = None

    return _client


def is_enabled() -> bool:
    return init_tracing() is not None


def flush() -> None:
    """Block until queued spans are sent. For short-lived processes (Lambda, scripts)."""
    if _client is not None:
        try:
            _client.flush()
        except Exception as e:
            logger.warning(f"Langfuse flush failed: {e}")


def shutdown() -> None:
    """Flush and stop background threads. Call on process shutdown."""
    if _client is not None:
        try:
            _client.shutdown()
        except Exception as e:
            logger.warning(f"Langfuse shutdown failed: {e}")


# --------------------------------------------------------------------------- #
# No-op fallbacks, so call sites stay free of `if tracing_enabled` branches
# --------------------------------------------------------------------------- #


class _NoopSpan:
    def update(self, **kwargs):
        return self

    def update_trace(self, **kwargs):
        return self

    def end(self, **kwargs):
        return self


_NOOP = _NoopSpan()


# --------------------------------------------------------------------------- #
# Observations
# --------------------------------------------------------------------------- #


@contextmanager
def query_trace(
    query: str,
    session_id: Optional[str],
    user_info: Optional[Dict[str, Any]],
    event_id: Optional[str],
    category_id: Optional[str],
    provider: str,
):
    """Root observation for one assistant turn.

    One trace per turn, grouped into a session by ``session_id`` — that is what
    makes the Sessions view show a whole conversation while keeping each trace
    small enough to read.

    Input is set to the user's question alone rather than the full argument
    list, so the trace input in the tracing table and in evaluators is the thing
    a reviewer actually wants to see (and so headers, which carry bearer tokens,
    never reach Langfuse).
    """
    client = init_tracing()
    if client is None:
        yield _NOOP
        return

    from langfuse import propagate_attributes

    user_info = user_info or {}
    # Page context is knowable up front, and tags are immutable once set, so
    # this is the right dimension to tag: it separates event-page traffic from
    # category-page and global traffic in dashboards.
    if event_id:
        page = "event"
    elif category_id:
        page = "category"
    else:
        page = "global"

    metadata = {
        "page_context": page,
        # Length is kept even when the question itself is not, so a trace still
        # shows roughly what came in.
        "query_chars": len(query or ""),
        "event_id": event_id,
        "category_id": category_id,
        "timezone": (
            user_info.get("requested_timezone")
            or user_info.get("context_timezone")
            or user_info.get("client_timezone")
        ),
        "customer_id": user_info.get("customer_id"),
    }

    # `agent` (not `span`) is the most specific type for a tool-calling loop
    # and is what drives the Agent Graph view.
    with client.start_as_current_observation(
        as_type="agent",
        name=ROOT_OBSERVATION_NAME,
        input=content(query),
        metadata={k: v for k, v in metadata.items() if v is not None},
    ) as root:
        with propagate_attributes(
            user_id=user_info.get("email") or None,
            session_id=session_id,
            trace_name=ROOT_OBSERVATION_NAME,
            tags=[f"page:{page}", f"provider:{provider}"],
        ):
            yield root


@contextmanager
def llm_generation(
    model: str,
    system: Any,
    messages: Sequence[Any],
    name: str = GENERATION_NAME,
    metadata: Optional[Dict[str, Any]] = None,
):
    """Generation observation for a single LLM call.

    Used for the main tool-calling loop and for the sub-LLM calls that some
    tools make on their own (agenda drafting, email composition) — every model
    call needs one of these or its tokens go unaccounted for.

    The system prompt is included in the input because it carries the schema
    reference and time context — without it a trace does not show what the model
    actually saw when it chose a tool.
    """
    client = init_tracing()
    if client is None:
        yield _NOOP
        return

    with client.start_as_current_observation(
        as_type="generation",
        name=name,
        model=model,
        input=content({"system": system, "messages": list(messages)}),
        metadata=metadata,
    ) as generation:
        yield generation


@contextmanager
def guardrail_span(name: str, input: Any):
    client = init_tracing()
    if client is None:
        yield _NOOP
        return

    with client.start_as_current_observation(
        as_type="guardrail", name=name, input=content(input)
    ) as span:
        yield span


@contextmanager
def tool_span(name: str, args: Any):
    """Tool observation, typed `tool` so it can be targeted by evaluators."""
    client = init_tracing()
    if client is None:
        yield _NOOP
        return

    with client.start_as_current_observation(
        as_type="tool", name=name, input=content(args)
    ) as span:
        yield span


# --------------------------------------------------------------------------- #
# Cross-thread context
# --------------------------------------------------------------------------- #


def current_context():
    """Snapshot the active OTel context.

    ThreadPoolExecutor does not carry contextvars into its workers, so tool
    spans started in a worker thread would otherwise be orphaned into their own
    traces instead of nesting under the current turn.
    """
    if not is_enabled():
        return None
    from opentelemetry import context as otel_context

    return otel_context.get_current()


@contextmanager
def use_context(ctx):
    """Re-attach a context snapshot inside a worker thread."""
    if ctx is None:
        yield
        return
    from opentelemetry import context as otel_context

    token = otel_context.attach(ctx)
    try:
        yield
    finally:
        otel_context.detach(token)


# --------------------------------------------------------------------------- #
# Usage mapping
# --------------------------------------------------------------------------- #


def bedrock_usage(usage: Dict[str, Any]) -> Dict[str, int]:
    """Map a Bedrock Converse usage block to Langfuse usage keys.

    Cache tokens are reported separately so prompt-cache savings show up in the
    cost breakdown instead of being folded into plain input tokens.
    """
    mapped = {
        "input": usage.get("inputTokens", 0),
        "output": usage.get("outputTokens", 0),
    }
    if usage.get("cacheReadInputTokens"):
        mapped["cache_read_input_tokens"] = usage["cacheReadInputTokens"]
    if usage.get("cacheWriteInputTokens"):
        mapped["cache_creation_input_tokens"] = usage["cacheWriteInputTokens"]
    return mapped
