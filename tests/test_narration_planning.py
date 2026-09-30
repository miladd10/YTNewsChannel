from app.main import (
    _fallback_content_plan,
    _narration_story_packet,
    _validate_content_plan,
)


def _stories():
    return [
        {
            "id": "s1",
            "category": "upcoming_films",
            "canonical_title": "Paper Tiger trailer released",
            "news_hook": "The official trailer was released this week.",
            "news_hook_date": "2026-09-25",
            "search_subject": "Paper Tiger",
            "familiarity_anchor": "James Gray",
            "summary": "Long model-written research summary that must not reach the writer.",
            "articles": [{"url": "https://example.com", "excerpt": "A very long English article excerpt."}],
            "spice_angles": [],
            "visual_context": [],
        },
        {
            "id": "s2",
            "category": "tv_series",
            "canonical_title": "Blackmere title announced",
            "news_hook": "The official title was announced this week.",
            "news_hook_date": "2026-09-25",
            "search_subject": "Blackmere",
            "familiarity_anchor": "Charlie Brooker",
            "articles": [{"url": "https://example.com/2", "excerpt": "Another article."}],
            "spice_angles": [],
            "visual_context": [],
        },
    ]


def _ledger():
    return [
        {
            "id": "C001", "story_id": "s1", "claim_role": "current_hook",
            "claim_type": "release", "verification_status": "verified",
        },
        {
            "id": "C002", "story_id": "s1", "claim_role": "supporting",
            "claim_type": "cast", "verification_status": "verified",
        },
        {
            "id": "C003", "story_id": "s2", "claim_role": "current_hook",
            "claim_type": "release", "verification_status": "verified",
        },
    ]


def test_writer_story_packet_does_not_include_raw_research_prose():
    packet = _narration_story_packet(_stories())
    serialized = repr(packet)
    assert "articles" not in serialized
    assert "excerpt" not in serialized
    assert "Long model-written research summary" not in serialized
    assert "Paper Tiger trailer released" in serialized
    assert "The official trailer was released this week." in serialized


def test_content_plan_validator_requires_every_story_current_hook():
    bad = {
        "intro_claim_ids": [],
        "sections": [{
            "section": "upcoming_films",
            "stories": [{
                "id": "s1",
                "depth": "quick",
                "hook_claim_ids": ["C002"],
                "setup_claim_ids": [],
                "detail_claim_ids": [],
                "familiarity_claim_ids": [],
                "spice_claim_ids": [],
                "ending_claim_ids": [],
                "bridge_relation": "none",
            }],
        }],
    }
    errors = _validate_content_plan(bad, _stories(), _ledger())
    assert any("not claim_role=current_hook" in error for error in errors)
    assert any("Selected story s2 appears 0 times" in error for error in errors)


def test_deterministic_fallback_plan_covers_all_selected_hooks():
    plan = _fallback_content_plan(_stories(), _ledger())
    assert _validate_content_plan(plan, _stories(), _ledger()) == []
    rows = {
        row["id"]: row
        for section in plan["sections"]
        for row in section["stories"]
    }
    assert rows["s1"]["hook_claim_ids"] == ["C001"]
    assert rows["s2"]["hook_claim_ids"] == ["C003"]


def test_writer_packet_carries_the_fun_fact_text():
    from app.main import _narration_story_packet
    story = {"id": "s1", "category": "upcoming_films", "canonical_title": "T", "spice_angles": [
        {"type": "cool_fact", "text": "یک نکته جالب", "usage_note": "کوتاه بگو", "safe_to_narrate": True},
        {"type": "rumor", "text": "شایعه ضعیف", "safe_to_narrate": False},
    ]}
    packet = _narration_story_packet([story])
    angles = [a for sec in packet for st in sec["stories"] for a in st["spice_angles"]]
    assert angles == [{"type": "cool_fact", "text": "یک نکته جالب", "how_to_use": "کوتاه بگو",
                       "evidence_status": None, "safe_to_narrate": True}]
