"""
Render a GeneratedAgenda as markdown for the chat reply.

Presentation only: nothing here decides anything about the agenda, it just
lays out what the generator and scheduler already settled.
"""

from tools.agenda_models import GeneratedAgenda

def agenda_to_markdown(agenda: GeneratedAgenda) -> str:
    """
    Convert a structured GeneratedAgenda to formatted markdown.
    
    Args:
        agenda: The structured agenda object
        
    Returns:
        Formatted markdown string
    """
    lines = []
    
    # Header
    lines.append(f"# Executive Briefing Agenda for {agenda.company}")
    lines.append("")
    lines.append(f"**Company:** {agenda.company}  ")
    lines.append(f"**Industry:** {agenda.industry}  ")
    lines.append(f"**Date/Time:** {agenda.date_time}  ")
    lines.append(f"**Location:** {agenda.location}  ")
    lines.append("")
    
    # Presenters
    lines.append("## Presenters")
    for presenter in agenda.oracle_presenters:
        lines.append(f"- {presenter.name}, {presenter.title}")
    lines.append("")
    
    # Attendee Summary
    lines.append("## Attendee Summary")
    lines.append(f"- **Total Attendees:** {agenda.total_attendees}")
    lines.append(f"- **C-Level Executives:** {agenda.c_level_count}")
    lines.append(f"- **Decision Makers:** {agenda.decision_maker_count}")
    lines.append(f"- **Technical Attendees:** {agenda.technical_count}")
    lines.append(f"- **Remote Participants:** {agenda.remote_count}")
    lines.append("")
    
    # Executive Summary
    lines.append("## Executive Summary")
    lines.append(agenda.executive_summary)
    lines.append("")
    
    # Sessions (grouped by day when the briefing spans multiple days)
    lines.append("---")
    lines.append("")
    lines.append("## Agenda Sessions")
    lines.append("")

    multi_day = len({getattr(s, "day", 1) or 1 for s in agenda.sessions}) > 1
    current_day = None
    for session in agenda.sessions:
        if multi_day:
            day = getattr(session, "day", 1) or 1
            if day != current_day:
                current_day = day
                lines.append(f"## Day {day}")
                lines.append("")
        lines.append(f"### {session.time_slot}")
        lines.append(f"**Title:** {session.title}  ")
        lines.append(f"**Format:** {session.format}  ")
        lines.append(f"**Presenter:** {session.presenter}  ")
        lines.append(f"**Description:** {session.description}  ")
        if session.backup_presenters:
            names = ", ".join(
                f"{b.presenter_name}{f' ({b.title})' if b.title else ''}"
                for b in session.backup_presenters
            )
            lines.append(f"**Backup Presenters:** {names}  ")
        if session.scheduling_note:
            lines.append(f"**Scheduling Note:** {session.scheduling_note}  ")
        if session.key_metrics:
            lines.append(f"**Key Metrics:** {session.key_metrics}  ")
        if session.customer_reference:
            lines.append(f"**Customer Reference:** {session.customer_reference}  ")
        if session.attendee_consideration:
            lines.append(f"**Attendee Consideration:** {session.attendee_consideration}")
        lines.append("")
    
    # Strategic Notes
    lines.append("---")
    lines.append("")
    lines.append("## Strategic Notes")
    lines.append("")
    
    if agenda.strategic_notes.derailer_handling:
        lines.append(f"**Derailer Handling:** {agenda.strategic_notes.derailer_handling}")
        lines.append("")
    
    if agenda.strategic_notes.attendee_considerations:
        lines.append("**Attendee Considerations:**")
        for consideration in agenda.strategic_notes.attendee_considerations:
            lines.append(f"- {consideration}")
        lines.append("")
    
    if agenda.strategic_notes.follow_up_actions:
        lines.append("**Recommended Follow-up Actions:**")
        for action in agenda.strategic_notes.follow_up_actions:
            lines.append(f"- {action}")
        lines.append("")

    if agenda.strategic_notes.assumptions:
        lines.append("**Assumptions Made (missing data — please confirm):**")
        for assumption in agenda.strategic_notes.assumptions:
            lines.append(f"- {assumption}")
        lines.append("")

    return "\n".join(lines)
