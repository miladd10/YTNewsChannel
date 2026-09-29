import json

import app.services.claim_ledger as claim_ledger
from app.services.claim_ledger import (
    _validate_spoken_claim,
    high_risk_sentences,
    normalize_ledger_claims,
)


STORY = {
    "id": "story-1",
    "canonical_title": "Resident Evil",
    "articles": [
        {
            "url": "https://example.com/source",
            "source": "Example Trade",
            "title": "Resident Evil box office",
            "snippet": "Evidence",
        }
    ],
    "spice_sources": [],
}


def _fresh():
    return {
        "story-1": [
            {
                "url": "https://example.com/fresh",
                "source": "Box Office Data",
                "title": "Weekend chart",
                "snippet": "Evidence",
                "trust_tier": "preferred",
            }
        ]
    }


def test_complete_ranking_claim_keeps_exact_scope():
    raw = [{
        "story_id": "story-1",
        "claim_type": "ranking",
        "subject": "Resident Evil",
        "predicate": "ranked",
        "canonical_text": "Resident Evil ranked #1 on the domestic weekly chart.",
        "numeric_value": None,
        "rank": 1,
        "metric": "box_office_rank",
        "market": "domestic",
        "region": "US/Canada",
        "chart_type": "weekly",
        "period_type": "weekly",
        "date_start": "2026-09-18",
        "date_end": "2026-09-24",
        "source_urls": ["https://example.com/fresh"],
        "verification_status": "verified",
    }]
    claims = normalize_ledger_claims(raw, [STORY], _fresh())
    assert claims[0]["verification_status"] == "verified"
    assert claims[0]["chart_type"] == "weekly"
    assert claims[0]["market"] == "domestic"
    assert claims[0]["date_start"] == "2026-09-18"
    assert claims[0]["date_end"] == "2026-09-24"


def test_ranking_without_chart_scope_is_blocked():
    raw = [{
        "story_id": "story-1",
        "claim_type": "ranking",
        "canonical_text": "Resident Evil was #1.",
        "rank": 1,
        "market": "domestic",
        "source_urls": ["https://example.com/fresh"],
        "verification_status": "verified",
    }]
    claim = normalize_ledger_claims(raw, [STORY], _fresh())[0]
    assert claim["verification_status"] == "blocked"
    assert any("Ranking requires" in note for note in claim["validation_notes"])


def test_opening_weekend_does_not_validate_current_cumulative_claim():
    ledger = {
        "C001": {
            "id": "C001",
            "story_id": "story-1",
            "claim_type": "box_office",
            "numeric_value": 108.3,
            "unit": "million",
            "currency": "USD",
            "market": "worldwide",
            "period_type": "opening_weekend",
            "verification_status": "verified",
            "attribution_required": False,
        }
    }
    spoken = {
        "story_id": "story-1",
        "sentence": "Resident Evil has now reached $108.3 million worldwide.",
        "claim_type": "box_office",
        "numeric_value": 108.3,
        "unit": "million",
        "currency": "USD",
        "market": "worldwide",
        "period_type": "current_cumulative",
        "ledger_claim_ids": ["C001"],
        "semantic_match": "equivalent",
    }
    checked = _validate_spoken_claim(spoken, ledger)
    assert checked["status"] == "blocked"
    assert "market/period scope" in checked["issue"]


def test_financial_claim_without_metric_is_blocked_in_ledger():
    raw = [{
        "story_id": "story-1",
        "claim_type": "budget",
        "canonical_text": "The reported budget was $150 million.",
        "numeric_value": 150,
        "unit": "million",
        "currency": "USD",
        "source_urls": ["https://example.com/source"],
        "verification_status": "verified",
    }]
    claim = normalize_ledger_claims(raw, [STORY], _fresh())[0]
    assert claim["verification_status"] == "blocked"
    assert any("Budget claim" in note for note in claim["validation_notes"])


def test_reported_estimate_requires_attribution_in_narration():
    ledger = {
        "C001": {
            "id": "C001",
            "story_id": "story-1",
            "claim_type": "budget",
            "numeric_value": 150,
            "unit": "million",
            "metric": "production_budget",
            "verification_status": "verified_with_attribution",
            "attribution_required": True,
        }
    }
    spoken = {
        "story_id": "story-1",
        "sentence": "بودجه فیلم ۱۵۰ میلیون دلار بوده.",
        "claim_type": "budget",
        "numeric_value": 150,
        "unit": "million",
        "metric": "production_budget",
        "ledger_claim_ids": ["C001"],
        "semantic_match": "equivalent",
        "attribution_present": False,
    }
    checked = _validate_spoken_claim(spoken, ledger)
    assert checked["status"] == "blocked"
    assert "attribution" in checked["issue"].lower()


