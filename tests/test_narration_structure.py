from app.services.cinema_format import narration_structure_audit
from app.main import _claim_audit_with_structure


def _project():
    return {"target_minutes": 5, "language": "Persian"}


def _stories():
    return [
        {"id": "s1", "canonical_title": "Deal Story", "category": "industry"},
        {"id": "s2", "canonical_title": "Movie Story", "category": "upcoming_films"},
        {"id": "s3", "canonical_title": "TV Story", "category": "tv_series"},
    ]


def test_structure_audit_catches_missing_selected_story_and_short_draft():
    text = """
## صنعت سینما
<!-- STORY:s1 -->
یک خبر کوتاه درباره معامله.

## فیلم‌های جدید
<!-- STORY:s2 -->
یک خبر کوتاه درباره فیلم.

## پایان
خداحافظ.
"""
    result = narration_structure_audit(text, _stories(), _project())
    assert result["status"] == "needs_repair"
    assert result["missing_story_ids"] == ["s3"]
    assert result["covered_story_count"] == 2
    assert result["length_status"] == "short"


def test_structure_audit_catches_story_under_wrong_section():
    text = """
## صنعت سینما
<!-- STORY:s1 -->
خبر معامله.

<!-- STORY:s2 -->
خبر فیلم.
"""
    result = narration_structure_audit(text, _stories()[:2], {"target_minutes": 0.05, "language": "Persian"})
    assert result["wrong_sections"]
    assert any(item["story_id"] == "s2" for item in result["wrong_sections"])


def test_structure_audit_passes_complete_ordered_episode_when_length_is_in_range():
    body = " ".join(["خبر"] * 25)
    text = f"""
## صنعت سینما
<!-- STORY:s1 -->
{body}

## فیلم‌های جدید
<!-- STORY:s2 -->
{body}

## سریال‌ها
<!-- STORY:s3 -->
{body}
"""
    project = {"target_minutes": 0.55, "language": "Persian"}
    result = narration_structure_audit(text, _stories(), project)
    assert result["missing_story_ids"] == []
    assert result["wrong_sections"] == []
    assert not result["section_order_violation"]
    assert result["length_status"] == "ok"
    assert result["status"] == "pass"



def test_short_complete_episode_is_warning_not_forced_repair():
    text = """
## صنعت سینما
<!-- STORY:s1 -->
خبر معامله.

## فیلم‌های جدید
<!-- STORY:s2 -->
خبر فیلم.

## سریال‌ها
<!-- STORY:s3 -->
خبر سریال.
"""
    result = narration_structure_audit(text, _stories(), _project())
    assert result["missing_story_ids"] == []
    assert result["length_status"] == "short"
    assert result["status"] == "pass"
    assert result["advisory_issues"]



def test_claim_audit_requires_current_hook_not_just_story_marker():
    story = {"id": "s1", "canonical_title": "Paper Tiger trailer", "category": "upcoming_films"}
    ledger = [
        {
            "id": "C001",
            "story_id": "s1",
            "claim_role": "current_hook",
            "verification_status": "verified",
            "canonical_text": "The official trailer was released.",
        },
        {
            "id": "C002",
            "story_id": "s1",
            "claim_role": "background",
            "verification_status": "verified",
            "canonical_text": "Paper Tiger is a James Gray film.",
        },
    ]
    structure = {
        "blocking_issues": [],
        "major_issues": [],
        "status": "pass",
    }
    audit = {
        "status": "pass",
        "blocked_count": 0,
        "claims": [{
            "story_id": "s1",
            "status": "verified",
            "ledger_claim_ids": ["C002"],
            "sentence": "Paper Tiger هم از فیلم‌های جیمز گریه.",
        }],
        "system_issues": [],
    }
    result = _claim_audit_with_structure(audit, structure, ledger, [story])
    assert result["status"] == "blocked"
    assert any("current-week hook" in issue for issue in result["system_issues"])


def test_claim_audit_passes_when_current_hook_is_spoken():
    story = {"id": "s1", "canonical_title": "Paper Tiger trailer", "category": "upcoming_films"}
    ledger = [{
        "id": "C001",
        "story_id": "s1",
        "claim_role": "current_hook",
        "verification_status": "verified",
        "canonical_text": "The official trailer was released.",
    }]
    structure = {"blocking_issues": [], "major_issues": [], "status": "pass"}
    audit = {
        "status": "pass",
        "blocked_count": 0,
        "claims": [{
            "story_id": "s1",
            "status": "verified",
            "ledger_claim_ids": ["C001"],
            "sentence": "این هفته تریلر رسمی Paper Tiger منتشر شد.",
        }],
        "system_issues": [],
    }
    result = _claim_audit_with_structure(audit, structure, ledger, [story])
    assert result["status"] == "pass"
    assert result["blocked_count"] == 0
