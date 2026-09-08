"""
Test: Research Pipeline — Clean article extraction, per-source analysis,
cross-source comparison, DOCX synthesis, and document verification.
"""
import asyncio
import os
import sys
import re
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "PASS"
FAIL = "FAIL"
results = []


def check(label: str, condition: bool, note: str = ""):
    status = PASS if condition else FAIL
    results.append((label, status, note))
    icon = "[OK]" if condition else "[FAIL]"
    print(f"  {icon} {label}{(' — ' + note) if note else ''}")


# ── 1. ResearchSynthesizer: Source Analysis ───────────────────────────────────
print("\n[1] ResearchSynthesizer — Source Analysis (rule-based fallback)")
try:
    from backend.agent.research_synthesizer import ResearchSynthesizer

    synth = ResearchSynthesizer(api_key="")  # No API key → deterministic fallback

    sample_content = """
    Teachers' Day is celebrated on September 5 in India, honoring the birthday of Dr. Sarvepalli Radhakrishnan.
    Born on September 5, 1888, he was the first Vice President and second President of India.
    He was a philosopher, statesman, and Bharat Ratna recipient. The day commemorates his contribution to education.
    National teachers are felicitated with awards on this occasion. Students celebrate by performing plays and songs.
    The celebration reflects respect and gratitude for educators across the country.
    """

    analysis = synth.analyze_source(
        title="Teachers' Day — Wikipedia",
        url="https://en.wikipedia.org/wiki/Teachers%27_Day",
        content=sample_content
    )

    check("analyze_source returns dict", isinstance(analysis, dict))
    check("Has title", analysis.get("title") == "Teachers' Day — Wikipedia")
    check("Has url", "wikipedia" in analysis.get("url", ""))
    check("Has key_facts list", isinstance(analysis.get("key_facts"), list))
    check("Has main_points list", isinstance(analysis.get("main_points"), list))
    check("Has summary string", isinstance(analysis.get("summary"), str) and len(analysis.get("summary", "")) > 10)
    check("Has dates_people list", isinstance(analysis.get("important_dates_people_events"), list))
except Exception as ex:
    check("ResearchSynthesizer import and analyze_source", False, str(ex))


# ── 2. ResearchSynthesizer: Cross-Source Comparison ──────────────────────────
print("\n[2] ResearchSynthesizer — Cross-Source Comparison")
try:
    from backend.agent.research_synthesizer import ResearchSynthesizer

    synth2 = ResearchSynthesizer(api_key="")

    src_analyses = [
        {
            "title": "Source A", "url": "http://a.com",
            "key_facts": ["Fact about Teachers Day.", "Celebrated on September 5.", "Honors Dr. Radhakrishnan."],
            "important_dates_people_events": ["September 5 — Birthday of Dr. Radhakrishnan"],
            "unique_information": ["Schools celebrate with special programs."],
            "summary": "Source A covers the history and celebration of Teachers Day in India."
        },
        {
            "title": "Source B", "url": "http://b.com",
            "key_facts": ["Radhakrishnan was India's second President.", "Day recognized since 1962."],
            "important_dates_people_events": ["1888 — Birth of Sarvepalli Radhakrishnan"],
            "unique_information": ["National award given to best teachers."],
            "summary": "Source B focuses on the life of Radhakrishnan and national recognition."
        },
        {
            "title": "Source C", "url": "http://c.com",
            "key_facts": ["Teachers Day encourages respect for educators.", "Global significance noted."],
            "important_dates_people_events": ["UNESCO World Teachers Day: October 5"],
            "unique_information": ["Celebrations differ across countries."],
            "summary": "Source C provides global context for Teachers Day observances."
        }
    ]

    comparison = synth2.compare_sources("Teachers' Day", src_analyses)
    check("compare_sources returns dict", isinstance(comparison, dict))
    check("Has consensus_facts", isinstance(comparison.get("consensus_facts"), list))
    check("Has unique_perspectives", isinstance(comparison.get("unique_perspectives"), list))
    check("Has overall_synthesis", isinstance(comparison.get("overall_synthesis"), str) and len(comparison.get("overall_synthesis", "")) > 20)
except Exception as ex:
    check("compare_sources", False, str(ex))


