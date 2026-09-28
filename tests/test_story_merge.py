from app.services.research import merge_duplicate_stories, story_subject_key

PROJECT = {"date_start": "2031-03-01", "date_end": "2031-03-08"}


def _article(aid, source, day="2031-03-03"):
    return {"id": aid, "title": f"t{aid}", "url": f"https://{source}.example/{aid}", "source": source,
            "published_at": f"{day}T12:00:00Z", "raw": {}}


def _story(sid, subject, ids, decision="maybe", score=5.0, verification="reported", category="box_office"):
    return {"id": sid, "canonical_title": f"title {sid}", "search_subject": subject, "article_ids": ids,
            "decision": decision, "score": score, "source_count": len(ids), "category": category,
            "verification_status": verification, "freshness": "current", "news_hook": f"hook {sid}",
            "news_hook_date": "2031-03-03", "rationale": "r", "in_window_source_count": 1,
            "current_non_reddit_source_count": 1, "independent_source_count": 1}


def test_subject_key_ignores_case_punctuation_years_and_generic_words():
    assert story_subject_key("Moth Kingdom: 2031 Box Office") == story_subject_key("moth kingdom")
    assert story_subject_key("Salt Choir Season 2") != story_subject_key("Salt Choir Season 3")
    assert story_subject_key("") == ""


def test_same_subject_stories_merge_and_combined_evidence_counts():
    articles = [_article("a1", "outleta"), _article("a2", "outletb"), _article("a3", "outletc")]
    stories = [
        _story("s1", "Moth Kingdom", ["a1"], decision="include", score=8, category="trend"),
        _story("s2", "moth kingdom box office", ["a2", "a3"], score=6),
        _story("s3", "Salt Choir", ["a3"], score=4, category="tv_series"),
    ]
    merged = merge_duplicate_stories(stories, articles, PROJECT)
    assert len(merged) == 2
    moth = next(s for s in merged if s["id"] == "s1")
    assert moth["article_ids"] == ["a1", "a2", "a3"]
    assert moth["category"] == "trend" and moth["decision"] == "include" and moth["news_hook"] == "hook s1"
    assert moth["in_window_source_count"] == 3 and moth["independent_source_count"] == 3
    assert moth["merged_story_count"] == 2


def test_merge_does_not_inflate_trust_beyond_evidence():
    articles = [_article("a1", "sameoutlet"), _article("a2", "sameoutlet")]
    stories = [_story("s1", "Lantern Road", ["a1"], verification="verified"), _story("s2", "Lantern Road", ["a2"])]
    merged = merge_duplicate_stories(stories, articles, PROJECT)
    assert len(merged) == 1
    assert merged[0]["verification_status"] == "reported"  # one independent outlet caps "verified"


def test_stories_without_subject_are_never_merged():
    articles = [_article("a1", "x"), _article("a2", "y")]
    stories = [_story("s1", "", ["a1"]), _story("s2", "", ["a2"])]
    assert len(merge_duplicate_stories(stories, articles, PROJECT)) == 2
