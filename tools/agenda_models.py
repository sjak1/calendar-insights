"""
The typed shape of a generated agenda.

GeneratedAgenda is the structured-output schema handed to the model, so the
Field descriptions here are not documentation for us — they are the
instructions the model reads. Editing one changes what comes back.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

class AgendaTruncated(RuntimeError):
    """The model ran out of output budget partway through the agenda object.

    Distinct from a schema error: the agenda we got back is not wrong, it is
    unfinished, and the retry has to ask for less rather than send less.
    """
# ============================================================================
# STRUCTURED OUTPUT MODELS
# ============================================================================

class OraclePresenter(BaseModel):
    """Presenter information."""
    name: str = Field(description="Full name of the presenter")
    title: str = Field(description="Job title of the presenter")


class TopicPresenterSuggestion(BaseModel):
    """Best-ranked presenter for a session's topic, attached after generation.

    A typed model rather than a free dict on purpose: AgendaSession is the
    OpenAI structured-output schema, and strict mode rejects free-form objects
    — to_strict_json_schema() raises on Dict[str, Any], which would fail every
    agenda request on the default provider path before the model was called.
    """
    presenter_name: Optional[str] = None
    title: Optional[str] = None
    match_tier: Optional[str] = None
    matched_topic: Optional[str] = None
    available: Optional[bool] = None
    reason: Optional[str] = None
    # Deal movement at the briefings this person presented at. Context only —
    # never a ranking input, and always carried WITH its caveat, because a
    # briefing has several presenters and one revenue figure.
    revenue_delta: Optional[float] = None
    revenue_events: Optional[int] = None
    revenue_note: Optional[str] = None


class BackupPresenter(BaseModel):
    """A ranked alternate for a session, verified free at its final time.

    Typed rather than a free dict for the same reason as
    TopicPresenterSuggestion: AgendaSession is the structured-output schema and
    strict mode rejects Dict[str, Any].
    """
    presenter_name: str
    title: Optional[str] = None
    match_tier: Optional[str] = None
    reason: Optional[str] = None


class AgendaSession(BaseModel):
    """A single session in the agenda."""
    day: int = Field(
        default=1,
        description="Day of the briefing this session belongs to (1-based). Always 1 for single-day events.",
    )
    time_slot: str = Field(
        default="",
        description=(
            "Leave empty. Clock times are assigned after generation by the "
            "scheduler, which knows the event's booked hours and who is free "
            "when. Anything written here is discarded."
        ),
    )
    duration_minutes: int = Field(
        default=45,
        description=(
            "How long this session should run, in minutes. Use realistic "
            "lengths: 15 for a welcome or close, 30-60 for a content session, "
            "60 for lunch. The scheduler turns these into clock times."
        ),
    )
    duration_min_minutes: Optional[int] = Field(
        default=None,
        description=(
            "Shortest this session can usefully run. Set it below "
            "duration_minutes only where the session can genuinely be "
            "compressed — it is the slack the scheduler uses to fit a busy "
            "expert or a tight window. Leave null for fixed-length slots."
        ),
    )
    duration_max_minutes: Optional[int] = Field(
        default=None,
        description="Longest this session can usefully run. Leave null for fixed-length slots.",
    )
    anchor: Literal["open", "morning", "lunch", "afternoon", "close", "any"] = Field(
        default="any",
        description=(
            "Where in the day this belongs. 'open' for the welcome, 'close' for "
            "the wrap-up/next-steps, 'lunch' for the lunch break, 'morning'/"
            "'afternoon' when the content genuinely needs that half of the day "
            "(strategy while executives are fresh; hands-on work later), 'any' otherwise."
        ),
    )
    movable: bool = Field(
        default=True,
        description=(
            "May the scheduler move this session to a different point in the day "
            "to keep the best-matched presenter? False for the welcome, lunch and "
            "close, and for anything whose position carries the narrative."
        ),
    )
    title: str = Field(description="Action-oriented session title")
    format: Literal["Presentation", "Demo", "Roundtable", "Working Session"] = Field(
        description="Session format type"
    )
    presenter: str = Field(description="Presenter name and title")
    topic: Optional[str] = Field(
        default=None,
        description=(
            "The briefing topic this session covers, copied EXACTLY from the "
            "AVAILABLE TOPICS list. This is what the presenter must be an "
            "expert in — it drives per-session presenter matching. Leave null "
            "for non-content slots (welcome, breaks, close) and whenever no "
            "listed topic genuinely fits; never invent one."
        ),
    )
    description: str = Field(description="What will be covered in this session")
    topic_presenter_suggestion: Optional[TopicPresenterSuggestion] = Field(
        default=None,
        description="Leave null. Filled in after generation by ranked topic matching, never by you.",
    )
    presenter_before_topic_match: Optional[str] = Field(
        default=None,
        description="The originally generated presenter, kept when topic matching replaced it.",
    )
    scheduling_note: Optional[str] = Field(
        default=None,
        description=(
            "Leave null. Filled in by the scheduler when it had to reshape the day "
            "— e.g. moving a session to keep the best-matched presenter."
        ),
    )
    backup_presenters: List[BackupPresenter] = Field(
        default_factory=list,
        description=(
            "Leave empty. Filled in by the scheduler with the next-ranked people "
            "who are ALSO free at this session's final time — a briefing team's "
            "first question when a presenter drops out."
        ),
    )
    key_metrics: Optional[str] = Field(
        default=None, 
        description="Any $ figures or KPIs being addressed (e.g., '$50M inefficient spend')"
    )
    customer_reference: Optional[str] = Field(
        default=None,
        description="Customer success reference (e.g., 'Nike achieved 40% improvement')"
    )
    attendee_consideration: Optional[str] = Field(
        default=None,
        description="How this session addresses specific attendee concerns"
    )


class StrategicNotes(BaseModel):
    """Strategic notes and recommendations."""
    derailer_handling: Optional[str] = Field(
        default=None,
        description="How the agenda addresses account derailers"
    )
    attendee_considerations: List[str] = Field(
        default_factory=list,
        description="Attendee-specific considerations"
    )
    follow_up_actions: List[str] = Field(
        default_factory=list,
        description="Recommended follow-up actions"
    )
    assumptions: List[str] = Field(
        default_factory=list,
        description=(
            "Assumptions made because source data was missing (e.g. 'No meeting "
            "objective on file — assumed evaluation-stage briefing'). Empty when "
            "all key data was available."
        ),
    )


class GeneratedAgenda(BaseModel):
    """Complete structured agenda output."""
    # Header info
    company: str = Field(description="Company name")
    industry: str = Field(description="Company industry")
    date_time: str = Field(description="Proposed date and time range")
    location: str = Field(description="Location (physical and/or virtual)")
    
    # Presenters
    oracle_presenters: List[OraclePresenter] = Field(
        description="List of presenters for the briefing"
    )
    
    # Attendee summary
    total_attendees: int = Field(description="Total number of attendees")
    c_level_count: int = Field(description="Number of C-level executives")
    decision_maker_count: int = Field(description="Number of decision makers")
    technical_count: int = Field(description="Number of technical attendees")
    remote_count: int = Field(description="Number of remote participants")
    
    # Content
    executive_summary: str = Field(
        description="2-3 sentence strategic summary of the briefing goals"
    )
    sessions: List[AgendaSession] = Field(
        description="List of agenda sessions in chronological order"
    )
    strategic_notes: StrategicNotes = Field(
        description="Strategic notes and recommendations"
    )