# ── 3. ResearchSynthesizer: Report Synthesis ──────────────────────────────────
print("\n[3] ResearchSynthesizer — Report Synthesis")
try:
    from backend.agent.research_synthesizer import ResearchSynthesizer

    synth3 = ResearchSynthesizer(api_key="")

    raw_sources = [
        {"title": "Source A", "url": "http://a.com", "text": "Content A about Teachers Day."},
        {"title": "Source B", "url": "http://b.com", "text": "Content B about Radhakrishnan."},
        {"title": "Source C", "url": "http://c.com", "text": "Content C about global observance."},
    ]
    src_analyses3 = [
        {"title": "Source A", "url": "http://a.com", "key_facts": ["Teachers Day is September 5."], "important_dates_people_events": [], "summary": "Overview of Teachers Day history."},
        {"title": "Source B", "url": "http://b.com", "key_facts": ["Radhakrishnan born 1888."], "important_dates_people_events": [], "summary": "Biography of Dr. Radhakrishnan."},
        {"title": "Source C", "url": "http://c.com", "key_facts": ["Global Teacher Day October 5."], "important_dates_people_events": [], "summary": "International context."},
    ]
    comparison3 = {
        "consensus_facts": ["Teachers Day honors educators.", "September 5 is Indian Teachers Day."],
        "unique_perspectives": ["Source A: history", "Source B: biography", "Source C: global"],
        "overall_synthesis": "All sources agree Teachers Day is a significant observance."
    }

    report = synth3.synthesize_research_report(
        topic="Teachers' Day",
        sources=raw_sources,
        source_analyses=src_analyses3,
        comparison=comparison3
    )

    check("synthesize_research_report returns dict", isinstance(report, dict))
    check("Has title", isinstance(report.get("title"), str) and len(report.get("title", "")) > 5)
    check("Has executive_summary", isinstance(report.get("executive_summary"), str) and len(report.get("executive_summary", "")) > 20)
    check("Has introduction", isinstance(report.get("introduction"), str) and len(report.get("introduction", "")) > 20)
    check("Has key_findings list", isinstance(report.get("key_findings"), list) and len(report.get("key_findings", [])) > 0)
    check("Has source_insights list", isinstance(report.get("source_insights"), list) and len(report.get("source_insights", [])) > 0)
    check("Has cross_source_analysis", isinstance(report.get("cross_source_analysis"), str) and len(report.get("cross_source_analysis", "")) > 10)
    check("Has conclusion", isinstance(report.get("conclusion"), str) and len(report.get("conclusion", "")) > 10)
    check("Has references list", isinstance(report.get("references"), list) and len(report.get("references", [])) > 0)

    # Ensure we have 3 references (one per source)
    check("References count matches sources", len(report.get("references", [])) == 3)
except Exception as ex:
    check("synthesize_research_report", False, str(ex))


# ── 4. Office.create_docx with Structured Report ──────────────────────────────
print("\n[4] Office.create_docx — Structured Report Mode")
try:
    import asyncio
    from backend.tools.office import Office

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    test_docx_path = os.path.join(desktop, "JARVIS_Test_Research_Report.docx")

    structured_report = {
        "title": "Comprehensive Research Report: Teachers' Day",
        "subtitle": "Synthesized Intelligence Report | J.A.R.V.I.S. Research Division",
        "executive_summary": "Teachers' Day is celebrated on September 5 in India, honoring Dr. Sarvepalli Radhakrishnan.\n\nThe day has been observed since 1962 and is marked by national recognition of outstanding teachers.",
        "introduction": "Teachers' Day commemorates the birth anniversary of Dr. Sarvepalli Radhakrishnan.\n\nRadhakrishnan was a philosopher, statesman, and the second President of India.",
        "key_findings": [
            "Teachers' Day is celebrated on September 5 in India.",
            "The day honors the birthday of Dr. Sarvepalli Radhakrishnan, born in 1888.",
            "India has observed Teachers Day since 1962.",
            "National awards are given to exemplary teachers on this occasion.",
            "Schools organize cultural events and recognition ceremonies."
        ],
        "source_insights": [
            {
                "source_title": "Wikipedia — Teachers Day",
                "source_url": "https://en.wikipedia.org/wiki/Teachers_Day",
                "key_takeaway": "Provides historical background and origin of the celebration."
            },
            {
                "source_title": "NDTV — Teachers Day",
                "source_url": "https://www.ndtv.com/education/teachers-day",
                "key_takeaway": "Covers national recognition programs and school-level celebrations."
            },
            {
                "source_title": "The Hindu — Teachers Day",
                "source_url": "https://www.thehindu.com/education/teachers-day",
                "key_takeaway": "Discusses Radhakrishnan's legacy and modern observance of the day."
            }
        ],
        "cross_source_analysis": "All three sources corroborate the central fact that Teachers' Day on September 5 honors Dr. Radhakrishnan's birth anniversary. Wikipedia provides the most comprehensive historical account, while NDTV focuses on contemporary celebrations and The Hindu offers philosophical context regarding Radhakrishnan's legacy.",
        "conclusion": "Teachers' Day is a well-documented, nationally significant occasion in India with strong consensus across multiple independent sources confirming its historical roots and modern observance.",
        "references": [
            {"index": 1, "title": "Wikipedia — Teachers Day", "url": "https://en.wikipedia.org/wiki/Teachers_Day", "type": "Verified Web Source"},
            {"index": 2, "title": "NDTV — Teachers Day", "url": "https://www.ndtv.com/education/teachers-day", "type": "Verified Web Source"},
            {"index": 3, "title": "The Hindu — Teachers Day", "url": "https://www.thehindu.com/education/teachers-day", "type": "Verified Web Source"}
        ]
    }

    result = asyncio.run(Office.create_docx(
        structured_report=structured_report,
        save_path=test_docx_path
    ))

    check("create_docx returns success", result.get("status") == "success", result.get("message", ""))
    check("DOCX file exists on disk", os.path.isfile(test_docx_path))
