from types import SimpleNamespace

from app.services.local_cli import _cli_error


def test_cli_error_drops_the_prompt_echo_and_names_usage_limits():
    echo = "<USER>" + "متن طولانی روایت " * 200 + "</USER>\n"
    result = SimpleNamespace(stderr="", stdout=echo + "ERROR: You've hit your usage limit. Try again at 12:01 AM.\nERROR: You've hit your usage limit. Try again at 12:01 AM.")
    message = _cli_error(result, "Codex")
    assert message.startswith("Codex hit its usage limit")
    assert "متن طولانی" not in message and len(message) < 500


def test_failed_extraction_does_not_invent_missing_hook_issues():
    import app.main as main
    audit = {"status": "blocked", "claims": [], "system_issues": ["Claim extraction failed: Codex hit its usage limit"]}
    ledger = [{"id": "C1", "story_id": "s1", "claim_role": "current_hook", "verification_status": "verified"}]
    out = main._claim_audit_with_structure(audit, {"blocking_issues": [], "major_issues": []}, ledger, [{"id": "s1"}])
    assert not any("not narrated" in issue for issue in out["system_issues"])
