import asyncio
import os
import re
from typing import Any, Dict, List, Optional
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from system_ops import WORK_DIR


class Office:
    """Word/DOCX generation tools with support for rich structured research reports."""

    @staticmethod
    async def create_docx(
        content: str = "",
        title: str = "Document",
        headings: List[str] = None,
        lists: List[str] = None,
        tables: List[List] = None,
        save_path: str = "",
        structured_report: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Create a beautifully formatted Microsoft Word .docx file."""
        try:
            # Determine save path
            if not save_path:
                filename = f"{title.replace(' ', '_')}_{os.path.basename(os.getcwd())}.docx"
                save_path = os.path.join(WORK_DIR, filename)
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
                            rows = len(table_data)
                            cols = max(len(row) for row in table_data) if table_data else 0
                            table = doc.add_table(rows=rows, cols=cols)
                            table.style = 'Table Grid'
                            for i, row_data in enumerate(table_data):
                                for j, cell_text in enumerate(row_data):
                                    if j < cols:
                                        table.rows[i].cells[j].text = str(cell_text)

            doc.save(save_path)
            return {"status": "success", "message": f"Word document created: {save_path}", "path": save_path}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create Word document: {str(e)}"}

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
        """Parse structured markdown text and convert into styled Word document elements."""
        lines = markdown_text.splitlines()
        has_title = False

        for line in lines:
            line_str = line.strip()
            if not line_str:
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
                return {"status": "success", "message": f"Opened document: {path}"}
            return {"status": "error", "message": f"Document not found: {path}"}
        except Exception as e:
            return {"status": "error", "message": f"Failed to open document: {str(e)}"}

    @staticmethod
    async def verify_document(path: str) -> Dict[str, Any]:
        """Verify a document exists, has content, and contains clean synthesized analysis."""
        try:
            if not os.path.exists(path):
                return {"status": "error", "message": f"Document not found: {path}", "verified": False}

            doc = Document(path)
            paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            full_text = "\n".join(paragraphs).lower()
            word_count = sum(len(p.split()) for p in paragraphs)

            # Check for obvious web navigation garbage
            noise_markers = [
                "cookie policy", "terms of use", "privacy policy", "sign in to continue",
                "create an account", "all rights reserved", "navigation menu", "skip to content",
                "[edit]", "advertisement"
            ]
            noise_detected = [m for m in noise_markers if m in full_text]

            # Check for synthesis structure
            has_summary = any("summary" in p.lower() for p in paragraphs[:5])
            has_findings = any("finding" in p.lower() or "analysis" in p.lower() for p in paragraphs)
            has_references = any("reference" in p.lower() or "source" in p.lower() for p in paragraphs)

            is_valid = len(paragraphs) >= 3 and word_count >= 50

            return {
                "status": "success" if is_valid else "error",
                "verified": is_valid,
                "message": f"Document verified: {len(paragraphs)} paragraphs, {word_count} words.",
                "path": path,
                "paragraph_count": len(paragraphs),
                "word_count": word_count,
                "has_summary": has_summary,
                "has_findings": has_findings,
                "has_references": has_references,
                "noise_detected": noise_detected
            }
        except Exception as e:
            return {"status": "error", "message": f"Failed to verify document: {str(e)}", "verified": False}