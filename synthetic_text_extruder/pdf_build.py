"""Local PDF builders: image stacks, magazine articles, contact sheets."""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _require_reportlab() -> None:
    try:
        import reportlab  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "reportlab is required to write PDFs. Run: pip install reportlab"
        ) from exc


def images_to_pdf(
    image_paths: list[Path],
    *,
    title: str = "Images",
) -> bytes:
    """One image per page, fitted to US Letter."""
    _require_reportlab()
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    page_w, page_h = letter
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(title[:200] or "Images")
    margin = 24
    max_w = page_w - margin * 2
    max_h = page_h - margin * 2
    wrote = False
    for path in image_paths:
        if path is None or not Path(path).is_file():
            continue
        try:
            reader = ImageReader(str(path))
            iw, ih = reader.getSize()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skip image for PDF %s: %s", path, exc)
            continue
        if iw <= 0 or ih <= 0:
            continue
        scale = min(max_w / iw, max_h / ih)
        dw, dh = iw * scale, ih * scale
        x = margin + (max_w - dw) / 2
        y = margin + (max_h - dh) / 2
        c.drawImage(reader, x, y, width=dw, height=dh, preserveAspectRatio=True, mask="auto")
        c.showPage()
        wrote = True
    if not wrote:
        c.setFont("Times-Roman", 14)
        c.drawString(margin, page_h - 72, "No images could be added to this PDF.")
        c.showPage()
    c.save()
    return buf.getvalue()


def article_pdf(
    *,
    title: str,
    sections: list[dict[str, Any]],
    skipped_ads: list[dict[str, Any]] | None = None,
) -> bytes:
    """Selectable-text PDF with optional embedded photos (readable reconstruction)."""
    _require_reportlab()
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        KeepTogether,
        ListFlowable,
        ListItem,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        title=(title or "Article")[:200],
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ArticleTitle",
        parent=styles["Title"],
        fontName="Times-Bold",
        fontSize=18,
        leading=22,
        spaceAfter=16,
    )
    h_style = ParagraphStyle(
        "ArticleH",
        parent=styles["Heading2"],
        fontName="Times-Bold",
        fontSize=13,
        leading=16,
        spaceBefore=12,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ArticleBody",
        parent=styles["BodyText"],
        fontName="Times-Roman",
        fontSize=11,
        leading=15,
        spaceAfter=8,
    )
    cap_style = ParagraphStyle(
        "ArticleCap",
        parent=styles["Italic"],
        fontName="Times-Italic",
        fontSize=9,
        leading=12,
        spaceAfter=10,
    )
    note_style = ParagraphStyle(
        "ArticleNote",
        parent=styles["BodyText"],
        fontName="Times-Roman",
        fontSize=10,
        leading=13,
        textColor="#444444",
    )
    story: list[Any] = []
    story.append(Paragraph(_escape(title or "Reconstructed article"), title_style))
    max_img_w = 6.3 * inch
    max_img_h = 4.5 * inch
    for section in sections:
        heading = str(section.get("heading") or "").strip()
        if heading:
            story.append(Paragraph(_escape(heading), h_style))
        for para in section.get("paragraphs") or []:
            text = str(para or "").strip()
            if text:
                story.append(Paragraph(_escape(text), body_style))
        photo = section.get("photoPath")
        if photo and Path(str(photo)).is_file():
            try:
                img = Image(str(photo))
                img._restrictSize(max_img_w, max_img_h)
                caption = str(section.get("photoCaption") or "").strip()
                block = [img, Spacer(1, 4)]
                if caption:
                    block.append(Paragraph(_escape(caption), cap_style))
                story.append(KeepTogether(block))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not embed photo %s: %s", photo, exc)
        if section.get("pageBreak"):
            story.append(PageBreak())
    ads = [a for a in (skipped_ads or []) if isinstance(a, dict)]
    if ads:
        story.append(Spacer(1, 16))
        story.append(Paragraph("Skipped ads (review)", h_style))
        items = []
        for ad in ads:
            label = str(ad.get("filename") or ad.get("title") or "page").strip()
            reason = str(ad.get("reason") or "Classified as an advertisement").strip()
            items.append(
                ListItem(Paragraph(_escape(f"{label} — {reason}"), note_style), leftIndent=12)
            )
        story.append(ListFlowable(items, bulletType="bullet"))
        story.append(
            Paragraph(
                "Ad detection is model judgment. Review skipped pages before you rely on this PDF.",
                note_style,
            )
        )
    if len(story) <= 1:
        story.append(Paragraph("No editorial text was recovered from these pages.", body_style))
    doc.build(story)
    return buf.getvalue()


def contact_sheet_png(
    image_paths: list[Path],
    *,
    columns: int = 4,
    thumb: int = 240,
    pad: int = 12,
) -> bytes:
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Pillow is required for contact sheets. Run: pip install pillow"
        ) from exc
    paths = [Path(p) for p in image_paths if p and Path(p).is_file()]
    if not paths:
        raise RuntimeError("No images available for a contact sheet.")
    cols = max(1, min(12, int(columns or 4)))
    rows = (len(paths) + cols - 1) // cols
    cell = thumb + pad
    width = pad + cols * cell
    height = pad + rows * cell
    sheet = Image.new("RGB", (width, height), (245, 245, 245))
    for index, path in enumerate(paths):
        try:
            im = Image.open(path)
            im.load()
            im = im.convert("RGB")
            im.thumbnail((thumb, thumb))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Skip contact-sheet image %s: %s", path, exc)
            continue
        col = index % cols
        row = index // cols
        x = pad + col * cell + (thumb - im.width) // 2
        y = pad + row * cell + (thumb - im.height) // 2
        sheet.paste(im, (x, y))
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    return buf.getvalue()


def _escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
