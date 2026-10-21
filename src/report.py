"""Report building: markdown from structured agent outputs, plus PDF export."""
import re
from datetime import datetime
from typing import List, Optional

from src.schemas import Extraction, ParamStatus

STATUS_ICON = {
    "Compliant": "✅",
    "Non-Compliant": "❌",
    "Insufficient Data": "⚠️",
    "Not Applicable": "➖",
}


def _cell(text) -> str:
    return str(text if text not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def build_markdown(extraction: Extraction, validation: Optional[dict], results: List[dict],
                   classification: Optional[dict] = None, source_name: str = "") -> str:
    counts = {s: sum(1 for r in results if r["status"] == s) for s in STATUS_ICON}
    evaluated = counts["Compliant"] + counts["Non-Compliant"]
    if counts["Non-Compliant"]:
        verdict = "NOT COMPLIANT"
    elif counts["Insufficient Data"]:
        verdict = "INCOMPLETE - resolve insufficient-data items"
    else:
        verdict = "COMPLIANT"

    out = [
        f"# Compliance Report - {extraction.drawing_type.value.title()} Drawing",
        "",
        f"- **Drawing:** {extraction.drawing_title or source_name or '-'}",
        f"- **Generated:** {datetime.now():%Y-%m-%d %H:%M}",
        "- **Codes:** IS 456:2000, SP 34:1987",
    ]
    if classification:
        out.append(f"- **Classified as:** {classification.get('drawing_type')} "
                   f"(confidence {classification.get('confidence', 0):.0%})"
                   + (" - overridden by engineer" if classification.get("overridden") else ""))
    out += [
        "",
        "## Summary",
        "",
        f"- **Checks run:** {len(results)} ({evaluated} with a verdict)",
        f"- **Compliant:** {counts['Compliant']}",
        f"- **Non-Compliant:** {counts['Non-Compliant']}",
        f"- **Insufficient Data:** {counts['Insufficient Data']}",
        f"- **Not Applicable:** {counts['Not Applicable']}",
        f"- **Overall verdict:** {verdict}",
        "",
        "## Compliance Checks",
        "",
        "| # | Check | Drawing value | Requirement | Clause / Ref | Status |",
        "|---|---|---|---|---|---|",
    ]
    for n, r in enumerate(results, 1):
        refs = "; ".join(c["ref"] for c in r.get("citations", []))
        clause = r.get("clause") or ""
        ref_cell = f"{clause} ({refs})" if clause and refs else (clause or refs)
        out.append(f"| {n} | {_cell(r['title'])} | {_cell(r.get('provided'))} | {_cell(r.get('requirement'))} "
                   f"| {_cell(ref_cell)} | {STATUS_ICON.get(r['status'], '')} {r['status']} |")

    out += ["", "## Reasoning", ""]
    for n, r in enumerate(results, 1):
        out += [f"**{n}. {r['title']}** - {r['status']}", "", r.get("reasoning") or "-"]
        if r.get("recommendation"):
            out += ["", f"*Recommendation:* {r['recommendation']}"]
        out.append("")

    if validation and validation.get("issues"):
        out += ["## Validator Findings", "", "| Severity | Parameters | Finding |", "|---|---|---|"]
        for i in validation["issues"]:
            out.append(f"| {i['severity']} | {_cell(', '.join(i['params']))} | {_cell(i['message'])} |")
        out.append("")

    out += ["## Verified Drawing Parameters", "", "| Parameter | Value | Source on drawing | Status |", "|---|---|---|---|"]
    for p in extraction.params:
        value = f"{p.value} {p.unit or ''}".strip() if p.value else "-"
        status = p.status.value + (" (edited)" if p.edited else "")
        out.append(f"| {_cell(p.label)} | {_cell(value)} | {_cell(p.source_location)} | {status} |")

    missing = [p for p in extraction.params if p.status != ParamStatus.FOUND]
    open_items = [r for r in results if r["status"] in ("Non-Compliant", "Insufficient Data")]
    out += ["", "## Missing or Wrong Information", ""]
    if not missing and not open_items:
        out.append("All items resolved.")
    for p in missing:
        out.append(f"- **{p.label}:** {p.clarification or p.status.value}")
    for r in open_items:
        out.append(f"- **{r['title']}:** {r['status']}" + (f" - {r['recommendation']}" if r.get("recommendation") else ""))
    out.append("")
    return "\n".join(out)


def markdown_to_pdf(markdown_text: str, output_path: str):
    """
    Converts markdown text to PDF using markdown + weasyprint.
    Falls back to reportlab if weasyprint fails (better Windows support).
    Returns (success: bool, error_message: str or None)
    """
    # Try WeasyPrint first
    try:
        import markdown
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration
        
        # Convert markdown to HTML
        html_content = markdown.markdown(markdown_text, extensions=['tables', 'fenced_code'])
        
        # Create full HTML document
        full_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    margin: 40px;
                    line-height: 1.6;
                }}
                table {{
                    border-collapse: collapse;
                    width: 100%;
                    margin: 20px 0;
                }}
                th, td {{
                    border: 1px solid #ddd;
                    padding: 8px;
                    text-align: left;
                }}
                th {{
                    background-color: #f2f2f2;
                }}
                code {{
                    background-color: #f4f4f4;
                    padding: 2px 4px;
                    border-radius: 3px;
                }}
            </style>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """
        
        # Generate PDF
        font_config = FontConfiguration()
        HTML(string=full_html).write_pdf(output_path, font_config=font_config)
        return True, None
    except ImportError:
        # WeasyPrint not installed, try reportlab
        pass
    except Exception as e:
        # WeasyPrint installed but failed (e.g., GTK libraries missing on Windows)
        error_msg = str(e)
        if 'libgobject' in error_msg.lower() or 'gtk' in error_msg.lower() or 'cannot load library' in error_msg.lower():
            # Try fallback with reportlab (better Windows support)
            pass
        else:
            # Other WeasyPrint errors - try reportlab anyway
            pass
    
    # Try fallback with reportlab (better Windows support)
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        import html
        
        # Create PDF
        doc = SimpleDocTemplate(output_path, pagesize=letter, 
                               rightMargin=72, leftMargin=72,
                               topMargin=72, bottomMargin=18)
        styles = getSampleStyleSheet()
        story = []
        
        # Define custom styles
        h1_style = ParagraphStyle(
            'H1',
            parent=styles['Heading1'],
            fontSize=12,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=6,
            spaceBefore=6,
        )
        
        h2_style = ParagraphStyle(
            'H2',
            parent=styles['Heading2'],
            fontSize=10,
            textColor=colors.HexColor('#2a2a2a'),
            spaceAfter=5,
            spaceBefore=5,
        )
        
        h3_style = ParagraphStyle(
            'H3',
            parent=styles['Heading3'],
            fontSize=9,
            textColor=colors.HexColor('#3a3a3a'),
            spaceAfter=4,
            spaceBefore=4,
        )
        
        normal_style = ParagraphStyle(
            'Normal',
            parent=styles['Normal'],
            fontSize=8,
            leading=10,
            spaceAfter=3,
        )
        
        # Helper function to convert markdown inline formatting to reportlab XML
        def convert_inline_formatting(text):
            # Escape HTML first
            text = html.escape(text)
            # Convert markdown to reportlab XML
            # Bold: **text** or __text__ (process before italic to avoid conflicts)
            text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
            text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
            # Code: `text` (process before italic)
            text = re.sub(r'`(.+?)`', r'<font name="Courier" color="darkblue">\1</font>', text)
            # Italic: *text* (single asterisk, not double)
            # Match *text* but not **text** (already processed)
            text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i>\1</i>', text)
            # Italic: _text_ (single underscore, not double)
            text = re.sub(r'(?<!_)_([^_]+?)_(?!_)', r'<i>\1</i>', text)
            return text
        
        # Helper function to parse markdown table
        def parse_table(lines, start_idx):
            """Parse a markdown table starting at start_idx. Returns (table_data, end_idx)"""
            table_data = []
            i = start_idx
            
            # Read header
            if i >= len(lines) or not lines[i].strip().startswith('|'):
                return None, start_idx
            
            header_line = lines[i].strip()
            if not header_line.startswith('|') or not header_line.endswith('|'):
                return None, start_idx
            
            headers = [cell.strip() for cell in header_line.split('|')[1:-1]]
            i += 1
            
            # Skip separator row (|---|---|)
            if i < len(lines) and re.match(r'^\|[\s\-:]+$', lines[i].strip()):
                i += 1
            
            # Read data rows
            while i < len(lines):
                row_line = lines[i].strip()
                if not row_line.startswith('|'):
                    break
                
                cells = [cell.strip() for cell in row_line.split('|')[1:-1]]
                if len(cells) == len(headers):
                    table_data.append(cells)
                i += 1
            
            if table_data:
                return [headers] + table_data, i
            return None, start_idx
        
        # Parse markdown line by line
        lines = markdown_text.split('\n')
        i = 0
        in_list = False
        list_items = []
        
        while i < len(lines):
            line = lines[i].rstrip()
            
            # Empty line
            if not line.strip():
                if in_list and list_items:
                    # Add list items
                    for item in list_items:
                        bullet_text = convert_inline_formatting(item)
                        story.append(Paragraph(f"• {bullet_text}", normal_style))
                    list_items = []
                    in_list = False
                story.append(Spacer(1, 0.1*inch))
                i += 1
                continue
            
            # Tables (check before headers to avoid conflicts)
            if line.strip().startswith('|') and '|' in line[1:]:
                table_data, new_idx = parse_table(lines, i)
                if table_data:
                    # Create table
                    table_style = TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#000000')),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                        ('FONTSIZE', (0, 0), (-1, 0), 7),
                        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                        ('TOPPADDING', (0, 0), (-1, 0), 6),
                        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                        ('FONTSIZE', (0, 1), (-1, -1), 7),
                        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
                        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                        ('LEFTPADDING', (0, 0), (-1, -1), 4),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                        ('TOPPADDING', (0, 1), (-1, -1), 5),
                        ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
                    ])
                    
                    # Convert table data to Paragraphs with formatting
                    formatted_table_data = []
                    for row_idx, row in enumerate(table_data):
                        formatted_row = []
                        for cell in row:
                            formatted_cell = Paragraph(convert_inline_formatting(cell), normal_style)
                            formatted_row.append(formatted_cell)
                        formatted_table_data.append(formatted_row)
                    
                    # Create table with auto column widths
                    # Calculate available width (page width minus margins)
                    available_width = letter[0] - 144  # 72*2 for left and right margins
                    col_widths = [available_width / len(table_data[0])] * len(table_data[0])
                    pdf_table = Table(formatted_table_data, colWidths=col_widths)
                    pdf_table.setStyle(table_style)
                    story.append(pdf_table)
                    story.append(Spacer(1, 0.15*inch))
                    i = new_idx
                    continue
            
            # Headers
            if line.startswith('#'):
                if in_list and list_items:
                    for item in list_items:
                        bullet_text = convert_inline_formatting(item)
                        story.append(Paragraph(f"• {bullet_text}", normal_style))
                    list_items = []
                    in_list = False
                
                if line.startswith('###'):
                    header_text = convert_inline_formatting(line[3:].strip())
                    story.append(Paragraph(header_text, h3_style))
                elif line.startswith('##'):
                    header_text = convert_inline_formatting(line[2:].strip())
                    story.append(Paragraph(header_text, h2_style))
                elif line.startswith('#'):
                    header_text = convert_inline_formatting(line[1:].strip())
                    story.append(Paragraph(header_text, h1_style))
                i += 1
                continue
            
            # Horizontal rule - just add spacing, don't render dashes
            if re.match(r'^---+$|^===+$|^\*\*\*+$', line):
                story.append(Spacer(1, 0.15*inch))
                i += 1
                continue
            
            # Unordered list
            if re.match(r'^[-*+]\s+', line):
                in_list = True
                item_text = re.sub(r'^[-*+]\s+', '', line)
                list_items.append(item_text)
                i += 1
                continue
            
            # Ordered list
            if re.match(r'^\d+\.\s+', line):
                if in_list and list_items:
                    for item in list_items:
                        bullet_text = convert_inline_formatting(item)
                        story.append(Paragraph(f"• {bullet_text}", normal_style))
                    list_items = []
                    in_list = False
                item_text = re.sub(r'^\d+\.\s+', '', line)
                item_text = convert_inline_formatting(item_text)
                story.append(Paragraph(item_text, normal_style))
                i += 1
                continue
            
            # Regular paragraph
            if in_list and list_items:
                for item in list_items:
                    bullet_text = convert_inline_formatting(item)
                    story.append(Paragraph(f"• {bullet_text}", normal_style))
                list_items = []
                in_list = False
            
            # Convert inline formatting and add paragraph
            formatted_text = convert_inline_formatting(line)
            story.append(Paragraph(formatted_text, normal_style))
            i += 1
        
        # Handle any remaining list items
        if in_list and list_items:
            for item in list_items:
                bullet_text = convert_inline_formatting(item)
                story.append(Paragraph(f"• {bullet_text}", normal_style))
        
        doc.build(story)
        return True, None
    except ImportError:
        return False, "PDF conversion requires either 'weasyprint' or 'reportlab'. Install with: `pip install weasyprint` or `pip install reportlab`"
    except Exception as e:
        return False, f"PDF conversion failed with reportlab: {str(e)}"
    
    # If we get here, both methods failed
    return False, "PDF conversion requires either 'weasyprint' (with GTK+ libraries) or 'reportlab'. For Windows, install reportlab: `pip install reportlab`"
