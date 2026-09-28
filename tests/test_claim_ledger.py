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
