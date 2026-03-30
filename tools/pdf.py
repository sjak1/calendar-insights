"""
PDF generation tool. Creates a PDF from text content for download.
Helvetica supports latin-1 only; we sanitize Unicode to avoid FPDF errors.
"""

import os
from fpdf import FPDF

# Replace common Unicode chars that cause latin-1 encode errors
_UNICODE_TO_ASCII = str.maketrans({
    "\u2014": "-",   # em dash
    "\u2013": "-",   # en dash
    "\u2018": "'",   # left single quote
    "\u2019": "'",   # right single quote
    "\u201c": '"',   # left double quote
    "\u201d": '"',   # right double quote
    "\u2022": "-",   # bullet
    "\u2705": "[Confirmed]",  # check mark emoji
    "\u23f3": "[Waitlist]",   # hourglass emoji
})


def _sanitize(text: str) -> str:
    """Replace Unicode chars outside latin-1 with ASCII equivalents."""
    if not text:
        return text
    result = text.translate(_UNICODE_TO_ASCII)
    # Fallback: any remaining non-latin-1 char -> ?
    return result.encode("latin-1", errors="replace").decode("latin-1")


def _normalize_symbols(text: str) -> str:
    """Apply symbol replacements that improve compatibility across fonts."""
    if not text:
        return text
    return text.translate(_UNICODE_TO_ASCII)


def _configure_font(pdf: FPDF) -> bool:
    """
    Configure a Unicode-capable font if available.

    Returns:
        True if Unicode font configured, False if latin-1 fallback should be used.
    """
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/Library/Fonts/NotoSans-Regular.ttf",
    ]
    for font_path in font_candidates:
        if os.path.exists(font_path):
            pdf.add_font("AppUnicode", "", font_path)
            pdf.add_font("AppUnicode", "B", font_path)
            pdf.set_font("AppUnicode", size=11)
            return True
    pdf.set_font("Helvetica", size=11)
    return False


def generate_pdf(content: str, title: str = "Document") -> bytes:
    """
    Generate a PDF from plain text content.

    Args:
        content: Text to include in the PDF (markdown-style formatting is stripped).
        title: Document title (shown as PDF metadata and optionally header).

    Returns:
        PDF file as bytes.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    unicode_font = _configure_font(pdf)

    # Set document title (sanitize only for latin-1 fallback)
    raw_title = (title or "Document")[:255]
    safe_title = _normalize_symbols(raw_title)
    if not unicode_font:
        safe_title = _sanitize(safe_title)

    # Optional header with title
    if safe_title:
        pdf.set_title(safe_title)
        pdf.set_font("AppUnicode" if unicode_font else "Helvetica", "B", size=14)
        pdf.cell(pdf.epw, 10, safe_title, ln=True)
        pdf.set_font("AppUnicode" if unicode_font else "Helvetica", size=11)
        pdf.ln(4)

    # Simple text: strip excessive newlines, wrap long lines
    w = pdf.epw  # effective width (page width minus margins)
    lines = (content or "").replace("\r\n", "\n").split("\n")
    for line in lines:
        # Trim and sanitize for latin-1 fallback only
        line = _normalize_symbols(line.strip())
        if not unicode_font:
            line = _sanitize(line)
        if not line:
            pdf.ln(4)
            continue
        # Decode common markdown-ish patterns to plain text
        if line.startswith("## "):
            pdf.set_font("AppUnicode" if unicode_font else "Helvetica", "B", size=12)
            pdf.cell(w, 8, line[3:], ln=True)
            pdf.set_font("AppUnicode" if unicode_font else "Helvetica", size=11)
        elif line.startswith("### "):
            pdf.set_font("AppUnicode" if unicode_font else "Helvetica", "B", size=11)
            pdf.cell(w, 7, line[4:], ln=True)
            pdf.set_font("AppUnicode" if unicode_font else "Helvetica", size=11)
        elif line.startswith("- ") or line.startswith("* "):
            pdf.multi_cell(w, 6, "  - " + line[2:])
        elif len(line) >= 2 and line[0] in "0123456789" and line[1] in ". ":
            pdf.multi_cell(w, 6, "  " + line)
        else:
            pdf.multi_cell(w, 6, line)

    return pdf.output()
