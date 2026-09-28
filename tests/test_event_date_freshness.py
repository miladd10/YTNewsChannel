from app.services.research import _apply_story_quality_gates

PROJECT = {"date_start": "2031-03-10", "date_end": "2031-03-17"}  # Monday-start window


def _story(title, published, hook_date="", event_date="", category="box_office"):
    return {"canonical_title": title, "news_hook": "hook", "summary": "", "category": category,
            "freshness": "current", "news_hook_date": hook_date, "news_event_date": event_date,
            "verification_status": "reported", "decision": "include", "score": 8,
            "in_window_source_count": len(published), "current_non_reddit_source_count": len(published),
            "independent_source_count": len(published),
            "source_evidence": [{"published_at": p, "temporal_role": "current"} for p in published]}


def test_event_date_before_window_fails_even_if_article_is_inside():
    story = _apply_story_quality_gates(_story("Studio X announces slate", ["2031-03-11T10:00:00Z"],
                                              hook_date="2031-03-11", event_date="2031-03-08", category="industry"), PROJECT)
    assert story["temporal_gate"] == "fail"


def test_tuesday_report_on_previous_weekend_is_stale():
    story = _apply_story_quality_gates(_story("Box Office Global: Moth Kingdom $90M WW opening", ["2031-03-11T15:00:00Z"]), PROJECT)
    assert story["temporal_gate"] == "fail" and story["decision"] == "skip"


def test_in_window_weekend_report_passes():
    story = _apply_story_quality_gates(_story("Moth Kingdom tops weekend box office", ["2031-03-16T18:00:00Z"]), PROJECT)
    assert story["temporal_gate"] == "pass"


def test_pre_window_weekend_plus_newer_in_window_report_passes():
    story = _apply_story_quality_gates(_story("Moth Kingdom opening weekend box office",
                                              ["2031-03-11T15:00:00Z", "2031-03-16T18:00:00Z"]), PROJECT)
    assert story["temporal_gate"] == "pass"


def test_non_box_office_midweek_news_is_unaffected():
    story = _apply_story_quality_gates(_story("Salt Choir renewed for season 2", ["2031-03-11T15:00:00Z"],
                                              category="tv_series"), PROJECT)
    assert story["temporal_gate"] == "pass"
