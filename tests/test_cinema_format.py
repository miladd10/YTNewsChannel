from app.services.cinema_format import (
    FORMAT_BY_KEY,
    REVIEWER_SYSTEM,
    WRITER_SYSTEM,
    build_style_packet,
    format_packet,
    parse_review_gate,
    research_query_groups,
)


def test_cinema_format_contains_recurring_weekly_sections():
    keys = [item["key"] for item in format_packet()]
    assert keys == [
        "intro", "trend", "industry", "upcoming_films", "tv_series",
        "celebrities", "ai_tech", "viral_images", "box_office",
        "channel_polls", "now_available", "toxic_news", "outro",
    ]


def test_research_queries_cover_researchable_sections_only():
    groups = research_query_groups()
    keys = {key for key, _ in groups}
    assert "trend" in keys
    assert "box_office" in keys
    assert "viral_images" in keys
    assert "now_available" in keys
    assert "toxic_news" in keys
    assert "intro" not in keys
    assert "outro" not in keys
    assert "channel_polls" not in keys


def test_style_packet_explicitly_separates_style_from_facts():
    packet = build_style_packet([
        {
            "name": "Filmbaz Ep 1",
            "content": "Old episode fact: Movie X made $500M. This is only a style example.",
            "enabled": 1,
        }
    ])
    assert "STYLE REFERENCES ONLY" in packet
    assert "Never treat facts" in packet
    assert "Filmbaz Ep 1" in packet


def test_writer_and_reviewer_prompts_protect_current_week_factual_authority():
    assert "ONLY factual authority" in WRITER_SYSTEM
    assert "Never import a fact" in WRITER_SYSTEM
    assert "style corpus is never factual authority" in REVIEWER_SYSTEM.lower()


def test_review_gate_requires_all_audits_to_pass():
    review = """# Review Summary
Good overall.

# Format Audit
- Status: PASS
- Notes: fine

# Style Audit
- Status: PASS
- Notes: fine

# Factual / Source Audit
- Status: NEEDS_WORK
- Notes: one unsupported number

# Storytelling Audit
- Status: PASS
- Notes: fine

# Issues
## ISSUE 1 — Unsupported number
- Severity: major
- Section: Trends
- Problem: unsupported
- Fix: remove it

# Review Gate
- Blocking Issues: 0
- Major Issues: 1
- Minor Issues: 0
- Recommendation: PASS
"""
    gate = parse_review_gate(review)
    assert gate["factual_status"] == "needs_work"
    assert gate["major_count"] == 1
    assert gate["gate_status"] == "revision_required"


def test_review_gate_can_pass_clean_review():
    review = """# Review Summary
Clean.

# Format Audit
- Status: PASS
- Notes: fine

# Style Audit
- Status: PASS
- Notes: fine

# Factual / Source Audit
- Status: PASS
- Notes: fine

# Storytelling Audit
- Status: PASS
- Notes: fine

# Issues
None.

# Review Gate
- Blocking Issues: 0
- Major Issues: 0
- Minor Issues: 0
- Recommendation: PASS
"""
    assert parse_review_gate(review)["gate_status"] == "pass"
