from app.services.cinema_format import (
    FORMAT_BY_KEY,
    REVIEWER_SYSTEM,
    WRITER_SYSTEM,
    build_style_packet,
    format_packet,
    parse_review_gate,
    research_query_groups,
)
from app.services.research import _social_platform_for_url, _social_queries


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



def test_every_research_section_has_a_semantic_contract():
    for section in format_packet():
        if not section["research"]:
            continue
        assert section["mission"]
        assert section["include"]
        assert section["exclude"]
        assert section["evidence"]
        assert section["preferred_sources"]


def test_celebrity_and_viral_sections_enable_social_discovery():
    by_key = {item["key"]: item for item in format_packet()}
    assert set(by_key["celebrities"]["social_sources"]) == {"x", "tiktok", "reddit"}
    assert set(by_key["viral_images"]["social_sources"]) == {"x", "tiktok", "reddit"}
    assert "Reddit is discovery/reaction" in by_key["celebrities"]["social_policy"]


def test_social_queries_are_section_and_platform_specific():
    rows = _social_queries("2026-09-21", "2026-09-28")
    assert any(section == "celebrities" and platform == "x" and "site:x.com" in query for section, platform, query in rows)
    assert any(section == "celebrities" and platform == "tiktok" and "site:tiktok.com" in query for section, platform, query in rows)
    assert any(section == "celebrities" and platform == "reddit" and "site:reddit.com" in query for section, platform, query in rows)
    assert not any(section == "box_office" and platform == "reddit" for section, platform, _ in rows)


def test_social_platform_detection_does_not_confuse_news_domains():
    assert _social_platform_for_url("https://x.com/example/status/1") == "x"
    assert _social_platform_for_url("https://www.tiktok.com/@example/video/1") == "tiktok"
    assert _social_platform_for_url("https://www.reddit.com/r/movies/comments/abc") == "reddit"
    assert _social_platform_for_url("https://www.netflix.com/title/123") == ""