def test_high_risk_sentence_detection_catches_persian_numbers_and_box_office():
    draft = """
<!-- STORY:story-1 -->
فروش جهانی فیلم به ۱۹۶.۵ میلیون دلار رسیده.
"""
    rows = high_risk_sentences(draft)
    assert len(rows) == 1
    assert rows[0]["story_id"] == "story-1"


def test_unextracted_high_risk_sentence_blocks_whole_audit(monkeypatch):
    def fake_generate_text(provider, model, system, user):
        return json.dumps({"claims": []}), provider, model

    monkeypatch.setattr(claim_ledger, "generate_text", fake_generate_text)
    audit, _, _ = claim_ledger.audit_narration_claims(
        """
<!-- STORY:story-1 -->
فروش جهانی فیلم به ۱۹۶.۵ میلیون دلار رسیده.
""",
        [{
            "id": "C001",
            "story_id": "story-1",
            "claim_type": "box_office",
            "canonical_text": "Worldwide cumulative gross was $196.5 million.",
            "numeric_value": 196.5,
            "unit": "million",
            "market": "worldwide",
            "period_type": "cumulative",
            "verification_status": "verified",
            "attribution_required": False,
        }],
        "test",
        "test",
    )
    assert audit["status"] == "blocked"
    assert audit["uncovered_high_risk_count"] == 1
    assert audit["blocked_count"] >= 1


def test_dates_and_counts_are_not_auto_blocked():
    from app.services.claim_ledger import normalize_ledger_claims
    stories = [{"id": "s1", "articles": [{"url": "u"}]}]
    raw = [
        {"story_id": "s1", "claim_type": "release", "canonical_text": "Moth Kingdom opens in select theaters on March 3, 2031.",
         "release_scope": "limited theatrical", "source_urls": ["u"], "verification_status": "verified"},
        {"story_id": "s1", "claim_type": "company", "canonical_text": "Studio X settled with 9 regulators.",
         "source_urls": ["u"], "verification_status": "verified"},
    ]
    assert [c["verification_status"] for c in normalize_ledger_claims(raw, stories, {})] == ["verified", "verified"]


def test_money_without_structured_value_is_still_blocked():
    from app.services.claim_ledger import normalize_ledger_claims
    stories = [{"id": "s1", "articles": [{"url": "u"}]}]
    raw = [{"story_id": "s1", "claim_type": "company", "canonical_text": "The deal is worth $4 billion.",
            "source_urls": ["u"], "verification_status": "verified"}]
    assert normalize_ledger_claims(raw, stories, {})[0]["verification_status"] == "blocked"


def test_spoken_count_matches_ledger_text_without_structured_value():
    from app.services.claim_ledger import _validate_spoken_claim
    ledger = {"C001": {"id": "C001", "story_id": "s1", "claim_type": "company", "numeric_value": None,
                       "canonical_text": "Studio X settled with 9 regulators.", "verification_status": "verified"}}
    ok = _validate_spoken_claim({"story_id": "s1", "sentence": "با ۹ نهاد نظارتی توافق کرد.", "claim_type": "company",
                                 "numeric_value": 9, "ledger_claim_ids": ["C001"], "semantic_match": "equivalent"}, ledger)
    bad = _validate_spoken_claim({"story_id": "s1", "sentence": "با ۱۱ نهاد نظارتی توافق کرد.", "claim_type": "company",
                                  "numeric_value": 11, "ledger_claim_ids": ["C001"], "semantic_match": "equivalent"}, ledger)
    assert ok["status"] == "verified"
    assert bad["status"] == "blocked"


def test_high_risk_filter_matches_whole_words_only():
    from app.services.claim_ledger import HIGH_RISK_RE
    risky = ["فروش افتتاحیه‌ش بالا بود", "گیشهٔ جهانی رو گرفت", "اکرانش از هفته بعده", "رتبهٔ اول شد",
             "It grossed a lot", "ranked first", "the release is limited", "۱۲ ایالت", "$4"]
    safe = ["بازاکران یه فیلم خودش خبر بزرگیه", "فروشگاه‌ها شلوغ بودن", "هزاران طرفدار اومدن",
            "این فیلم ارزش دیدن داره", "Frank Oz is in it", "a frankly odd choice"]
    for text in risky:
        assert HIGH_RISK_RE.search(text), text
    for text in safe:
        assert not HIGH_RISK_RE.search(text), text


