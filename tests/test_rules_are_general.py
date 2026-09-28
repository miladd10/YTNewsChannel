"""The fact-check rules must work for ANY story, not only the stories they
were first written for. Every case here uses invented titles, studios, years,
dates and numbers that never appeared in a real project."""

import inspect

from app.main import _deterministic_fact_red_flags
from app.services import claim_ledger, cinema_format, research
from app.services.research import _fact_check_queries, _fact_check_subjects, _fact_check_trust_tier


def _flags(draft: str, fresh: dict) -> set[str]:
    return {flag["rule"] for flag in _deterministic_fact_red_flags(draft, fresh)}


def test_rerelease_guard_is_not_tied_to_one_year():
    for year in ("1997", "2004", "2012"):
        draft = "<!-- STORY:s -->\n«Glass Harbor» فیلم جدید این هفته‌ست.\n"
        fresh = {"s": [{"title": "Glass Harbor returns",
                        "snippet": f"The {year} film is back in theaters in a remastered edition."}]}
        assert "new_movie_vs_rerelease" in _flags(draft, fresh), year


def test_rerelease_guard_covers_reissue_and_anniversary_wording():
    draft = "<!-- STORY:s -->\n«Lantern Road» فیلم تازه‌ایه که اکران شده.\n"
    for snippet in ("A 25th anniversary re-release hits screens.",
                    "The studio reissued the film nationwide.",
                    "The director's cut arrives in cinemas."):
        assert "new_movie_vs_rerelease" in _flags(draft, {"s": [{"title": "", "snippet": snippet}]}), snippet


def test_rerelease_guard_does_not_fire_on_generic_new_version_phrase():
    draft = "<!-- STORY:s -->\n«Lantern Road» فیلم جدید این استودیوئه.\n"
    fresh = {"s": [{"title": "", "snippet": "A new version of the app launched for ticket buyers."}]}
    assert "new_movie_vs_rerelease" not in _flags(draft, fresh)


def test_milestone_guard_works_for_any_title_and_amount():
    draft = "<!-- STORY:s -->\n«Iron Orchard» به مرز ۵۰۰ میلیون دلار نزدیک شده.\n"
    fresh = {"s": [{"title": "Iron Orchard passes $500 million", "snippet": ""}]}
    assert "milestone_crossed_vs_approaching" in _flags(draft, fresh)


def test_rank_guard_correction_uses_a_template_not_a_real_date():
    draft = "<!-- STORY:s -->\n«Iron Orchard» رفت صدر جدول.\n"
    flags = _deterministic_fact_red_flags(draft, {"s": []})
    basis = next(f["correction_basis"] for f in flags if f["rule"] == "unqualified_box_office_rank")
    assert "<exact date range" in basis
    assert not any(ch.isdigit() for ch in basis)


def test_subject_extraction_for_unquoted_invented_headline():
    subjects = _fact_check_subjects({"canonical_title": "Moth Kingdom crosses $250M worldwide - Some Outlet",
                                     "search_subject": ""})
    assert "Moth Kingdom" in subjects


def test_tv_verification_queries_do_not_assume_one_platform():
    story = {"canonical_title": "‘Salt Choir’ renewed for season 2", "category": "tv_series", "search_subject": "Salt Choir"}
    queries = " ".join(_fact_check_queries(story, "2031-03-01", "2031-03-08")).casefold()
    for platform in ("netflix", "hbo", "disney", "apple", "prime", "hulu", "peacock", "paramount"):
        assert platform not in queries


def test_industry_verification_queries_are_not_settlement_specific():
    story = {"canonical_title": "Studio X names new CEO", "category": "industry", "search_subject": "Studio X"}
    queries = " ".join(_fact_check_queries(story, "2031-03-01", "2031-03-08")).casefold()
    assert "settlement" not in queries


def test_trust_tier_covers_studios_beyond_one_weeks_stories():
    for url in ("https://www.lionsgate.com/news/x", "https://a24films.com/news", "https://www.universalpictures.com/x"):
        assert _fact_check_trust_tier(url) == "preferred", url


def test_prompts_contain_no_story_specific_examples():
    text = "\n".join([
        inspect.getsource(cinema_format), inspect.getsource(claim_ledger), inspect.getsource(research),
    ]).casefold()
    for banned in ("108.3", "incredibles", "brad bird", "coyote", "resident evil", "endgame",
                   "sep. 25", "۲۵ تا ۲۷", "70mm", "filmlinc"):
        assert banned not in text, banned
