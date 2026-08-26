from __future__ import annotations

import io
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)
from xml.sax.saxutils import escape


# ============================================================
# BRAND / DESIGN
# ============================================================

BRAND_NAME = "AI PLAG DETECTOR"
REPORT_SUBTITLE = "Academic Integrity Analysis"

PAGE_WIDTH, PAGE_HEIGHT = A4

MARGIN_LEFT = 18 * mm
MARGIN_RIGHT = 18 * mm
MARGIN_TOP = 22 * mm
MARGIN_BOTTOM = 18 * mm

PURPLE = colors.HexColor("#6D28D9")
PURPLE_DARK = colors.HexColor("#4C1D95")
PURPLE_LIGHT = colors.HexColor("#F3E8FF")

TEXT = colors.HexColor("#171717")
TEXT_MUTED = colors.HexColor("#666666")
BORDER = colors.HexColor("#E5E7EB")
BACKGROUND = colors.HexColor("#F8FAFC")
WHITE = colors.white

RED = colors.HexColor("#DC2626")
RED_LIGHT = colors.HexColor("#FEF2F2")

ORANGE = colors.HexColor("#EA580C")
ORANGE_LIGHT = colors.HexColor("#FFF7ED")

GREEN = colors.HexColor("#16A34A")
GREEN_LIGHT = colors.HexColor("#F0FDF4")

YELLOW = colors.HexColor("#CA8A04")
YELLOW_LIGHT = colors.HexColor("#FEFCE8")

BLUE = colors.HexColor("#2563EB")
BLUE_LIGHT = colors.HexColor("#EFF6FF")


# ============================================================
# HELPERS
# ============================================================

def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp_score(value: Any) -> float:
    return max(0.0, min(100.0, safe_float(value)))


def format_score(value: Any) -> str:
    score = clamp_score(value)
    if score.is_integer():
        return f"{int(score)}%"
    return f"{score:.1f}%"


def escape_text(value: Any) -> str:
    if value is None:
        return ""
    return escape(str(value)).replace("\n", "<br/>")


def word_count_from_results(results: List[Dict[str, Any]]) -> int:
    text = " ".join(
        str(item.get("text", ""))
        for item in results
        if isinstance(item, dict)
    )
    return len(text.split())


def get_risk(score: Any) -> Dict[str, Any]:
    score = clamp_score(score)

    if score >= 70:
        return {
            "level": "HIGH",
            "color": RED,
            "light": RED_LIGHT,
        }

    if score >= 50:
        return {
            "level": "MEDIUM",
            "color": ORANGE,
            "light": ORANGE_LIGHT,
        }

    return {
        "level": "LOW",
        "color": GREEN,
        "light": GREEN_LIGHT,
    }


def get_ai_breakdown(results: List[Dict[str, Any]], overall: float) -> Dict[str, float]:
    """
    Current backend only gives us one AI score per paragraph.
    Therefore:
      AI-generated = overall score
      Human-written = 100 - overall score
      AI-refined = 0

    This intentionally does not invent an AI-refined classification.
    """

    ai_generated = clamp_score(overall)
    ai_refined = 0.0
    human_written = max(0.0, 100.0 - ai_generated - ai_refined)

    return {
        "ai_generated": ai_generated,
        "ai_refined": ai_refined,
        "human_written": human_written,
    }