except Exception as ex:
    check("Office.create_docx structured report", False, str(ex))


# ── 5. Office.verify_document ──────────────────────────────────────────────────
print("\n[5] Office.verify_document — Structural Integrity")
try:
    import asyncio
    from backend.tools.office import Office

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    test_docx_path = os.path.join(desktop, "JARVIS_Test_Research_Report.docx")

    if os.path.isfile(test_docx_path):
        verify_result = asyncio.run(Office.verify_document(test_docx_path))
        check("verify_document returns success", verify_result.get("status") == "success", verify_result.get("message", ""))
        check("Adequate paragraph count (>=3)", verify_result.get("paragraph_count", 0) >= 3, f"{verify_result.get('paragraph_count', 0)} paragraphs")
        check("Adequate word count (>=50)", verify_result.get("word_count", 0) >= 50, f"{verify_result.get('word_count', 0)} words")
        check("No noise detected", len(verify_result.get("noise_detected", [])) == 0, f"Noise: {verify_result.get('noise_detected', [])}")
        check("Has summary section", verify_result.get("has_summary", False))
        check("Has references section", verify_result.get("has_references", False))
    else:
        check("verify_document (DOCX exists for verification)", False, "DOCX not found — create_docx may have failed")
except Exception as ex:
    check("Office.verify_document", False, str(ex))


# ── 6. Browser._clean_extracted_text — Noise Filtering ────────────────────────
print("\n[6] Browser._clean_extracted_text — Noise Pattern Filtering")
try:
    from backend.tools.browser import Browser

    noisy_text = """
Home
Menu
Navigation
Sign In
Log In
Teachers Day in India is celebrated on September 5 every year.
Cookie Policy
Privacy Policy
Terms of Use
All Rights Reserved
Dr. Sarvepalli Radhakrishnan was born on September 5, 1888.
Share
Subscribe to Newsletter
He became the second President of India and was a renowned philosopher.
Advertisement
Follow us on
The national award for teachers was instituted to honor outstanding educators.
Teachers' Day has been observed in India since 1962.
Home
Cookie Policy
"""

    cleaned = Browser._clean_extracted_text(noisy_text)

    check("Cleaned text is not empty", len(cleaned.strip()) > 0)
    check("'Home' (single-word nav) removed", "Home\n" not in cleaned and cleaned.strip() != "Home")
    check("Cookie Policy removed", "Cookie Policy" not in cleaned)
    check("Privacy Policy removed", "Privacy Policy" not in cleaned)
    check("Terms of Use removed", "Terms of Use" not in cleaned)
    check("Substantive content preserved — Dr. Radhakrishnan", "Radhakrishnan" in cleaned)
    check("September 5 fact preserved", "September 5" in cleaned)
    check("National award fact preserved", "national award" in cleaned.lower())
    # Deduplication: "Home" should appear at most once (actually removed as noise)
    occurrences_home = cleaned.lower().count("cookie policy")
    check("Duplicate 'Cookie Policy' not repeated", occurrences_home == 0)
except Exception as ex:
    check("Browser._clean_extracted_text", False, str(ex))


# ── 7. State: source_analyses / cross_source_analysis / synthesized_report ────
print("\n[7] TaskState — Research Pipeline Fields Present")
try:
    from backend.agent.state import TaskState

    state = TaskState()
    check("source_analyses field exists and is list", isinstance(state.source_analyses, list))
    check("cross_source_analysis field exists and is dict", isinstance(state.cross_source_analysis, dict))
    check("synthesized_report field exists and is dict", isinstance(state.synthesized_report, dict))
    check("extracted_sources field exists and is list", isinstance(state.extracted_sources, list))
    check("search_results field exists and is list", isinstance(state.search_results, list))
except Exception as ex:
    check("TaskState research fields", False, str(ex))


# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for _, s, _ in results if s == PASS)
failed = total - passed
print(f"  Results: {passed}/{total} passed  ({failed} failed)")
if failed:
    print("\n  Failed tests:")
    for label, status, note in results:
        if status == FAIL:
            print(f"    [FAIL] {label}{(' — ' + note) if note else ''}")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
