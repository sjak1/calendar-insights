"""
Assembling the prompt the agenda model is given.

Everything here is string construction over data the generator has already
gathered — no network, no model call — which is what makes the prompt cheap to
read and to test.
"""

import json
import re
from typing import Any, Dict, List

from tools.agenda_config import (
    AGENDA_DAY_END,
    AGENDA_DAY_START,
    _session_count_range,
)

def _format_correction_note(issues: List[str]) -> str:
    """Build a correction section instructing the LLM to fix specific time issues."""
    bullets = "\n".join(f"- {issue}" for issue in issues)
    return (
        "The previous draft of this agenda had scheduling problems. "
        "Regenerate the full agenda fixing ALL of the following, while keeping the "
        "same topics and presenters where possible. Sessions must be in chronological "
        "order, non-overlapping, contiguous within the day window, and include a lunch break:\n"
        f"{bullets}"
    )
def _rank_previous_meetings(
    meetings: List[Dict[str, Any]], current_meeting: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Rank and annotate previous meetings by relevance to the current one.

    Scoring: recency + visit-focus overlap + same pillars.
    Only the top 3 most relevant are kept to save prompt space.
    """
    if not meetings:
        return []

    current_focus = (current_meeting.get("visit_focus") or "").lower()
    current_pillars = set()
    cp = current_meeting.get("pillars")
    if isinstance(cp, list):
        current_pillars = {str(p).lower() for p in cp}
    elif isinstance(cp, str):
        current_pillars = {cp.lower()}

    scored = []
    for i, m in enumerate(meetings):
        score = 0.0
        # Recency: first items are most recent (already sorted desc)
        score += max(0, 5 - i)  # 5, 4, 3, 2, 1

        # Visit focus overlap
        m_focus = (m.get("visit_focus") or "").lower()
        if m_focus and current_focus:
            # Simple word overlap ratio
            cur_words = set(current_focus.split())
            m_words = set(m_focus.split())
            if cur_words & m_words:
                overlap = len(cur_words & m_words) / max(len(cur_words | m_words), 1)
                score += overlap * 5

        # Pillar overlap
        m_pillars = set()
        mp = m.get("pillars")
        if isinstance(mp, list):
            m_pillars = {str(p).lower() for p in mp}
        elif isinstance(mp, str):
            m_pillars = {mp.lower()}
        if m_pillars & current_pillars:
            score += 2

        m_copy = dict(m)
        m_copy["_relevance_score"] = round(score, 1)
        scored.append(m_copy)

    scored.sort(key=lambda x: -x["_relevance_score"])
    # Keep top 3; annotate relevance label for the LLM
    top = scored[:3]
    for m in top:
        s = m.pop("_relevance_score")
        m["relevance"] = "high" if s >= 7 else ("medium" if s >= 4 else "low")
    return top
def _build_agenda_prompt(
    *, meeting, total_attendee_count, attendees, c_level_attendees,
    decision_makers, technical_attendees, remote_attendees, external_attendees,
    previous, similar, presenter_section, ebd_section, has_ebd,
    presenter_recommendations, correction_note=None, num_days=1, missing_fields=None,
    schedule=None,
) -> str:
    """Build the user prompt for the LLM."""
    correction_section = f"\n\n## CORRECTIONS REQUIRED\n\n{correction_note}\n" if correction_note else ""
    gaps_section = ""
    if missing_fields:
        gaps_section = (
            "\n\n## DATA GAPS\n\n"
            f"The following fields are missing from the meeting record: {', '.join(missing_fields)}. "
            "Do NOT invent values for them. Where you have to assume something to build the agenda, "
            "record each assumption as a short bullet in strategic_notes.assumptions so the requester "
            "can confirm or correct it.\n"
        )
    # The booked hours, when the event has real ones. Sessions are sized to fill
    # them; the scheduler then turns durations into clock times.
    window_label = schedule.get("label") if schedule else None
    window_minutes = (schedule or {}).get("minutes") or 0
    if window_label:
        day_span = f"{window_label} ({window_minutes // 60}h{window_minutes % 60 or ''} of booked time)"
    else:
        day_span = f"{AGENDA_DAY_START} - {AGENDA_DAY_END}"

    budget = (
        f" Session durations should add up to roughly {int(window_minutes * 0.85)} minutes "
        f"so the day is well used without being programmed wall-to-wall."
        if window_minutes
        else ""
    )
    # Session count scales with the booked day rather than being one fixed
    # range for a four-hour visit and a full day alike.
    sess_min, sess_max = _session_count_range(window_minutes, num_days)

    if num_days > 1:
        day_requirement = (
            f"1. This is a {num_days}-DAY briefing. Create sessions for EVERY day: set the day field "
            f"(1..{num_days}) on each session. Each day runs {day_span} with "
            f"{sess_min}-{sess_max} sessions AND its own lunch break.{budget} Give each day a "
            "coherent theme (e.g. day 1 = vision/strategy, day 2 = deep-dives/planning) and avoid repeating sessions across days."
        )
    else:
        day_requirement = (
            f"1. Create {sess_min}-{sess_max} sessions filling "
            f"{day_span} (single day; day field = 1).{budget}"
        )
    return f"""Generate a professional executive briefing agenda based on the data below.{correction_section}{gaps_section}

## MEETING CONTEXT

Company: {meeting.get('company_name')}
Industry: {meeting.get('industry')}
Account Type: {meeting.get('account_type')}
Line of Business: {meeting.get('line_of_business')}
Visit Focus: {meeting.get('visit_focus')}
Meeting Objective: {meeting.get('meeting_objective')}
Sales Plays: {meeting.get('sales_plays')}
Strategic Pillars: {meeting.get('pillars')}
Region: {meeting.get('region')}
Tier: {meeting.get('tier')}
Date: {(schedule or {}).get('date') or 'not on file'}
Booked hours: {(schedule or {}).get('label') or 'not on file'}
Location: {meeting.get('location') or 'not on file'}

## ATTENDEE MIX

Total attendees: {total_attendee_count}{f' (showing top {len(attendees)})' if total_attendee_count > len(attendees) else ''}
C-Level: {len(c_level_attendees)} | Decision Makers: {len(decision_makers)} | Technical: {len(technical_attendees)} | Remote: {len(remote_attendees)} | External: {len(external_attendees)}

Who is actually in the room — design the day for THESE people. Their real job
titles are what matter; the C-level flag is a data field and often disagrees
with the title, in which case believe the title:

{chr(10).join(
    f"- {a.get('name') or 'Unnamed'} — {a.get('title') or 'title unknown'}"
    f" [{a.get('type', 'Unknown')}"
    + (", decision maker" if a.get("decision_maker") else "")
    + (", technical" if a.get("technical") else "")
    + (", remote" if a.get("remote") else "")
    + "]"
    for a in attendees[:15]
) or '- No attendee records on file'}

## PREVIOUS MEETINGS (ranked by relevance)

{json.dumps(previous, indent=2) if previous else 'None'}

## SIMILAR BRIEFINGS

{json.dumps(similar, indent=2) if similar else 'None'}
{presenter_section}
{ebd_section}

## REQUIREMENTS

{day_requirement}
1b. Do NOT write time_slot — leave it empty. Set duration_minutes on every session,
    plus anchor ('open' for the welcome, 'lunch', 'close' for the wrap-up, 'morning'/
    'afternoon' where the content needs that half of the day, else 'any') and movable
    (False for welcome/lunch/close). Clock times are assigned afterwards by a scheduler
    that knows the booked hours and each presenter's real calendar — which is why it,
    and not you, decides when things run. Where a session could reasonably be shorter
    or longer, set duration_min_minutes / duration_max_minutes: that slack is what lets
    the scheduler keep the best-matched expert instead of downgrading to someone free.
2. Include a lunch break{' each day' if num_days > 1 else ''}.
3. Tailor to {meeting.get('industry')} industry.
4. Address visit focus: {meeting.get('visit_focus')}.
5. Incorporate sales plays: {meeting.get('sales_plays')}.
6. Use hybrid format if remote attendees ({len(remote_attendees)} remote).
7. Vary session formats (Presentation, Demo, Roundtable, Working Session).
8. {'ATTENDEES ARE NOT PRESENTERS. The document lists who will be in the room — account team, points of contact, executives attending. Never put those names in a presenter field. Only use a name from the document if it explicitly says that person is presenting or speaking on a topic.' if has_ebd else 'Use presenter recommendations below when relevant.'}
9. {'Presenters come from the PRESENTER RECOMMENDATIONS below, chosen per session by topic fit. Use TBD when none fits — TBD is correct and expected; inventing a presenter, or promoting an attendee into the role, is not.' if presenter_recommendations else 'If no strong presenter match is available, use TBD.'}
9b. Put the presenter's name ONLY in the `presenter` field. Never name them in `description` — write "this session covers X", not "Deepa will cover X". Assignments are re-checked against topic expertise and availability after you generate, so a name written into prose can end up contradicting the presenter actually assigned.
10. {'Extract any dollar figures / KPIs from the document into key_metrics fields.' if has_ebd else ''}
11. {'Use any customer references found in the document.' if has_ebd else ''}
12. Prioritise high-relevance previous meetings when designing the flow; avoid repeating topics from recent meetings.

Hard-code the following attendee counts (do NOT make them up):
- total_attendees: {total_attendee_count}
- c_level_count: {len(c_level_attendees)}
- decision_maker_count: {len(decision_makers)}
- technical_count: {len(technical_attendees)}
- remote_count: {len(remote_attendees)}"""
def _strip_prompt_sections(messages: list) -> list:
    """Remove PREVIOUS MEETINGS and SIMILAR BRIEFINGS sections from the prompt for retry."""
    new_messages = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            # Remove sections between headers
            content = re.sub(
                r"## PREVIOUS MEETINGS.*?(?=## )", "## PREVIOUS MEETINGS (ranked by relevance)\n\nOmitted for brevity.\n\n",
                content, flags=re.DOTALL,
            )
            content = re.sub(
                r"## SIMILAR BRIEFINGS.*?(?=## )", "## SIMILAR BRIEFINGS\n\nOmitted for brevity.\n\n",
                content, flags=re.DOTALL,
            )
            new_messages.append({**msg, "content": content})
        else:
            # multipart content (file + text) — strip from the text part
            new_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    t = part["text"]
                    t = re.sub(
                        r"## PREVIOUS MEETINGS.*?(?=## )", "## PREVIOUS MEETINGS\n\nOmitted.\n\n",
                        t, flags=re.DOTALL,
                    )
                    t = re.sub(
                        r"## SIMILAR BRIEFINGS.*?(?=## )", "## SIMILAR BRIEFINGS\n\nOmitted.\n\n",
                        t, flags=re.DOTALL,
                    )
                    new_parts.append({**part, "text": t})
                else:
                    new_parts.append(part)
            new_messages.append({**msg, "content": new_parts})
    return new_messages
