from app.services.cinema_format import (
    CONTENT_PLAN_SYSTEM,
    ENRICHMENT_REWRITE_SYSTEM,
    FORMAT_BY_KEY,
    REVIEWER_SYSTEM,
    STYLE_PROFILE_SYSTEM,
    WRITER_SYSTEM,
    NARRATION_FLUENCY_POLISH_SYSTEM,

    build_style_packet,
    format_packet,
    parse_review_gate,
    research_query_groups,
    spoken_lint,
    style_rows_for_content_type,
)
from app.services.research import (
    _apply_story_quality_gates,
    _spice_queries,
    _validated_spice_angles,
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

# Context / Spice Audit
- Status: PASS
- Notes: supported context only

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

# Context / Spice Audit
- Status: PASS
- Notes: supported context only

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
    assert _social_platform_for_url("https://www.instagram.com/p/abc") == "instagram"
    assert _social_platform_for_url("https://www.youtube.com/watch?v=abc") == "youtube"
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



def test_all_enabled_style_transcripts_contribute_to_large_reference_library():
    transcripts = [
        {
            "name": f"Filmbaz {index:02d}",
            "content": ("intro\ntrend\nindustry\nupcoming\ncelebrity\nbox office\noutro\n" * 120),
            "enabled": 1,
        }
        for index in range(40)
    ]
    packet = build_style_packet(transcripts, max_chars=20000)
    for index in range(40):
        assert f"Filmbaz {index:02d}" in packet


def test_writer_prompt_requires_short_familiarity_context_without_biography():
    assert "CASUAL-AUDIENCE FAMILIARITY RULE" in WRITER_SYSTEM
    assert "Do not turn it into a biography" in WRITER_SYSTEM
    assert "never invent an anchor" in WRITER_SYSTEM.lower()


def test_reviewer_checks_familiarity_and_generic_ai_style():
    assert "CASUAL-AUDIENCE FAMILIARITY" in REVIEWER_SYSTEM
    assert "generic AI/news-presenter phrasing" in REVIEWER_SYSTEM
    assert "full style corpus" in REVIEWER_SYSTEM



def test_story_spice_queries_cover_drama_critics_social_and_context():
    story = {
        "search_subject": "Ray Gunn",
        "canonical_title": "Netflix releases Ray Gunn trailer",
    }
    rows = _spice_queries(story, "2026-09-21", "2026-09-28")
    kinds = {kind for kind, _ in rows}
    assert kinds == {
        "web_news", "rumor_drama", "critics", "social_reddit", "social_x",
        "social_tiktok", "social_instagram", "youtube", "cool_context", "comparison",
    }
    assert any("rumor" in query and "controversy" in query for _, query in rows)
    assert any("critics review reaction" in query for _, query in rows)
    assert any("site:reddit.com" in query for _, query in rows)
    assert any("site:x.com" in query for _, query in rows)
    assert any("site:tiktok.com" in query for _, query in rows)
    assert any("site:instagram.com" in query for _, query in rows)
    assert any("site:youtube.com" in query for _, query in rows)


def test_spice_validation_rejects_hallucinated_source_urls_and_weak_claims():
    sources = [
        {
            "url": "https://example.com/report",
            "source": "Example",
        }
    ]
    angles = _validated_spice_angles([
        {
            "type": "rumor",
            "text": "A reported casting rumor exists.",
            "evidence_status": "supported",
            "safe_to_narrate": True,
            "source_urls": ["https://example.com/report"],
        },
        {
            "type": "controversy",
            "text": "Invented controversy.",
            "evidence_status": "strong",
            "safe_to_narrate": True,
            "source_urls": ["https://made-up.example/nope"],
        },
        {
            "type": "critic_reaction",
            "text": "Weak reaction.",
            "evidence_status": "weak",
            "safe_to_narrate": True,
            "source_urls": ["https://example.com/report"],
        },
    ], sources)
    assert len(angles) == 2
    rumor = next(x for x in angles if x["type"] == "rumor")
    weak = next(x for x in angles if x["type"] == "critic_reaction")
    assert rumor["safe_to_narrate"] is True
    assert weak["safe_to_narrate"] is False


def test_social_only_rumor_is_never_marked_safe():
    angles = _validated_spice_angles([
        {
            "type": "rumor",
            "text": "Fans speculate about a sequel.",
            "evidence_status": "social_only",
            "safe_to_narrate": True,
            "source_urls": ["https://reddit.com/r/movies/example"],
        }
    ], [{"url": "https://reddit.com/r/movies/example", "source": "Reddit"}])
    assert angles[0]["safe_to_narrate"] is False


def test_writer_and_reviewer_have_evidence_backed_spice_rules():
    assert "STORY SPICE RULE" in WRITER_SYSTEM
    assert "RUMORS:" in WRITER_SYSTEM
    assert "If there are no strong supported angles, do not pretend there are" in WRITER_SYSTEM
    assert "Context / Spice Audit" in REVIEWER_SYSTEM
    assert "safe_to_narrate spice angle" in REVIEWER_SYSTEM



def test_enrichment_rewrite_requires_platform_specific_social_attribution():
    assert "توی ردیت بعضی از کاربرا" in ENRICHMENT_REWRITE_SYSTEM
    assert "توی X یکی از بحث‌ها" in ENRICHMENT_REWRITE_SYSTEM
    assert 'Avoid vague "مردم توی شبکه‌های اجتماعی می‌گن"' in ENRICHMENT_REWRITE_SYSTEM
    assert "safe_to_narrate=true" in ENRICHMENT_REWRITE_SYSTEM



def test_style_packet_contains_long_flow_anchors_and_asr_warning():
    long_text = ("حالا این خبر یه نکته جالب داره و برای همین میریم سراغ جزئیات. " * 500)
    packet = build_style_packet([
        {"id": "a", "name": "Long Filmbaz Reference", "content": long_text, "enabled": 1},
        {"id": "b", "name": "Second Reference", "content": long_text[::-1], "enabled": 1},
    ], max_chars=24000)
    assert "<flow_anchors>" in packet
    assert "<distributed_samples>" in packet
    assert "do NOT imitate ASR mistakes" in packet


def test_style_profile_targets_spoken_micro_arc_not_written_news():
    assert "# Story Micro-Arc" in STYLE_PROFILE_SYSTEM
    assert "colloquial Persian" in STYLE_PROFILE_SYSTEM
    assert "formal entertainment-news article" in STYLE_PROFILE_SYSTEM
    assert "ASR/transcription mistakes" in STYLE_PROFILE_SYSTEM


def test_content_plan_extracts_supported_story_beats_before_writing():
    assert '"hook_claim_ids"' in CONTENT_PLAN_SYSTEM
    assert '"detail_claim_ids"' in CONTENT_PLAN_SYSTEM
    assert '"ending_claim_ids"' in CONTENT_PLAN_SYSTEM
    assert "claim_role=current_hook" in CONTENT_PLAN_SYSTEM


def test_writer_rejects_headline_summary_style_and_english_headings():
    assert "SPOKEN TRANSCRIPT" in WRITER_SYSTEM
    assert "STORY MICRO-ARC" in WRITER_SYSTEM
    assert "never output English headings" in WRITER_SYSTEM
    assert "A cast list by itself is not a payoff" in WRITER_SYSTEM


def test_reviewer_must_fail_overcompressed_article_like_drafts():
    assert "OVER-COMPRESSION" in REVIEWER_SYSTEM
    assert "FORMAL WRITTEN-PERSIAN DRIFT" in REVIEWER_SYSTEM
    assert "EMPTY ADJECTIVE PAYOFFS" in REVIEWER_SYSTEM
    assert "headline-summary draft should be NEEDS_WORK" in REVIEWER_SYSTEM



def test_persian_spoken_section_labels_are_available_to_writer():
    by_key = {item["key"]: item for item in format_packet()}
    assert by_key["industry"]["spoken_label_fa"] == "صنعت سینما"
    assert by_key["upcoming_films"]["spoken_label_fa"] == "فیلم‌های جدید"
    assert by_key["box_office"]["spoken_label_fa"] == "گیشه"


def _review(status_fmt: str, rec_fmt: str, issues: str = "None.") -> str:
    parts = []
    for heading in ("# Format Audit", "# Style Audit", "# Factual / Source Audit", "# Freshness Audit",
                    "# Context / Spice Audit", "# Storytelling Audit"):
        parts.append(f"{heading}\n{status_fmt}\n- Notes: fine")
    parts.append(f"# Issues\n{issues}")
    parts.append(f"# Review Gate\n- Blocking Issues: 0\n{rec_fmt}")
    return "\n\n".join(parts)


def test_review_gate_accepts_bold_and_trailing_notes():
    from app.services.cinema_format import parse_review_gate
    for status_fmt, rec_fmt in (
        ("- Status: PASS", "- Recommendation: PASS"),
        ("- **Status:** **PASS**", "- **Recommendation:** **PASS**"),
        ("- Status: `PASS` (minor nits only)", "- Recommendation: POLISH OPTIONAL"),
    ):
        assert parse_review_gate(_review(status_fmt, rec_fmt))["gate_status"] in {"pass", "polish_optional"}, status_fmt


def test_review_gate_still_blocks_needs_work_and_bold_major_issue():
    from app.services.cinema_format import parse_review_gate
    assert parse_review_gate(_review("- **Status:** NEEDS WORK", "- Recommendation: PASS"))["gate_status"] == "revision_required"
    issue = "## ISSUE 1 — x\n- **Severity:** major (fix first)\n- Problem: y"
    gate = parse_review_gate(_review("- Status: PASS", "- Recommendation: PASS", issue))
    assert gate["major_count"] == 1 and gate["gate_status"] == "revision_required"


def test_one_attribution_policy_is_shared_by_all_narration_prompts():
    from app.services import cinema_format as cf
    for prompt in (cf.WRITER_SYSTEM, cf.REVIEWER_SYSTEM, cf.REVISION_SYSTEM, cf.ENRICHMENT_REWRITE_SYSTEM, cf.FACT_CHECK_SYSTEM):
        assert cf.ATTRIBUTION_POLICY in prompt
    assert "Do not mention sources aloud unless" not in cf.WRITER_SYSTEM


def test_spoken_outlet_phrasing_counts_as_attribution():
    from app.services.claim_ledger import _attribution_present
    claim = {"attribution_required": True}
    assert _attribution_present("ورایتی می‌گه حدود ۴۰ میلیون فروخته", claim, True)
    assert _attribution_present("حدود ۴۰ میلیون فروخته", claim, True)
    assert not _attribution_present("۴۰ میلیون فروخته", claim, True)


def test_length_target_and_word_count():
    from app.services.cinema_format import length_target, narration_word_count, WRITER_SYSTEM, REVIEWER_SYSTEM
    draft = "## بخش\n\n<!-- STORY:a --> [thoughtful] این یک جملهٔ کوتاهه و می‌شه شمردش.\n"
    assert narration_word_count(draft) == 7
    target = length_target({"target_minutes": 5, "language": "Persian"}, draft)
    assert target["target_words"] == 700
    assert target["acceptable_words"] == [595, 770]
    assert target["current_draft_words"] == 7
    assert "length_target" in WRITER_SYSTEM and "length_target" in REVIEWER_SYSTEM


def test_spoken_lint_flags_written_or_pipeline_speech_and_passes_clean_text():
    from app.services.cinema_format import spoken_lint, SPOKEN_QUALITY_RULES, WRITER_SYSTEM, FACT_CHECK_SYSTEM
    bad = ("<!-- STORY:a --> ددلاین گزارش داده این فیلم حدود ۴۲.۷ میلیون دلار فروخته. رقمی که دقیقاً مربوط به افتتاحیه است.\n"
           "ورایتی را هم داریم. رویترز گفته. بلومبرگ هم گفته. البته در شواهد موجود مشخص نشده. این را دارد و آن را آمده. اینه و رو.")
    rules = {f["rule"] for f in spoken_lint(bad)}
    assert {"pipeline_language", "scope_disclaimer", "spoken_decimal", "outlet_names", "register_drift"} <= rules
    clean = "<!-- STORY:a --> این فیلم تو آخرهفتهٔ اولش حدود ۴۳ میلیون دلار فروخت. حالا بریم سراغ سریال‌ها که خبرای خوبی داره."
    assert spoken_lint(clean) == []
    assert SPOKEN_QUALITY_RULES in WRITER_SYSTEM and SPOKEN_QUALITY_RULES in FACT_CHECK_SYSTEM


def test_content_plan_is_claim_id_only_to_avoid_translationese():
    from app.services.cinema_format import CONTENT_PLAN_SYSTEM
    assert "MUST NOT write English or Persian prose" in CONTENT_PLAN_SYSTEM
    assert '"hook_claim_ids"' in CONTENT_PLAN_SYSTEM
    assert '"bridge_relation"' in CONTENT_PLAN_SYSTEM


def _new_format_review(issues: str) -> str:
    audits = "\n\n".join(f"{h}\n- Status: {st}\n- Notes: n" for h, st in (
        ("# Format Audit", "PASS"), ("# Style Audit", "PASS"), ("# Factual / Source Audit", "PASS"),
        ("# Freshness Audit", "PASS"), ("# Context / Spice Audit", "PASS"), ("# Storytelling Audit", "PASS")))
    return ("# Review Summary\nReady to voice: yes\nGood.\n\n# Keep\n- «حالا برسیم به گیشه» (Status: keep)\n\n"
            + audits + f"\n\n# Issues\n{issues}\n\n# Review Gate\n- Recommendation: POLISH_OPTIONAL")


def test_reviewer_minor_issues_do_not_block_and_keep_section_is_ignored_by_gate():
    from app.services.cinema_format import parse_review_gate
    minor = "## ISSUE 1 — x\n- Severity: minor\n- Section: s\n- Problem: «a»\n- Fix: b"
    gate = parse_review_gate(_new_format_review(minor))
    assert gate["minor_count"] == 1 and gate["gate_status"] == "polish_optional"
    major = minor.replace("minor", "major")
    assert parse_review_gate(_new_format_review(major))["gate_status"] == "revision_required"


def test_reviewer_prompt_defines_severity_and_audit_status():
    from app.services.cinema_format import REVIEWER_SYSTEM, REVISION_SYSTEM
    assert "Minor issues never fail an audit" in REVIEWER_SYSTEM
    assert "At most 12 issues" in REVIEWER_SYSTEM and "# Keep" in REVIEWER_SYSTEM
    assert '"# Keep"' in REVISION_SYSTEM



def test_spoken_lint_flags_translationese_phrasing():
    findings = spoken_lint(
        "نتفلیکس چند عنوان تازه رو جلو آورد. "
        "این فیلم وارد رادار شد. "
        "فروش تجمعی جهانی فیلم بالا رفت."
    )
    rules = {item["rule"] for item in findings}
    assert "translationese" in rules


def test_writer_rules_prefer_natural_persian_over_ledger_labels():
    assert "NATURAL PERSIAN OVER LITERAL TRANSLATION" in WRITER_SYSTEM
    assert "فروش تجمعی جهانی" in WRITER_SYSTEM
    assert "THIN STORY RULE" in WRITER_SYSTEM



def test_weekly_writer_uses_weekly_news_references_not_monthly_preview_format():
    rows = [
        {"name": "2026-09-11 آخرین و جدید ترین اخبار سینمای جهان.txt", "content": "هر هفته میریم یه نگاهی بندازیم به جدیدترین اتفاقاتی که توی سینما افتادن", "enabled": 1},
        {"name": "2026-09-04 آخرین و جدید ترین اخبار سینمای جهان.txt", "content": "امروزم مثل هر هفته میریم سراغ خبرها", "enabled": 1},
        {"name": "2026-08-28 آخرین و جدید ترین اخبار سینمای جهان.txt", "content": "این هفته توی سینما یه عالم اتفاق افتاد", "enabled": 1},
        {"name": "2026-08-23 معرفی مورد انتظارترین فیلم ها و سریال‌های ماه.txt", "content": "امروز قراره فیلم‌هایی که ماه بعد میان رو معرفی کنیم", "enabled": 1},
    ]
    fitted = style_rows_for_content_type(rows, "weekly_news")
    assert len(fitted) == 3
    assert all("مورد انتظارترین" not in row["name"] for row in fitted)


def test_content_plan_uses_claim_ids_instead_of_english_prose_notes():
    assert '"hook_claim_ids"' in CONTENT_PLAN_SYSTEM
    assert '"detail_claim_ids"' in CONTENT_PLAN_SYSTEM
    assert "MUST NOT write English or Persian prose" in CONTENT_PLAN_SYSTEM
    assert "terse ENGLISH fact note" not in CONTENT_PLAN_SYSTEM


def test_fluency_polish_is_wording_only_and_style_corpus_driven():
    assert "final spoken-Persian editor" in NARRATION_FLUENCY_POLISH_SYSTEM
    assert "SAME-FORMAT weekly-news style references" in NARRATION_FLUENCY_POLISH_SYSTEM
    assert "Do not expand merely to hit a duration target" in NARRATION_FLUENCY_POLISH_SYSTEM



def test_review_gate_does_not_force_revision_for_minor_only_inconsistent_audit_status():
    review = """# Review Summary
Mostly clean.

# Format Audit
- Status: PASS
- Notes: fine

# Style Audit
- Status: NEEDS_WORK
- Notes: one small awkward phrase

# Factual / Source Audit
- Status: PASS
- Notes: fine

# Freshness Audit
- Status: PASS
- Notes: fine

# Context / Spice Audit
- Status: PASS
- Notes: fine

# Storytelling Audit
- Status: PASS
- Notes: fine

# Issues
## ISSUE 1 — awkward phrase
- Severity: minor
- Section: Upcoming Films
- Problem: one phrase is clunky
- Fix: simplify it

# Review Gate
- Blocking Issues: 0
- Major Issues: 0
- Minor Issues: 1
- Recommendation: REVISION_REQUIRED
"""
    assert parse_review_gate(review)["gate_status"] == "polish_optional"


def test_every_prose_prompt_starts_from_the_same_host_voice():
    from app.services import cinema_format as cf
    for prompt in (cf.WRITER_SYSTEM, cf.REVISION_SYSTEM, cf.ENRICHMENT_REWRITE_SYSTEM,
                   cf.NARRATION_FLUENCY_POLISH_SYSTEM, cf.NARRATION_ASSEMBLY_REPAIR_SYSTEM):
        assert cf.HOST_VOICE in prompt
        # voice comes before the rule wall
        assert prompt.index(cf.HOST_VOICE) < prompt.index(cf.ATTRIBUTION_POLICY) if cf.ATTRIBUTION_POLICY in prompt else True


def test_prompts_never_prescribe_database_scope_wording():
    from app.services import cinema_format as cf
    for prompt in (cf.WRITER_SYSTEM, cf.FACT_CHECK_SYSTEM, cf.REVIEWER_SYSTEM):
        assert "در جدول آخرهفتهٔ آمریکای شمالی ... رتبهٔ اول" not in prompt
    assert "Ordinary spoken scope is enough" in cf.FACT_CHECK_SYSTEM


def test_lint_flags_database_persian_and_headline_items():
    from app.services.cinema_format import spoken_lint
    draft = "\n".join(
        f"<!-- STORY:s{i} -->\nفیلم {i} در جدول گیشه آخرهفته داخلی آمریکای شمالی اول شد." for i in range(4)
    )
    rules = {f["rule"] for f in spoken_lint(draft)}
    assert {"written_or_database_persian", "headline_items"} <= rules
    rich = "\n".join(
        f"<!-- STORY:s{i} -->\nاین فیلم این آخر هفته تو آمریکا اول شد. یعنی از همه جلو زد دیگه. "
        f"جالبش اینجاست که بودجه‌ش خیلی کم بوده. کارگردانش گفتش که انتظارشو نداشته." for i in range(4)
    )
    assert not {"written_or_database_persian", "headline_items"} & {f["rule"] for f in spoken_lint(rich)}
