#!/usr/bin/env python3
"""Render the report's simple Markdown subset (requires reportlab)."""
import argparse
import html
from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def inline(text):
    text = html.escape(text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<link href="\2" color="#174a7e">\1</link>', text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font name="Courier" size="9">\1</font>', text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    body = ParagraphStyle("ReportBody", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=10.5, leading=14.2, spaceAfter=8, allowWidows=0, allowOrphans=0)
    title = ParagraphStyle("ReportTitle", parent=body, fontName="Helvetica-Bold", fontSize=18,
                           leading=23, alignment=TA_CENTER, spaceAfter=10)
    heading = ParagraphStyle("ReportHeading", parent=body, fontName="Helvetica-Bold", fontSize=12,
                             leading=16, spaceBefore=10, spaceAfter=7, keepWithNext=True)
    cell = ParagraphStyle("ReportCell", parent=body, fontSize=9, leading=11.5, spaceAfter=0)
    caption = ParagraphStyle("ReportCaption", parent=body, fontSize=9, leading=12, textColor=colors.HexColor("#444444"))
    reference = ParagraphStyle("ReportReference", parent=body, fontSize=9.5, leading=12.5, spaceAfter=6, keepWithNext=True)
    doc = SimpleDocTemplate(str(args.out), pagesize=letter, rightMargin=54, leftMargin=54,
                            topMargin=42, bottomMargin=44, title="Progress Report 2 - Group 16",
                            author="CS 4251 Group 16")
    lines = args.source.read_text().splitlines()
    story, i = [], 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), title))
            i += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(inline(line[3:]), heading))
            i += 1
            continue
        if re.match(r"^\d+\. ", line):
            story.append(Paragraph(inline(line), reference))
            i += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                if not re.fullmatch(r"[| :\-]+", lines[i]):
                    table_lines.append([part.strip() for part in lines[i].strip("|").split("|")])
                i += 1
            columns = len(table_lines[0])
            widths = {2: [128, 376], 4: [91, 135, 163, 115], 5: [59, 66, 108, 112, 159]}[columns]
            rows = [[Paragraph(inline(f"**{v}**" if n == 0 else v), cell) for v in row]
                    for n, row in enumerate(table_lines)]
            table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9eef3")),
                ("LINEBELOW", (0, 0), (-1, 0), .7, colors.HexColor("#8b9aaa")),
                ("LINEBELOW", (0, 1), (-1, -1), .3, colors.HexColor("#d4dce3")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            caption_index = i
            while caption_index < len(lines) and not lines[caption_index].strip():
                caption_index += 1
            if caption_index < len(lines) and lines[caption_index].startswith("*Table"):
                story.append(KeepTogether([
                    table, Spacer(1, 5),
                    Paragraph(inline(lines[caption_index]), caption),
                ]))
                i = caption_index + 1
            else:
                story.extend([table, Spacer(1, 9)])
            continue
        match = re.fullmatch(r"!\[[^\]]*\]\(([^)]+)\)", line)
        if match:
            figure = Image(str((args.source.parent / match[1]).resolve()))
            figure.drawHeight *= 504 / figure.drawWidth
            figure.drawWidth = 504
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            if i < len(lines) and lines[i].startswith("*Figure"):
                story.append(KeepTogether([figure, Spacer(1, 5), Paragraph(inline(lines[i]), caption)]))
                i += 1
            else:
                story.append(figure)
            continue
        paragraph = []
        while i < len(lines) and lines[i].strip() and not lines[i].startswith(("#", "|", "![")):
            paragraph.append(inline(lines[i].rstrip()) + ("<br/>" if lines[i].endswith("  ") else ""))
            i += 1
        story.append(Paragraph(" ".join(paragraph), caption if line.startswith("*Table") else body))

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.drawString(54, 24, "CS 4251 - Group 16 | Progress Report 2")
        canvas.drawRightString(letter[0] - 54, 24, str(document.page))
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(args.out)


if __name__ == "__main__":
    main()
