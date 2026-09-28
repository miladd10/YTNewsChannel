from app.main import _deterministic_fact_red_flags
from app.services.research import _fact_check_subjects


def test_fact_check_subjects_extracts_short_movie_title_from_stale_headline():
    story = {
        "canonical_title": "Coyote vs. Acme approaches $100 million worldwide at box office",
        "search_subject": "",
    }
    subjects = _fact_check_subjects(story)
    assert "Coyote vs. Acme" in subjects


def test_deterministic_flag_catches_crossed_milestone_vs_approaching_persian():
    draft = """
<!-- STORY:coyote -->
«Coyote vs. Acme» هم به مرز ۱۰۰ میلیون دلار جهانی نزدیک شده؛ نزدیک، نه اینکه ازش رد شده باشه.
"""
    fresh = {
        "coyote": [
            {
                "title": "Coyote vs. Acme Crosses $100 Million",
                "snippet": "The film crossed the $100 million mark at the global box office this weekend.",
            }
        ]
    }
    flags = _deterministic_fact_red_flags(draft, fresh)
    assert any(flag["rule"] == "milestone_crossed_vs_approaching" for flag in flags)


def test_endgame_rerelease_wording_is_not_flagged_as_new_movie():
    draft = """
<!-- STORY:endgame -->
«Avengers: Endgame Encore» یک بازاکران از فیلم ۲۰۱۹ است که چند دقیقه تصویر تازه هم دارد.
"""
    fresh = {
        "endgame": [
            {
                "title": "Avengers Endgame: Encore returns to theaters",
                "snippet": "The re-release of the 2019 film includes new footage.",
            }
        ]
    }
    assert _deterministic_fact_red_flags(draft, fresh) == []


def test_endgame_new_movie_wording_is_flagged_when_evidence_says_rerelease():
    draft = """
<!-- STORY:endgame -->
«Avengers: Endgame Encore» فیلم جدید اونجرزه که این هفته اکران شده.
"""
    fresh = {
        "endgame": [
            {
                "title": "Avengers Endgame: Encore returns to theaters",
                "snippet": "The re-release of the 2019 movie is back in theaters with additional footage.",
            }
        ]
    }
    flags = _deterministic_fact_red_flags(draft, fresh)
    assert any(flag["rule"] == "new_movie_vs_rerelease" for flag in flags)