def extract_sources(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Supports source data if your external API is later connected.

    The current backend does not expose source URLs yet, so this will
    simply return [] with your current setup.

    Supported examples:
      sources
      matches
      plagiarism_sources
      aggregate.sources
      aggregate.matches
    """

    candidates = [
        payload.get("sources"),
        payload.get("matches"),
        payload.get("plagiarism_sources"),
        (payload.get("aggregate") or {}).get("sources"),
        (payload.get("aggregate") or {}).get("matches"),
    ]

    raw_sources = next(
        (value for value in candidates if isinstance(value, list)),
        [],
    )

    normalized = []

    for index, source in enumerate(raw_sources, start=1):
        if isinstance(source, str):
            normalized.append({
                "rank": index,
                "name": source,
                "url": source,
                "score": None,
            })
            continue

        if not isinstance(source, dict):
            continue

        name = (
            source.get("name")
            or source.get("title")
            or source.get("domain")
            or source.get("source")
            or source.get("url")
            or f"Source {index}"
        )

        url = (
            source.get("url")
            or source.get("link")
            or source.get("source_url")
            or ""
        )

        score = (
            source.get("score")
            if source.get("score") is not None
            else source.get("match")
        )

        if score is None:
            score = source.get("percentage")

        normalized.append({
            "rank": index,
            "name": str(name),
            "url": str(url),
            "score": score,
        })

    return normalized


# ============================================================
# PDF CANVAS / HEADER / FOOTER
# ============================================================

class NumberedCanvasMixin:
    pass


def draw_header_footer(canvas, doc):
    canvas.saveState()

    page_number = canvas.getPageNumber()

    # Header line
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.6)
    canvas.line(
        MARGIN_LEFT,
        PAGE_HEIGHT - 14 * mm,
        PAGE_WIDTH - MARGIN_RIGHT,
        PAGE_HEIGHT - 14 * mm,
    )

    # Header brand
    canvas.setFillColor(PURPLE_DARK)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawString(
        MARGIN_LEFT,
        PAGE_HEIGHT - 10.5 * mm,
        BRAND_NAME,
    )

    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(
        PAGE_WIDTH - MARGIN_RIGHT,
        PAGE_HEIGHT - 10.5 * mm,
        REPORT_SUBTITLE,
    )

    # Footer line
    canvas.setStrokeColor(BORDER)
    canvas.line(
        MARGIN_LEFT,
        12 * mm,
        PAGE_WIDTH - MARGIN_RIGHT,
        12 * mm,
    )

    canvas.setFillColor(TEXT_MUTED)
    canvas.setFont("Helvetica", 7)

    canvas.drawString(
        MARGIN_LEFT,
        7.5 * mm,
        "Generated by AI Plag Detector",
    )

    canvas.drawRightString(
        PAGE_WIDTH - MARGIN_RIGHT,
        7.5 * mm,
        f"Page {page_number}",
    )

    canvas.restoreState()


# ============================================================
# CUSTOM DOCUMENT
# ============================================================

class ReportDocument(BaseDocTemplate):

    def __init__(self, filename, **kwargs):
        super().__init__(
            filename,
            pagesize=A4,
            leftMargin=MARGIN_LEFT,
            rightMargin=MARGIN_RIGHT,
            topMargin=MARGIN_TOP,
            bottomMargin=MARGIN_BOTTOM,
            **kwargs,
        )

        frame = Frame(
            MARGIN_LEFT,
            MARGIN_BOTTOM,
            PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT,
            PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM,
            id="normal",
        )

        template = PageTemplate(
            id="main",
            frames=[frame],
            onPage=draw_header_footer,
        )

        self.addPageTemplates([template])


# ============================================================
# STYLES
# ============================================================

def create_styles():
    styles = getSampleStyleSheet()

    return {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=25,
            leading=29,
            textColor=PURPLE_DARK,
            alignment=TA_LEFT,
            spaceAfter=6,
        ),

        "subtitle": ParagraphStyle(
            "ReportSubtitle",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=TEXT_MUTED,
            spaceAfter=16,
        ),

        "section": ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=19,
            textColor=TEXT,
            spaceBefore=8,
            spaceAfter=10,
        ),

        "small_heading": ParagraphStyle(
            "SmallHeading",
            parent=styles["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=TEXT,
            spaceAfter=5,
        ),

        "body": ParagraphStyle(
            "Body",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=14,
            textColor=TEXT,
            spaceAfter=7,
        ),

        "body_small": ParagraphStyle(
            "BodySmall",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=TEXT_MUTED,
            spaceAfter=5,
        ),

        "document_text": ParagraphStyle(
            "DocumentText",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9.3,
            leading=14.2,
            textColor=TEXT,
            alignment=TA_LEFT,
            spaceAfter=0,
        ),

        "center": ParagraphStyle(
            "Center",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=13,
            textColor=TEXT_MUTED,
            alignment=TA_CENTER,
        ),

        "score_big": ParagraphStyle(
            "ScoreBig",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=34,
            leading=38,
            textColor=PURPLE_DARK,
            alignment=TA_CENTER,
        ),

        "score_label": ParagraphStyle(
            "ScoreLabel",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=10,
            leading=13,
            textColor=TEXT,
            alignment=TA_CENTER,
        ),

        "stat_value": ParagraphStyle(
            "StatValue",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=18,
            textColor=TEXT,
            alignment=TA_LEFT,
        ),

        "stat_label": ParagraphStyle(
            "StatLabel",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=TEXT_MUTED,
            alignment=TA_LEFT,
        ),

        "source_title": ParagraphStyle(
            "SourceTitle",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=9.5,
            leading=13,
            textColor=TEXT,
        ),

        "source_url": ParagraphStyle(
            "SourceUrl",
            parent=styles["Normal"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10,
            textColor=BLUE,
        ),

        "terms_heading": ParagraphStyle(
            "TermsHeading",
            parent=styles["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.8,
            leading=10.5,
            textColor=TEXT,
            spaceAfter=0,
        ),

        "terms_body": ParagraphStyle(
            "TermsBody",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=7.5,
            leading=10.2,
            textColor=TEXT_MUTED,
            spaceAfter=0,
        ),

        "warning": ParagraphStyle(
            "Warning",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=8.3,
            leading=12.5,
            textColor=colors.HexColor("#7C2D12"),
        ),
    }


# ============================================================
# COMPONENTS
# ============================================================

def build_brand_header(styles, report_type: str):
    story = []

    story.append(Spacer(1, 3 * mm))

    story.append(
        Paragraph(
            escape(BRAND_NAME),
            styles["title"],
        )
    )

    story.append(
        Paragraph(
            escape(
                "AI Detection Report"
                if report_type == "ai"
                else "Similarity Report"
            ),
            styles["subtitle"],
        )
    )

    story.append(
        HRFlowable(
            width="100%",
            thickness=1,
            color=PURPLE,
            spaceBefore=2,
            spaceAfter=12,
        )
    )

    return story


def build_document_info(styles, document_name, word_count, result_count, report_date):
    data = [
        [
            Paragraph("<b>DOCUMENT</b>", styles["body_small"]),
            Paragraph("<b>WORD COUNT</b>", styles["body_small"]),
            Paragraph("<b>RESULTS COUNT</b>", styles["body_small"]),
        ],
        [
            Paragraph(
                escape(document_name),
                styles["body"],
            ),
            Paragraph(
                f"<b>{word_count:,}</b>",
                styles["body"],
            ),
            Paragraph(
                f"<b>{result_count}</b>",
                styles["body"],
            ),
        ],
        [
            Paragraph("<b>SUBMISSION DATE</b>", styles["body_small"]),
            Paragraph("<b>REPORT DATE</b>", styles["body_small"]),
            Paragraph("<b>REPORT TYPE</b>", styles["body_small"]),
        ],
        [
            Paragraph(report_date, styles["body"]),
            Paragraph(report_date, styles["body"]),
            Paragraph(
                "AI Detection"
                if report_type_global == "ai"
                else "Similarity Analysis",
                styles["body"],
            ),
        ],
    ]

    table = Table(
        data,
        colWidths=[
            83 * mm,
            43 * mm,
            43 * mm,
        ],
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    return table


def build_score_card(styles, score, label, report_type):
    risk = get_risk(score)

    title = (
        "OVERALL AI SCORE"
        if report_type == "ai"
        else "OVERALL SIMILARITY"
    )

    description = (
        "of analyzed text is likely AI-generated"
        if report_type == "ai"
        else "of analyzed text shows similarity"
    )

    score_table = Table(
        [
            [
                Paragraph(title, styles["body_small"]),
            ],
            [
                Paragraph(
                    format_score(score),
                    ParagraphStyle(
                        "CardScore",
                        parent=styles["score_big"],
                        textColor=risk["color"],
                    ),
                )
            ],
            [
                Paragraph(
                    escape(description),
                    styles["center"],
                )
            ],
            [
                Paragraph(
                    f"<b>{escape(label.upper())} RISK</b>",
                    ParagraphStyle(
                        "CardRisk",
                        parent=styles["score_label"],
                        textColor=risk["color"],
                    ),
                )
            ],
        ],
        colWidths=[169 * mm],
        hAlign="LEFT",
    )

    score_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), risk["light"]),
                ("BOX", (0, 0), (-1, -1), 1.0, risk["color"]),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 15),
                ("RIGHTPADDING", (0, 0), (-1, -1), 15),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )

    return score_table


def build_ai_breakdown(styles, breakdown):
    rows = [
        [
            Paragraph("<b>AI-generated</b>", styles["body"]),
            Paragraph(
                format_score(breakdown["ai_generated"]),
                styles["body"],
            ),
        ],
        [
            Paragraph("<b>Human-written &amp; AI-refined</b>", styles["body"]),
            Paragraph(
                format_score(breakdown["ai_refined"]),
                styles["body"],
            ),
        ],
        [
            Paragraph("<b>Human-written</b>", styles["body"]),
            Paragraph(
                format_score(breakdown["human_written"]),
                styles["body"],
            ),
        ],
    ]

    table = Table(
        rows,
        colWidths=[135 * mm, 34 * mm],
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), WHITE),
                ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )

    return table


def build_warning_box(styles, report_type):
    if report_type == "ai":
        message = (
            "<b>Caution:</b> AI detection results are probabilistic and "
            "should not be treated as absolute proof of authorship. "
            "Use these results as an analytical indicator alongside "
            "human review and other academic-integrity checks."
        )
    else:
        message = (
            "<b>Caution:</b> Similarity results indicate matching or "
            "repeated text detected by the configured analysis system. "
            "A similarity percentage does not by itself establish plagiarism."
        )

    table = Table(
        [
            [
                Paragraph(
                    "!",
                    ParagraphStyle(
                        "WarningIcon",
                        parent=styles["body"],
                        fontSize=15,
                        textColor=ORANGE,
                    ),
                ),
                Paragraph(message, styles["warning"]),
            ]
        ],
        colWidths=[12 * mm, 157 * mm],
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), ORANGE_LIGHT),
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#FDBA74")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    return table


def build_document_paragraph(styles, item, report_type):
    score = clamp_score(item.get("score", 0))
    risk = get_risk(score)

    text = escape_text(item.get("text", ""))

    if report_type == "ai":
        label = item.get("label") or "AI"
        heading = (
            f"Paragraph {item.get('index', '')} • "
            f"{escape(str(label))} • {format_score(score)}"
        )
    else:
        label = item.get("plagiarism_label") or item.get("label") or "Similarity"
        plagiarism_score = item.get("plagiarism_score")

        if plagiarism_score is None:
            plagiarism_score = score

        heading = (
            f"Paragraph {item.get('index', '')} • "
            f"{escape(str(label))} • {format_score(plagiarism_score)}"
        )

    reason = escape_text(item.get("reason", ""))

    content = [
        [
            Paragraph(
                heading,
                ParagraphStyle(
                    f"ParaHeading_{item.get('index', '')}",
                    parent=styles["small_heading"],
                    textColor=risk["color"],
                ),
            )
        ],
        [
            Paragraph(
                text,
                styles["document_text"],
            )
        ],
    ]

    if reason:
        content.append(
            [
                Paragraph(
                    f"<font color='#666666'><b>Analysis:</b> {reason}</font>",
                    styles["body_small"],
                )
            ]
        )

    table = Table(
        content,
        colWidths=[169 * mm],
        hAlign="LEFT",
    )

    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), risk["light"]),
                ("BOX", (0, 0), (-1, -1), 0.6, risk["color"]),
                ("LINEBEFORE", (0, 0), (0, -1), 3, risk["color"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )

    return table


def build_sources_section(styles, sources):
    story = []

    story.append(
        Paragraph(
            "Similarity Sources",
            styles["section"],
        )
    )

    if not sources:
        story.append(
            Paragraph(
                "No external source-level matches were provided by the current analysis response. "
                "The current local plagiarism detector reports internal document duplication rather "
                "than Internet or academic-database source matches.",
                styles["body"],
            )
        )
        return story

    for source in sources:
        score = source.get("score")

        score_text = (
            format_score(score)
            if score is not None
            else "Match"
        )

        source_name = escape(str(source.get("name", "Unknown source")))
        url = escape(str(source.get("url", "")))

        source_table = Table(
            [
                [
                    Paragraph(
                        f"<b>{source.get('rank', '')}. {source_name}</b>",
                        styles["source_title"],
                    ),
                    Paragraph(
                        f"<b>{score_text}</b>",
                        ParagraphStyle(
                            "SourceScore",
                            parent=styles["source_title"],
                            alignment=TA_RIGHT,
                            textColor=PURPLE_DARK,
                        ),
                    ),
                ],
                [
                    Paragraph(
                        url if url else "Source URL not provided",
                        styles["source_url"],
                    ),
                    "",
                ],
            ],
            colWidths=[137 * mm, 32 * mm],
            hAlign="LEFT",
        )

        source_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BACKGROUND),
                    ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                    ("SPAN", (0, 1), (1, 1)),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )

        story.append(source_table)
        story.append(Spacer(1, 4 * mm))

    return story


def build_statistics(styles, results, report_type):
    if not results:
        return None

    if report_type == "ai":
        high = len([r for r in results if clamp_score(r.get("score")) >= 60])
        medium = len([
            r for r in results
            if 40 <= clamp_score(r.get("score")) < 60
        ])
        low = len([r for r in results if clamp_score(r.get("score")) < 40])

        cards = [
            ("HIGH AI RISK", high, RED, RED_LIGHT),
            ("MEDIUM AI RISK", medium, ORANGE, ORANGE_LIGHT),
            ("LOW AI RISK", low, GREEN, GREEN_LIGHT),
        ]
    else:
        high = len([
            r for r in results
            if clamp_score(
                r.get("plagiarism_score", r.get("score"))
            ) >= 60
        ])

        medium = len([
            r for r in results
            if 35 <= clamp_score(
                r.get("plagiarism_score", r.get("score"))
            ) < 60
        ])

        low = len([
            r for r in results
            if clamp_score(
                r.get("plagiarism_score", r.get("score"))
            ) < 35
        ])

        cards = [
            ("HIGH SIMILARITY", high, RED, RED_LIGHT),
            ("MEDIUM SIMILARITY", medium, ORANGE, ORANGE_LIGHT),
            ("LOW SIMILARITY", low, GREEN, GREEN_LIGHT),
        ]

    cells = []

    for label, value, color, light in cards:
        cells.append(
            Table(
                [
                    [
                        Paragraph(
                            str(value),
                            ParagraphStyle(
                                f"Stat_{label}",
                                parent=styles["stat_value"],
                                textColor=color,
                            ),
                        )
                    ],
                    [
                        Paragraph(
                            label,
                            styles["stat_label"],
                        )
                    ],
                ],
                colWidths=[52 * mm],
            )
        )

    outer = Table(
        [cells],
        colWidths=[56 * mm, 56 * mm, 56 * mm],
        hAlign="LEFT",
    )

    outer.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )

    return outer



def build_terms_conditions(styles):
    """Build the final Terms & Conditions section for the report."""
    terms = [
        (
            "1. Purpose of the Report",
            "This report is generated for informational and assessment purposes to help "
            "identify potential textual similarities and/or indicators of AI-generated content "
            "within the submitted document."
        ),
        (
            "2. Accuracy & Limitations",
            "Automated AI and similarity detection technologies are not infallible. Results may "
            "contain false positives or false negatives and should not be considered conclusive "
            "proof of plagiarism, authorship, or AI-generated content."
        ),
        (
            "3. Similarity Results",
            "A similarity percentage represents textual overlap detected by the configured "
            "analysis system. Similarity alone does not establish plagiarism, as common phrases, "
            "proper terminology, quotations, or legitimately reused material may contribute to a match."
        ),
        (
            "4. AI Detection Results",
            "AI detection scores are automated estimates and should be interpreted as indicators "
            "rather than definitive evidence that content was generated or refined using AI."
        ),
        (
            "5. Human Review",
            "Results should be reviewed by a qualified person before any academic, professional, "
            "disciplinary, or other significant decision is made."
        ),
        (
            "6. Source & Dataset Availability",
            "Detection results may vary depending on the sources, databases, models, datasets, "
            "and analysis methods available to the system at the time of processing."
        ),
        (
            "7. Confidentiality",
            "The submitted document and generated report should be handled securely and should "
            "not be shared with unauthorized individuals."
        ),
        (
            "8. No Guarantee",
            "The system does not guarantee detection of every instance of copied, paraphrased, "
            "or AI-generated content."
        ),
        (
            "9. Use of Results",
            "This report is intended to be used as a supporting assessment tool and should not "
            "be the sole basis for determining plagiarism, academic misconduct, authorship, or originality."
        ),
        (
            "10. Acceptance",
            "By using this report, the user acknowledges and accepts the limitations associated "
            "with automated AI and similarity detection."
        ),
    ]

    story = []

    story.append(
        Paragraph("Terms & Conditions", styles["section"])
    )

    story.append(
        Paragraph(
            "Please review the following terms before relying on the results of this automated report.",
            styles["body_small"],
        )
    )

    rows = []
    for heading, text in terms:
        rows.append([
            Paragraph(f"<b>{escape(heading)}</b>", styles["terms_heading"]),
            Paragraph(escape(text), styles["terms_body"]),
        ])

    table = Table(
        rows,
        colWidths=[42 * mm, 127 * mm],
        hAlign="LEFT",
        repeatRows=0,
    )

    table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BACKGROUND),
            ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ])
    )

    story.append(table)
    return story


# ============================================================
# MAIN PDF GENERATOR
# ============================================================

# Used only by build_document_info to show report type.
# It is set locally by generate_report_pdf.
report_type_global = "ai"


def generate_report_pdf(payload: Dict[str, Any]) -> bytes:
    """
    Generate a professional A4 PDF report.

    Expected payload:
    {
        "results": [...],
        "aggregate": {...},
        "title": "...",
        "format": "pdf",
        "document_name": "...",
        "analysis_mode": "ai" | "plagiarism",
        "sources": [...] optional
    }
    """

    global report_type_global

    results = payload.get("results", [])
    aggregate = payload.get("aggregate", {})
    report_type = payload.get("analysis_mode", "ai")

    if report_type not in {"ai", "plagiarism"}:
        report_type = "ai"

    report_type_global = report_type

    if not isinstance(results, list):
        results = []

    if not isinstance(aggregate, dict):
        aggregate = {}

    document_name = (
        payload.get("document_name")
        or payload.get("title")
        or "Untitled Document"
    )

    document_name = str(document_name)

    report_date = datetime.now().strftime("%d %b %Y")

    word_count = payload.get("word_count")

    if word_count is None:
        word_count = word_count_from_results(results)

    try:
        word_count = int(word_count)
    except (TypeError, ValueError):
        word_count = word_count_from_results(results)

    result_count = len(results)

    if report_type == "plagiarism":
        overall = aggregate.get("plagiarism_score")

        if overall is None:
            overall = aggregate.get("overall_score", 0)

        label = (
            aggregate.get("plagiarism_label")
            or "Similarity"
        )

    else:
        overall = aggregate.get("overall_score", 0)
        label = aggregate.get("ai_label") or "AI"

    overall = clamp_score(overall)

    buffer = io.BytesIO()

    doc = ReportDocument(
        buffer,
        title=f"{BRAND_NAME} - {document_name}",
        author=BRAND_NAME,
    )

    styles = create_styles()

    story = []

    # --------------------------------------------------------
    # COVER / SUMMARY
    # --------------------------------------------------------

    story.extend(
        build_brand_header(
            styles,
            report_type,
        )
    )

    story.append(
        Paragraph(
            escape(document_name),
            ParagraphStyle(
                "DocumentName",
                parent=styles["section"],
                fontSize=13,
                leading=17,
                textColor=TEXT,
            ),
        )
    )

    story.append(
        build_document_info(
            styles,
            document_name,
            word_count,
            result_count,
            report_date,
        )
    )

    story.append(Spacer(1, 8 * mm))

    risk = get_risk(overall)

    story.append(
        build_score_card(
            styles,
            overall,
            risk["level"],
            report_type,
        )
    )

    story.append(Spacer(1, 6 * mm))

    if report_type == "ai":
        breakdown = get_ai_breakdown(
            results,
            overall,
        )

        story.append(
            Paragraph(
                "AI Detection Breakdown",
                styles["section"],
            )
        )

        story.append(
            build_ai_breakdown(
                styles,
                breakdown,
            )
        )

    else:
        story.append(
            Paragraph(
                "Similarity Summary",
                styles["section"],
            )
        )

        plagiarism_label_value = (
            aggregate.get("plagiarism_label")
            or risk["level"]
        )

        summary_rows = [
            [
                Paragraph("<b>Overall similarity</b>", styles["body"]),
                Paragraph(
                    format_score(overall),
                    styles["body"],
                ),
            ],
            [
                Paragraph("<b>Risk classification</b>", styles["body"]),
                Paragraph(
                    escape(str(plagiarism_label_value)),
                    styles["body"],
                ),
            ],
        ]

        summary_table = Table(
            summary_rows,
            colWidths=[135 * mm, 34 * mm],
            hAlign="LEFT",
        )

        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BACKGROUND),
                    ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 9),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )

        story.append(summary_table)

    story.append(Spacer(1, 7 * mm))

    statistics = build_statistics(
        styles,
        results,
        report_type,
    )

    if statistics:
        story.append(
            Paragraph(
                "Analysis Distribution",
                styles["section"],
            )
        )
        story.append(statistics)
        story.append(Spacer(1, 7 * mm))

    story.append(
        build_warning_box(
            styles,
            report_type,
        )
    )

    # --------------------------------------------------------
    # DOCUMENT ANALYSIS
    # --------------------------------------------------------

    story.append(PageBreak())

    story.append(
        Paragraph(
            "Document Analysis",
            styles["section"],
        )
    )

    story.append(
        Paragraph(
            "The following section contains the extracted document text "
            "with analysis indicators applied to each detected paragraph.",
            styles["body"],
        )
    )

    if not results:
        story.append(
            Paragraph(
                "No paragraph analysis results were returned.",
                styles["body"],
            )
        )
    else:
        for item in results:
            if not isinstance(item, dict):
                continue

            story.append(
                KeepTogether(
                    [
                        build_document_paragraph(
                            styles,
                            item,
                            report_type,
                        ),
                        Spacer(1, 3 * mm),
                    ]
                )
            )

    # --------------------------------------------------------
    # SOURCES
    # --------------------------------------------------------

    if report_type == "plagiarism":
        sources = extract_sources(payload)

        story.append(PageBreak())

        story.extend(
            build_sources_section(
                styles,
                sources,
            )
        )

        story.append(Spacer(1, 7 * mm))

        story.append(
            Paragraph(
                "Methodology Note",
                styles["section"],
            )
        )

        story.append(
            Paragraph(
                "The current local plagiarism analysis checks for repeated "
                "phrasing and duplicate n-gram patterns within the uploaded "
                "document. External source-level matches are displayed only "
                "when source data is supplied by the configured external API.",
                styles["body"],
            )
        )

    # --------------------------------------------------------
    # FINAL PAGE / DISCLAIMER / TERMS & CONDITIONS
    # --------------------------------------------------------

    story.append(PageBreak())

    story.append(
        Paragraph("Report Disclaimer", styles["section"])
    )

    final_box = Table(
        [
            [
                Paragraph(
                    "<b>Important Notice</b>",
                    styles["small_heading"],
                )
            ],
            [
                Paragraph(
                    "This report is an automated analytical assessment. "
                    "AI-detection and similarity scores should be interpreted "
                    "as indicators rather than definitive proof of authorship "
                    "or academic misconduct. Final decisions should involve "
                    "appropriate human review.",
                    styles["body_small"],
                )
            ],
        ],
        colWidths=[169 * mm],
        hAlign="LEFT",
    )

    final_box.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), BACKGROUND),
                ("BOX", (0, 0), (-1, -1), 0.7, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    story.append(final_box)
    story.append(Spacer(1, 5 * mm))

    story.extend(build_terms_conditions(styles))

    doc.build(story)

    return buffer.getvalue()