def test_spoken_numbers_may_be_rounded_to_spoken_precision():
    from app.services.claim_ledger import _same_number
    ledger = {"numeric_value": 42.7, "unit": "million"}
    assert _same_number({"numeric_value": 43, "unit": "million"}, ledger)
    assert _same_number({"numeric_value": 42.7, "unit": "million"}, ledger)
    assert not _same_number({"numeric_value": 45, "unit": "million"}, ledger)
    assert not _same_number({"numeric_value": 41, "unit": "million"}, ledger)
    assert _same_number({"numeric_value": 1.2, "unit": "billion"}, {"numeric_value": 1234, "unit": "million"})
    assert _same_number({"numeric_value": 1.3, "unit": "billion"}, {"numeric_value": 1260, "unit": "million"})
    assert not _same_number({"numeric_value": 2, "unit": "billion"}, {"numeric_value": 1234, "unit": "million"})


def test_scope_synonyms_match_but_real_scope_differences_do_not():
    from app.services.claim_ledger import _field_equal
    assert _field_equal("North America", "domestic", "market")
    assert _field_equal("US/Canada", "domestic", "market")
    assert _field_equal("global", "worldwide", "market")
    assert not _field_equal("domestic", "worldwide", "market")
    assert not _field_equal("international", "worldwide", "market")
    assert _field_equal("opening weekend", "weekend", "period_type")
    assert not _field_equal("opening weekend", "cumulative", "period_type")
    assert not _field_equal("opening weekend total", "cumulative", "period_type")
    assert not _field_equal("weekend", "weekly", "period_type")
    assert _field_equal("weekend box office", "weekend chart", "chart_type")
    assert _field_equal("select theatrical", "limited large-format theatrical", "release_scope")
    assert not _field_equal("wide theatrical", "limited theatrical", "release_scope")
    assert _field_equal("reissue", "re-release", "title_identity")
    assert not _field_equal("sequel", "re-release", "title_identity")
    assert _field_equal("production budget", "budget", "metric")
    assert not _field_equal("marketing spend", "production budget", "metric")
    assert not _field_equal("enterprise value", "equity value", "metric")


def test_confirmed_routine_facts_do_not_require_spoken_attribution():
    from app.services.claim_ledger import normalize_ledger_claims
    stories = [{"id": "s1", "articles": [{"url": "u"}]}]
    raw = [
        {"story_id": "s1", "claim_type": "cast", "canonical_text": "Ana Ruiz voices the lead in Moth Kingdom.",
         "attribution_required": True, "estimate_status": "confirmed", "source_urls": ["u"], "verification_status": "verified_with_attribution"},
        {"story_id": "s1", "claim_type": "box_office", "canonical_text": "Moth Kingdom opened to $40 million worldwide.",
         "numeric_value": 40, "unit": "million", "market": "worldwide", "period_type": "weekend",
         "estimate_status": "reported_estimate", "source_urls": ["u"], "verification_status": "verified"},
        {"story_id": "s1", "claim_type": "production", "canonical_text": "Studio X is reportedly in talks to acquire the rights.",
         "attribution_required": True, "source_urls": ["u"], "verification_status": "verified_with_attribution"},
    ]
    out = normalize_ledger_claims(raw, stories, {})
    assert [(c["attribution_required"], c["verification_status"]) for c in out] == [
        (False, "verified"), (True, "verified_with_attribution"), (True, "verified_with_attribution")]


def test_sources_of_duplicate_stories_about_same_subject_are_accepted():
    from app.services.claim_ledger import normalize_ledger_claims
    stories = [
        {"id": "a", "search_subject": "Moth Kingdom", "articles": [{"url": "ua"}]},
        {"id": "b", "search_subject": "moth kingdom", "articles": [{"url": "ub"}]},
        {"id": "c", "search_subject": "Salt Choir", "articles": [{"url": "uc"}]},
    ]
    raw = [
        {"story_id": "a", "claim_type": "person_credit", "canonical_text": "Ana Ruiz directed Moth Kingdom.", "source_urls": ["ub"], "verification_status": "verified"},
        {"story_id": "a", "claim_type": "person_credit", "canonical_text": "Ana Ruiz directed Moth Kingdom.", "source_urls": ["uc"], "verification_status": "verified"},
    ]
    out = normalize_ledger_claims(raw, stories, {})
    assert out[0]["verification_status"] == "verified" and out[0]["source_urls"] == ["ub"]
    assert out[1]["verification_status"] == "blocked"


