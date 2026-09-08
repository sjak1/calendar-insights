"""
Tunables for the agenda generator, and the one piece of arithmetic that reads
them.

These live apart from agenda_generator so that the prompt builder and the
document reader can reach them without importing the generator itself, which
imports both. Everything here is read once at import; load_dotenv runs first
because this module can be imported before agenda_generator is.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration (all overridable via env vars)
# ---------------------------------------------------------------------------
# Provider: "bedrock" (Sonnet 5, default) or "openai" (gpt-5-mini).
# Sonnet 5 replaced Sonnet 4.6 after an 8-model comparison on the same event
# (Bosch, 2026-09-03), one run each, isolating the agenda LLM call:
#
#   sonnet-5      30.4s  3083 out  101.5 tok/s  9 sessions
#   sonnet-4-6    48.2s  3077 out   63.8 tok/s  8 sessions
#   haiku-4-5     17.3s  1897 out  109.7 tok/s  7 sessions
#   gpt-5.6-sol   28.1s  2599 out   92.4 tok/s  8 sessions
#   gpt-5.6-terra 20.0s  1998 out  100.1 tok/s  8 sessions
#   gpt-5.6-luna  17.8s     — failed schema validation twice
#   kimi-k2.5     19.6s  1880 out   95.9 tok/s  8 sessions
#   glm-4.7       54.4s  1462 out   26.9 tok/s  7 sessions
#
# Sonnet 5 is 37% faster than 4.6 for the same output token count and $2/$10
# against $3/$15. Its newer tokenizer does cost ~30% more INPUT tokens (6147 vs
# 4747), but input is prefilled in parallel and priced lower, so it does not
# show up in latency. Haiku 4.5 and gpt-5.6-terra are faster still and remain
# worth revisiting, but both produced a shorter agenda, and the two non-Claude
# providers reject Anthropic's cachePoint block and report input tokens as 129
# regardless of prompt size — prompt caching and cost tracking would both need
# work before either could ship.
AGENDA_PROVIDER: str = os.getenv("AGENDA_PROVIDER", "bedrock").lower()
LLM_MODEL: str = os.getenv("AGENDA_LLM_MODEL", "gpt-5-mini")
AGENDA_BEDROCK_MODEL_ID: str = os.getenv(
    "AGENDA_BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-5"
)
MAX_DOCUMENT_CHARS: int = int(os.getenv("MAX_DOCUMENT_CHARS", "30000"))
AGENDA_SESSION_MIN: int = int(os.getenv("AGENDA_SESSION_MIN", "6"))
AGENDA_SESSION_MAX: int = int(os.getenv("AGENDA_SESSION_MAX", "10"))
AGENDA_DAY_START: str = os.getenv("AGENDA_DAY_START", "10:00 AM")
AGENDA_DAY_END: str = os.getenv("AGENDA_DAY_END", "5:00 PM")
AGENDA_MAX_ATTENDEES: int = int(os.getenv("AGENDA_MAX_ATTENDEES", "20"))
LLM_TIMEOUT_SECONDS: int = int(os.getenv("AGENDA_LLM_TIMEOUT", "120"))

# Ceiling on the agenda tool-use response. Converse defaults to 4096 when no
# inferenceConfig is sent, which is under what a multi-day briefing needs: a
# five-day Zurich agenda measured 7253 output tokens, and every event with
# duration > 1 failed in production because the JSON was cut off partway. This
# is a cap and not a target — billing is on tokens actually generated, so the
# headroom is free. _MAX_SESSIONS_TOTAL is what keeps the length sane.
AGENDA_MAX_OUTPUT_TOKENS: int = int(os.getenv("AGENDA_MAX_OUTPUT_TOKENS", "16000"))

# EBD quality gate: skip extracted text that is too short or mostly non-alpha
EBD_MIN_WORDS: int = 100
EBD_MAX_NOISE_RATIO: float = 0.5  # if >50% of chars are non-alphanumeric, skip
# Default EBD path for testing only — set DEFAULT_EBD_PATH env var to override
DEFAULT_EBD_PATH: Optional[str] = os.getenv(
    "DEFAULT_EBD_PATH",
    str(Path(__file__).parent.parent / "documents" / "ebd" / "EBD_Apple_FILLED.pptx"),
)
# A briefing day has a practical ceiling on distinct sessions regardless of how
# many hours are booked — past this you are describing a conference timetable,
# not a briefing, and the structured-output call grows accordingly.
_MAX_SESSIONS_PER_DAY = 10
# And a ceiling across the whole briefing: a 12-hour window over three days
# asked for up to 36 sessions, which stalled generation outright.
_MAX_SESSIONS_TOTAL = 24


def _session_count_range(window_minutes: int, num_days: int = 1) -> tuple:
    """How many sessions this briefing can carry per day, as (min, max).

    AGENDA_SESSION_MIN/MAX are one fixed range for every briefing, so a
    four-hour visit was asked for the same 6-10 sessions as a full day and the
    model met the count by shrinking everything to fit. Deriving the range from
    the booked window instead means one session per ~75 min at the loose end
    and per ~45 min at the tight end — which reproduces the old 6-10 for a
    standard seven-hour day, and scales honestly either side of it.

    Both ends are then capped. Sizing purely off the window is what a long
    booking exposes: a 12-hour window over three days worked out to 9-12
    sessions a day, 36 in total, and the generation call simply stalled. Hours
    booked is evidence of how long the room is held, not of how many distinct
    sessions anyone wants to sit through.

    Falls back to the configured range when there is no window to measure.
    """
    if not window_minutes or window_minutes <= 0:
        return AGENDA_SESSION_MIN, AGENDA_SESSION_MAX

    low = max(3, window_minutes // 75)
    high = max(low + 1, window_minutes // 45)

    high = min(high, _MAX_SESSIONS_PER_DAY)
    if num_days > 1:
        # Spread the total budget across the days rather than per-day sizing
        # each one as though it were the only day.
        high = min(high, max(4, _MAX_SESSIONS_TOTAL // num_days))
    low = min(low, max(3, high - 1))
    return low, high
