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



def test_unqualified_number_one_claim_is_blocked():
    draft = """
<!-- STORY:endgame -->
«Avengers: Endgame Encore» این هفته مستقیم رفت صدر جدول.
"""
    fresh = {
        "endgame": [
            {
                "title": "Domestic 2026 Weekend 39",
                "snippet": "Avengers Endgame: Encore ranked number one for the Sep. 25-27 domestic weekend.",
            }
        ]
    }
    flags = _deterministic_fact_red_flags(draft, fresh)
    assert any(flag["rule"] == "unqualified_box_office_rank" for flag in flags)


def test_explicit_domestic_weekend_number_one_claim_is_allowed():
    draft = """
<!-- STORY:endgame -->
«Avengers: Endgame Encore» در جدول آخرهفتهٔ آمریکای شمالی رتبهٔ اول را گرفت.
"""
    fresh = {
        "endgame": [
            {
                "title": "Domestic 2026 Weekend 39",
                "snippet": "Avengers Endgame: Encore ranked number one for the Sep. 25-27 domestic weekend.",
            }
        ]
    }
    flags = _deterministic_fact_red_flags(draft, fresh)
    assert not any(flag["rule"] == "unqualified_box_office_rank" for flag in flags)


def test_fact_check_over_edit_guard():
    from app.main import _fact_check_over_edit
    draft = ("<!-- STORY:a --> جملهٔ اول درباره فیلم. جملهٔ دوم با عدد ۴۳ میلیون. جملهٔ سوم.\n\n"
             "<!-- STORY:b --> خبر دوم. ادامهٔ خبر دوم. پایان خبر دوم.")
    fixed_one = draft.replace("۴۳ میلیون", "حدود ۴۳ میلیون")
    assert _fact_check_over_edit(draft, fixed_one, 1) == ""
    dropped_story = "<!-- STORY:a --> جملهٔ اول درباره فیلم. جملهٔ دوم با عدد ۴۳ میلیون. جملهٔ سوم."
    assert "removed" in _fact_check_over_edit(draft, dropped_story, 1)
    rewritten = ("<!-- STORY:a --> متن کاملاً تازه یک. تازه دو. تازه سه.\n\n"
                 "<!-- STORY:b --> تازه چهار. تازه پنج. تازه شش.")
    assert "changed 6 sentences" in _fact_check_over_edit(draft, rewritten, 1)