def test_all_time_ranking_needs_no_date_window():
    from app.services.claim_ledger import normalize_ledger_claims
    stories = [{"id": "a", "articles": [{"url": "u"}]}]
    raw = [{"story_id": "a", "claim_type": "ranking", "canonical_text": "Moth Kingdom is No. 2 all time worldwide.", "rank": 2,
            "chart_type": "all-time worldwide box office", "market": "worldwide", "source_urls": ["u"], "verification_status": "verified"},
           {"story_id": "a", "claim_type": "ranking", "canonical_text": "Moth Kingdom was No. 1 on the weekend chart.", "rank": 1,
            "chart_type": "weekend box office", "market": "domestic", "source_urls": ["u"], "verification_status": "verified"}]
    out = normalize_ledger_claims(raw, stories, {})
    assert out[0]["verification_status"] != "blocked" and out[1]["verification_status"] == "blocked"


def test_ledger_input_carries_familiarity_anchor():
    from app.services.claim_ledger import _ledger_input, CLAIM_LEDGER_SYSTEM
    packet = _ledger_input([{"id": "a", "familiarity_anchor": "director of Glass Harbor", "search_subject": "Moth Kingdom"}], {}, {})
    assert packet["stories"][0]["familiarity_anchor"] == "director of Glass Harbor"
    assert "familiarity_anchor" in CLAIM_LEDGER_SYSTEM



def test_opening_weekend_is_not_generic_weekend_scope():
    from app.services.claim_ledger import _field_equal
    assert _field_equal("opening weekend", "opening_weekend", "period_type")
    assert not _field_equal("opening weekend", "weekend", "period_type")
    assert not _field_equal("second weekend", "opening_weekend", "period_type")


def test_box_office_extraction_cannot_omit_scope_fields():
    ledger = {
        "C001": {
            "id": "C001",
            "story_id": "s1",
            "claim_type": "box_office",
            "numeric_value": 40,
            "unit": "million",
            "market": "worldwide",
            "period_type": "opening_weekend",
            "verification_status": "verified",
            "attribution_required": False,
        }
    }
    checked = _validate_spoken_claim({
        "story_id": "s1",
        "sentence": "فیلم ۴۰ میلیون دلار فروخت.",
        "claim_type": "box_office",
        "numeric_value": 40,
        "unit": "million",
        "ledger_claim_ids": ["C001"],
        "semantic_match": "equivalent",
    }, ledger)
    assert checked["status"] == "blocked"
    assert "missing market or period" in checked["issue"].lower()


def test_ranking_extraction_cannot_omit_date_range():
    ledger = {
        "C001": {
            "id": "C001",
            "story_id": "s1",
            "claim_type": "ranking",
            "rank": 1,
            "chart_type": "weekend",
            "market": "domestic",
            "date_start": "2026-09-25",
            "date_end": "2026-09-27",
            "verification_status": "verified",
            "attribution_required": False,
        }
    }
    checked = _validate_spoken_claim({
        "story_id": "s1",
        "sentence": "در گیشه آخرهفته آمریکای شمالی اول شد.",
        "claim_type": "ranking",
        "rank": 1,
        "chart_type": "weekend",
        "market": "domestic",
        "ledger_claim_ids": ["C001"],
        "semantic_match": "equivalent",
    }, ledger)
    assert checked["status"] == "blocked"
    assert "exact date range" in checked["issue"].lower()


def test_financial_extraction_cannot_omit_metric():
    ledger = {
        "C001": {
            "id": "C001",
            "story_id": "s1",
            "claim_type": "deal_value",
            "numeric_value": 110,
            "unit": "billion",
            "metric": "transaction_value",
            "verification_status": "verified",
            "attribution_required": False,
        }
    }
    checked = _validate_spoken_claim({
        "story_id": "s1",
        "sentence": "ارزش معامله ۱۱۰ میلیارد دلار بود.",
        "claim_type": "deal_value",
        "numeric_value": 110,
        "unit": "billion",
        "ledger_claim_ids": ["C001"],
        "semantic_match": "equivalent",
    }, ledger)
    assert checked["status"] == "blocked"
    assert "missing the metric" in checked["issue"].lower()
