import asyncio
import io
import os
import re
from typing import Any, Dict, List, Optional
from datetime import datetime
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from system_ops import WORK_DIR
from backend.tools.charts import render_chart
from backend.tools.result_schema import create_office_result


def _shade_cell(cell, fill_hex: str):
    """Fill a table cell with a background colour for a human-made look."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_hex)
    tc_pr.append(shd)


class Office:
    """Word/DOCX generation tools with support for rich structured research reports."""

    @staticmethod
    async def create_docx(
        content: str = "",
        title: str = "Document",
        headings: List[str] = None,
        lists: List[str] = None,
        tables: List[List] = None,
        charts: List[Dict] = None,
        save_path: str = "",
        structured_report: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a beautifully formatted Microsoft Word .docx file.

        `charts` is an optional list of chart specs ({type: pie|bar|histogram|
        line, title, labels, values|data, bins, width, height}) - each one is
        rendered and embedded as a real image so reports look human-made."""
        try:
            # Determine save path
            if not save_path:
                filename = f"{title.replace(' ', '_')}_{os.path.basename(os.getcwd())}.docx"
                save_path = os.path.join(WORK_DIR, "documents", filename)
            elif not save_path.endswith('.docx'):
                save_path = save_path + '.docx'

            # Ensure directory exists
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

            doc = Document()

            # Set normal style font to Calibri / 11pt
            style = doc.styles['Normal']
            font = style.font
            font.name = 'Calibri'
            font.size = Pt(11)
            font.color.rgb = RGBColor(0x33, 0x33, 0x33)

            # ── Mode A: Structured Report Object ─────────────────────────────
            if structured_report and isinstance(structured_report, dict):
                Office._build_from_structured_report(doc, structured_report, title)

            # ── Mode B: Markdown-Formatted Content String ─────────────────────
            elif content and ("#" in content or "**" in content or "\n* " in content or "\n- " in content):
                Office._build_from_markdown(doc, content, title)

            # ── Mode C: Standard / Legacy Content Creation ────────────────────
            else:
                if title:
                    doc.add_heading(title, level=0)

                if headings and not content:
                    for heading in headings:
                        doc.add_heading(heading, level=1)

                if content:
                    for paragraph in content.split('\n'):
                        p_strip = paragraph.strip()
                        if p_strip:
                            # Check if line looks like a section header (ALL CAPS or short)
                            if p_strip.isupper() and len(p_strip) < 60:
                                doc.add_heading(p_strip.title(), level=1)
                            elif p_strip.startswith(("- ", "* ", "• ")):
                                doc.add_paragraph(p_strip[2:].strip(), style='List Bullet')
                            else:
                                doc.add_paragraph(p_strip)

                if lists:
                    for item in lists:
                        doc.add_paragraph(item, style='List Bullet')

                if tables:
                    for table_data in tables:
                        if isinstance(table_data, list) and table_data:
                            Office._add_styled_table(doc, table_data)

            # ── Embedded charts (rendered to real images) ─────────────────────
            for chart_spec in charts or []:
                if not isinstance(chart_spec, dict):
                    continue
                try:
                    png, cw, ch = render_chart(chart_spec)
                    cap_title = str(chart_spec.get("title", "") or "").strip()
                    p = doc.add_paragraph()
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = p.add_run()
                    run.add_picture(io.BytesIO(png), width=Inches(min(float(cw), 6.2)))
                    if cap_title:
                        cap = doc.add_paragraph()
                        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        cap_run = cap.add_run(cap_title)
                        cap_run.italic = True
                        cap_run.font.size = Pt(9)
                        cap_run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
                except Exception as chart_err:
                    # Never let one render failure kill the whole document
                    print(f"[office] Chart embed skipped ({chart_err})")

            doc.save(save_path)
            return create_office_result("create_docx", "success", f"Word document created: {save_path}", path=save_path, document_type="docx")
        except Exception as e:
            return create_office_result("create_docx", "error", f"Failed to create Word document: {str(e)}")

    @staticmethod
    def _add_styled_table(doc: Document, table_data: List[List]):
        """Add a polished, readable table with a bold shaded header row."""
        if not table_data or not isinstance(table_data, list):
            return
        rows = len(table_data)
        cols = max(len(row) for row in table_data) if table_data else 0
        if cols == 0:
            return
        table = doc.add_table(rows=rows, cols=cols)
        table.style = 'Table Grid'
        for i, row_data in enumerate(table_data):
            for j in range(cols):
                cell = table.rows[i].cells[j]
                txt = str(row_data[j]) if j < len(row_data) else ""
                cell.text = ""
                para = cell.paragraphs[0]
                run = para.add_run(txt)
                if i == 0:
                    run.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    _shade_cell(cell, "2E86AB")
        # Give alternating rows a light shade so it reads like a real report
        for i in range(1, rows):
            if i % 2 == 0:
                for j in range(cols):
                    _shade_cell(table.rows[i].cells[j], "EAF3F8")
        doc.add_paragraph()

    @staticmethod
    def _build_from_structured_report(doc: Document, report: Dict[str, Any], default_title: str):
        """Construct a publication-grade Word document from a structured research report dictionary."""
        # Document Title
        doc_title = report.get("title") or default_title or "Research Report"
        title_p = doc.add_heading(doc_title, level=0)
        title_p.alignment = WD_ALIGN_PARAGRAPH.LEFT

        # Subtitle / Metadata
        subtitle_text = report.get("subtitle") or "Synthesized Intelligence Report | J.A.R.V.I.S. Research Division"
        sub_p = doc.add_paragraph()
        sub_run = sub_p.add_run(subtitle_text)
        sub_run.italic = True
        sub_run.font.size = Pt(10)
        sub_run.font.color.rgb = RGBColor(0x77, 0x77, 0x77)

        doc.add_paragraph()  # Spacing

        # 1. Executive Summary
        if report.get("executive_summary"):
            doc.add_heading("1. Executive Summary", level=1)
            for p in str(report["executive_summary"]).split("\n\n"):
                if p.strip():
                    doc.add_paragraph(p.strip())

        # 2. Introduction
        if report.get("introduction"):
            doc.add_heading("2. Introduction & Background", level=1)
            for p in str(report["introduction"]).split("\n\n"):
                if p.strip():
                    doc.add_paragraph(p.strip())

        # 3. Key Findings
        if report.get("key_findings"):
            doc.add_heading("3. Key Findings & Thematic Analysis", level=1)
            findings = report["key_findings"]
            if isinstance(findings, list):
                for item in findings:
                    doc.add_paragraph(str(item).strip(), style='List Bullet')
            else:
                doc.add_paragraph(str(findings).strip())

        # 4. Source Insights
        if report.get("source_insights"):
            doc.add_heading("4. Detailed Source Insights", level=1)
            insights = report["source_insights"]
            if isinstance(insights, list):
                for idx, src in enumerate(insights, 1):
                    s_title = src.get("source_title", f"Source {idx}")
                    s_url = src.get("source_url", "")
                    s_takeaway = src.get("key_takeaway", "")

                    p = doc.add_paragraph()
                    r_bold = p.add_run(f"• Source {idx}: {s_title}")
                    r_bold.bold = True

                    if s_url and s_url != "N/A":
                        p_url = doc.add_paragraph()
                        r_url_label = p_url.add_run("   URL: ")
                        r_url_label.font.size = Pt(9.5)
                        r_url_val = p_url.add_run(s_url)
                        r_url_val.font.size = Pt(9.5)
                        r_url_val.font.color.rgb = RGBColor(0x00, 0x66, 0xCC)

                    if s_takeaway:
                        p_takeaway = doc.add_paragraph()
                        r_t_label = p_takeaway.add_run("   Key Contribution: ")
                        r_t_label.italic = True
                        p_takeaway.add_run(s_takeaway)

        # 5. Cross-Source Analysis
        if report.get("cross_source_analysis"):
            doc.add_heading("5. Cross-Source Comparative Analysis", level=1)
            for p in str(report["cross_source_analysis"]).split("\n\n"):
                if p.strip():
                    doc.add_paragraph(p.strip())

        # 6. Conclusion
        if report.get("conclusion"):
            doc.add_heading("6. Conclusion & Implications", level=1)
            for p in str(report["conclusion"]).split("\n\n"):
                if p.strip():
                    doc.add_paragraph(p.strip())

        # 7. References
        if report.get("references"):
            doc.add_heading("7. References & Verified Sources", level=1)
            refs = report["references"]
            if isinstance(refs, list):
                for idx, r in enumerate(refs, 1):
                    if isinstance(r, dict):
                        r_title = r.get("title", f"Source {idx}")
                        r_url = r.get("url", "N/A")
                        doc.add_paragraph(f"[{idx}] {r_title} — {r_url}")
                    else:
                        doc.add_paragraph(f"[{idx}] {str(r)}")

    @staticmethod
    def _build_from_markdown(doc: Document, markdown_text: str, default_title: str):
        """Parse structured markdown text (incl. tables) into styled Word elements."""
        lines = markdown_text.splitlines()
        has_title = False
        i = 0

        def _is_table_row(line: str) -> bool:
            return bool(line.strip().startswith("|")) and line.count("|") >= 2

        while i < len(lines):
            line_str = lines[i].strip()
            if not line_str:
                i += 1
                continue

            # ── Markdown table block ──────────────────────────────────────
            if _is_table_row(line_str):
                block = []
                while i < len(lines) and _is_table_row(lines[i].strip()) and "```" not in lines[i]:
                    block.append(lines[i].strip())
                    i += 1
                if block:
                    rows = []
                    for row_line in block:
                        cells = [c.strip() for c in row_line.strip().strip("|").split("|")]
                        # skip the |---| :---| separator row
                        if all(re.match(r"^:?-+:?$", c or "-") for c in cells):
                            continue
                        rows.append(cells)
                    if rows:
                        if len(rows) == 1:
                            # single-row table: treat as a normal inline table
                            Office._add_styled_table(doc, rows)
                        else:
                            Office._add_styled_table(doc, rows)
                continue

            # Heading 1 (# Heading)
            if line_str.startswith("# "):
                doc.add_heading(line_str[2:].strip(), level=0 if not has_title else 1)
                has_title = True
            # Heading 2 (## Heading)
            elif line_str.startswith("## "):
                doc.add_heading(line_str[3:].strip(), level=1)
            # Heading 3 (### Heading)
            elif line_str.startswith("### "):
                doc.add_heading(line_str[4:].strip(), level=2)
            # Bullet list (* item or - item)
            elif line_str.startswith(("* ", "- ", "• ")):
                text = line_str[2:].strip()
                p = doc.add_paragraph(style='List Bullet')
                Office._add_formatted_runs(p, text)
            # Numbered list (1. item)
            elif re.match(r"^\d+\.\s+", line_str):
                text = re.sub(r"^\d+\.\s+", "", line_str).strip()
                p = doc.add_paragraph(style='List Number')
                Office._add_formatted_runs(p, text)
            # Regular paragraph
            else:
                p = doc.add_paragraph()
                Office._add_formatted_runs(p, line_str)
            i += 1

    @staticmethod
    def _add_formatted_runs(paragraph, text: str):
        """Parse **bold** and *italic* markdown tags and append formatted runs to a paragraph."""
        parts = re.split(r'(\*\*.*?\*\*|\*.*?\*)', text)
        for part in parts:
            if not part:
                continue
            if part.startswith('**') and part.endswith('**') and len(part) >= 4:
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            elif part.startswith('*') and part.endswith('*') and len(part) >= 2:
                run = paragraph.add_run(part[1:-1])
                run.italic = True
            else:
                paragraph.add_run(part)

    @staticmethod
    async def open_document(path: str) -> Dict[str, Any]:
        """Open a document (attempt to launch with default application)."""
        try:
            if os.path.exists(path):
                os.startfile(path) if os.name == 'nt' else None
                return create_office_result("open_document", "success", f"Opened document: {path}", path=path)
            return create_office_result("open_document", "error", f"Document not found: {path}")
        except Exception as e:
            return create_office_result("open_document", "error", f"Failed to open document: {str(e)}")

    @staticmethod
    async def verify_document(path: str) -> Dict[str, Any]:
        """Verify a document exists, has content, and contains clean synthesized analysis."""
        try:
            if not os.path.exists(path):
                return create_office_result("verify_document", "error", f"Document not found: {path}", verified=False)

            doc = Document(path)
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            full_text = "\n".join(paragraphs).lower()
            word_count = sum(len(p.split()) for p in paragraphs)

            noise_markers = [
                "cookie policy", "terms of use", "privacy policy", "sign in to continue",
                "create an account", "all rights reserved", "navigation menu", "skip to content",
                "[edit]", "advertisement"
            ]
            noise_detected = [m for m in noise_markers if m in full_text]

            has_summary = any("summary" in p.lower() for p in paragraphs[:5])
            has_findings = any("finding" in p.lower() or "analysis" in p.lower() for p in paragraphs)
            has_references = any("reference" in p.lower() or "source" in p.lower() for p in paragraphs)

            is_valid = len(paragraphs) >= 3 and word_count >= 50

            return create_office_result("verify_document", "success" if is_valid else "error",
                f"Document verified: {len(paragraphs)} paragraphs, {word_count} words.",
                verified=is_valid, path=path, paragraph_count=len(paragraphs), word_count=word_count,
                has_summary=has_summary, has_findings=has_findings, has_references=has_references,
                noise_detected=noise_detected)
        except Exception as e:
            return create_office_result("verify_document", "error", f"Failed to verify document: {str(e)}", verified=False)

    @staticmethod
    async def create_pptx(
        title: str = "Presentation",
        slides: List[Dict] = None,
        save_path: str = ""
    ) -> Dict[str, Any]:
        """Create a modern executive PowerPoint presentation with python-pptx.

        Each slide dict supports:
          - title:    slide title text
          - bullets:  list of bullet text lines
          - table:    list-of-lists table data
          - chart:    chart spec ({type, title, labels, values, bins})
          - notes:    speaker notes for the slide
          - image_path: path to relevant slide image
        """
        try:
            from pptx import Presentation
            from pptx.util import Inches, Pt
            from pptx.dml.color import RGBColor as PptRGBColor
            from pptx.enum.text import PP_ALIGN
            from pptx.enum.shapes import MSO_SHAPE

            if not save_path:
                safe = re.sub(r'[^\w\- ]', '_', title)
                save_path = os.path.join(WORK_DIR, "documents", f"{safe.replace(' ', '_')}.pptx")
            if not save_path.endswith('.pptx'):
                save_path = save_path + '.pptx'
            os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)

            prs = Presentation()
            prs.slide_width = Inches(13.333)
            prs.slide_height = Inches(7.5)

            # ── Executive Cover Slide ─────────────────────────────────────────
            cover_layout = prs.slide_layouts[6]  # Blank layout for custom styling
            cover = prs.slides.add_slide(cover_layout)

            # Dark Background Header Banner
            bg_shape = cover.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5))
            bg_shape.fill.solid()
            bg_shape.fill.fore_color.rgb = PptRGBColor(0x0F, 0x17, 0x2A)  # Slate 900
            bg_shape.line.fill.background()

            # Cyan Left Accent Stripe
            accent_stripe = cover.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(1.5), Inches(0.15), Inches(4.5))
            accent_stripe.fill.solid()
            accent_stripe.fill.fore_color.rgb = PptRGBColor(0x02, 0x84, 0xC7)  # Sky 600
            accent_stripe.line.fill.background()

            # Main Title & Subtitle Box
            title_box = cover.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(11.0), Inches(3.8))
            tf = title_box.text_frame
            tf.word_wrap = True

            p1 = tf.paragraphs[0]
            clean_title = re.sub(r'^(?:Presentation:?\s*|Deck:?\s*)', '', str(title), flags=re.I).strip()
            p1.text = clean_title.title() or "Executive Presentation"
            p1.font.size = Pt(38)
            p1.font.bold = True
            p1.font.color.rgb = PptRGBColor(0xFF, 0xFF, 0xFF)
            p1.space_after = Pt(14)

            p2 = tf.add_paragraph()
            p2.text = "RESEARCH SYNTHESIS & STRATEGIC INSIGHTS"
            p2.font.size = Pt(14)
            p2.font.bold = True
            p2.font.color.rgb = PptRGBColor(0x38, 0xBD, 0xF8)  # Cyan 400
            p2.space_after = Pt(28)

            p3 = tf.add_paragraph()
            p3.text = f"Prepared by J.A.R.V.I.S. Agentic Intelligence System  ·  {datetime.now().strftime('%B %Y')}"
            p3.font.size = Pt(12)
            p3.font.color.rgb = PptRGBColor(0x94, 0xA3, 0xB8)  # Slate 400

            # ── Content Slides ────────────────────────────────────────────────
            for idx, slide_data in enumerate(slides or [], 1):
                Office._build_pptx_slide(prs, slide_data, idx, len(slides or []))

            prs.save(save_path)
            return create_office_result("create_pptx", "success", f"Presentation created: {save_path}", path=save_path, document_type="pptx", slide_count=len(slides or []))
        except Exception as e:
            return create_office_result("create_pptx", "error", f"Failed to create PowerPoint: {str(e)}")

    @staticmethod
    def _build_pptx_slide(prs, slide_data: Dict, slide_num: int = 1, total_slides: int = 1):
        from pptx.util import Inches, Pt
        from pptx.dml.color import RGBColor as PptRGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.enum.text import PP_ALIGN

        title_text = str(slide_data.get("title", "") or "").strip()
        bullets = slide_data.get("bullets") or []
        table_data = slide_data.get("table")
        chart_spec = slide_data.get("chart")
        image_path = slide_data.get("image_path")
        notes = slide_data.get("notes")

        # Blank layout for total control over aesthetics
        layout = prs.slide_layouts[6]
        slide = prs.slides.add_slide(layout)

        # Top Header Accent Bar
        top_bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(1.1))
        top_bar.fill.solid()
        top_bar.fill.fore_color.rgb = PptRGBColor(0x0F, 0x17, 0x2A)  # Slate 900
        top_bar.line.fill.background()

        # Cyan Accent Stripe beneath top bar
        accent_line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, Inches(1.1), Inches(13.333), Inches(0.06))
        accent_line.fill.solid()
        accent_line.fill.fore_color.rgb = PptRGBColor(0x02, 0x84, 0xC7)  # Sky 600
        accent_line.line.fill.background()

        # Slide Title in Header
        if title_text:
            tbox = slide.shapes.add_textbox(Inches(0.6), Inches(0.18), Inches(10.5), Inches(0.8))
            ttf = tbox.text_frame
            ttf.word_wrap = True
            tp = ttf.paragraphs[0]
            tp.text = title_text.title()
            tp.font.size = Pt(22)
            tp.font.bold = True
            tp.font.color.rgb = PptRGBColor(0xFF, 0xFF, 0xFF)

        # Slide Counter Badge in Top Right Header
        counter_box = slide.shapes.add_textbox(Inches(11.2), Inches(0.25), Inches(1.5), Inches(0.6))
        ctf = counter_box.text_frame
        cp = ctf.paragraphs[0]
        cp.alignment = PP_ALIGN.RIGHT
        cp.text = f"{slide_num} / {total_slides}"
        cp.font.size = Pt(12)
        cp.font.bold = True
        cp.font.color.rgb = PptRGBColor(0x38, 0xBD, 0xF8)

        if image_path and not os.path.isfile(str(image_path)):
            image_path = None
        has_right = bool(chart_spec or image_path or (table_data and isinstance(table_data, list)))
        left_w = Inches(6.0) if has_right else Inches(12.1)

        # ── Left Side: Formatted Content / Bullet Points ─────────────────────
        if bullets:
            box = slide.shapes.add_textbox(Inches(0.6), Inches(1.35), left_w, Inches(5.6))
            tf = box.text_frame
            tf.word_wrap = True
            
            for idx, b in enumerate(bullets):
                p = tf.paragraphs[0] if idx == 0 else tf.add_paragraph()
                p.space_after = Pt(10)
                p.space_before = Pt(4)
                
                b_text = str(b).strip()
                # Parse bold prefix if present (e.g. "**Header:** text" or "Header: text")
                colon_match = re.match(r'^(?:\*\*)?([A-Za-z0-9\s\-_]+?)(?:\*\*)?:\s*(.*)$', b_text)
                if colon_match:
                    prefix_str = colon_match.group(1).strip() + ": "
                    body_str = colon_match.group(2).strip()

                    r1 = p.add_run()
                    r1.text = "• " + prefix_str
                    r1.font.bold = True
                    r1.font.size = Pt(15)
                    r1.font.color.rgb = PptRGBColor(0x02, 0x84, 0xC7)  # Sky 600

                    r2 = p.add_run()
                    r2.text = body_str
                    r2.font.size = Pt(14)
                    r2.font.color.rgb = PptRGBColor(0x33, 0x41, 0x55)  # Slate 700
                else:
                    r = p.add_run()
                    r.text = "• " + b_text
                    r.font.size = Pt(14)
                    r.font.color.rgb = PptRGBColor(0x33, 0x41, 0x55)

        # ── Right Side: Table ─────────────────────────────────────────────────
        if table_data and isinstance(table_data, list) and table_data:
            n_rows = len(table_data)
            n_cols = max(len(r) for r in table_data)
            tx = Inches(6.9) if bullets else Inches(0.6)
            tbl_w = Inches(5.8) if bullets else Inches(12.1)
            gfx = slide.shapes.add_table(n_rows, n_cols, tx, Inches(1.5), tbl_w, Inches(0.45 * n_rows + 0.3))
            tbl = gfx.table
            for i, row in enumerate(table_data):
                for j in range(n_cols):
                    cell = tbl.cell(i, j)
                    cell.text = str(row[j]) if j < len(row) else ""
                    if i == 0:
                        cell.fill.solid()
                        cell.fill.fore_color.rgb = PptRGBColor(0x0F, 0x17, 0x2A)
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                run.font.bold = True
                                run.font.size = Pt(13)
                                run.font.color.rgb = PptRGBColor(0xFF, 0xFF, 0xFF)
                    else:
                        cell.fill.solid()
                        bg_c = PptRGBColor(0xF8, 0xFA, 0xFC) if i % 2 == 1 else PptRGBColor(0xFF, 0xFF, 0xFF)
                        cell.fill.fore_color.rgb = bg_c
                        for para in cell.text_frame.paragraphs:
                            for run in para.runs:
                                run.font.size = Pt(12)
                                run.font.color.rgb = PptRGBColor(0x33, 0x41, 0x55)

        # ── Right Side: Chart ─────────────────────────────────────────────────
        if chart_spec and isinstance(chart_spec, dict):
            from backend.tools.charts import render_chart
            try:
                png, cw, chh = render_chart(chart_spec)
                w = min(float(cw), 5.8)
                slide.shapes.add_picture(io.BytesIO(png), Inches(6.8), Inches(1.5), width=Inches(w))
            except Exception as ce:
                print(f"[office] PPT chart embed skipped ({ce})")

        # ── Right Side: Relevant Image ───────────────────────────────────────
        elif image_path and not (table_data and isinstance(table_data, list) and table_data):
            try:
                slide.shapes.add_picture(str(image_path), Inches(6.8), Inches(1.4), width=Inches(5.8))
            except Exception as ie:
                print(f"[office] PPT image embed skipped ({ie})")

        if notes:
            try:
                slide.notes_slide.notes_text_frame.text = str(notes)
            except Exception:
                pass