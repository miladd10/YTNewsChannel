from app.services.cinema_format import (
    FORMAT_BY_KEY,
    REVIEWER_SYSTEM,
    WRITER_SYSTEM,
    build_style_packet,
    format_packet,
    parse_review_gate,
    research_query_groups,
)
from app.services.research import (
    _apply_story_quality_gates,
    _social_platform_for_url,
    _social_queries,
    cluster_articles,
    google_news_rss_url,
    source_temporal_role,
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

# Freshness Audit
- Status: PASS
- Notes: current hook checked

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

# Freshness Audit
- Status: PASS
- Notes: current hook checked

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



def test_source_temporal_role_uses_project_window_not_current_clock():
    assert source_temporal_role("2026-09-21T10:00:00+00:00", "2026-09-21", "2026-09-28") == "current"
    assert source_temporal_role("2026-09-27T23:59:59+00:00", "2026-09-21", "2026-09-28") == "current"
    assert source_temporal_role("2026-09-20T23:59:59+00:00", "2026-09-21", "2026-09-28") == "background"
    assert source_temporal_role("2026-09-28T00:00:00+00:00", "2026-09-21", "2026-09-28") == "out_of_window"
    assert source_temporal_role("", "2026-09-21", "2026-09-28") == "undated"


def test_cluster_marks_old_news_stale_even_if_subject_is_relevant():
    articles = [
        {
            "id": "a1",
            "title": "Old movie casting announcement",
            "url": "https://example.com/old",
            "source": "Example News",
            "published_at": "2026-09-01T12:00:00+00:00",
            "category": "upcoming_films",
            "snippet": "Casting was announced earlier this month.",
            "query_key": "upcoming film casting",
            "raw": {},
        }
    ]
    stories = cluster_articles(articles, "2026-09-21", "2026-09-28")
    assert stories[0]["freshness"] == "stale"
    assert stories[0]["temporal_gate"] == "fail"
    assert stories[0]["decision"] == "skip"
    assert stories[0]["in_window_source_count"] == 0
    assert stories[0]["background_source_count"] == 1


def test_current_story_without_semantic_hook_cannot_be_auto_included():
    story = {
        "decision": "include",
        "freshness": "current",
        "news_hook": "",
        "news_hook_date": "",
        "verification_status": "reported",
        "in_window_source_count": 1,
        "background_source_count": 0,
        "undated_source_count": 0,
        "current_non_reddit_source_count": 1,
        "independent_source_count": 1,
        "reddit_only": False,
        "score": 8.5,
    }
    _apply_story_quality_gates(
        story,
        {"date_start": "2026-09-21", "date_end": "2026-09-28"},
    )
    assert story["temporal_gate"] == "warning"
    assert story["decision"] == "maybe"


def test_current_verified_hook_can_pass_selection_gate():
    story = {
        "decision": "include",
        "freshness": "current",
        "news_hook": "Studio released the first trailer this week.",
        "news_hook_date": "2026-09-25",
        "verification_status": "verified",
        "in_window_source_count": 2,
        "background_source_count": 1,
        "undated_source_count": 0,
        "current_non_reddit_source_count": 2,
        "independent_source_count": 2,
        "reddit_only": False,
        "score": 8.5,
    }
    _apply_story_quality_gates(
        story,
        {"date_start": "2026-09-21", "date_end": "2026-09-28"},
    )
    assert story["temporal_gate"] == "pass"
    assert story["verification_gate"] == "pass"
    assert story["decision"] == "include"


def test_news_hook_date_outside_window_forces_stale_skip():
    story = {
        "decision": "include",
        "freshness": "current",
        "news_hook": "A casting announcement.",
        "news_hook_date": "2026-09-10",
        "verification_status": "verified",
        "in_window_source_count": 2,
        "background_source_count": 0,
        "undated_source_count": 0,
        "current_non_reddit_source_count": 2,
        "independent_source_count": 2,
        "reddit_only": False,
        "score": 9.0,
    }
    _apply_story_quality_gates(
        story,
        {"date_start": "2026-09-21", "date_end": "2026-09-28"},
    )
    assert story["freshness"] == "stale"
    assert story["temporal_gate"] == "fail"
    assert story["decision"] == "skip"



def test_section_intelligence_schema_contains_freshness_and_verification_contracts():
    for section in format_packet():
        assert "freshness_policy" in section
        assert "verification_policy" in section
        assert section["intelligence_schema_version"] >= 1
        if section["research"]:
            assert section["freshness_policy"]["require_current_week_hook"] is True
            assert section["freshness_policy"]["background_sources_count_as_freshness"] is False
            assert "include_gate" in section["verification_policy"]


def test_search_queries_widen_front_edge_but_gate_keeps_true_window():
    url = google_news_rss_url(
        "movie trailer",
        "2026-09-21",
        "2026-09-28",
    )
    assert "after%3A2026-09-20" in url
    assert "before%3A2026-09-28" in url
    assert source_temporal_role(
        "2026-09-20T18:00:00+00:00",
        "2026-09-21",
        "2026-09-28",
    ) == "background"
