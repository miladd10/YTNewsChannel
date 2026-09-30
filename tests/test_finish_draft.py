"""The shared post-writing pipeline: polish -> verify -> bounded repair."""
import pytest

import app.main as main

DRAFT = "<!-- STORY:s1 -->\n" + " ".join(["کلمه"] * 200) + "."


@pytest.fixture()
def fakes(tmp_path, monkeypatch):
    calls = {"fetch": 0, "fact": 0, "audit": 0, "polish": 0, "repair": 0}
    state = {"polish": lambda text: text, "repair": lambda text: text + " اصلاح.", "fact_ok": lambda text: True}

    def fetch(stories, start, end, per_query_limit=5):
        calls["fetch"] += 1
        return {str(s["id"]): [{"url": "u", "snippet": "x"}] for s in stories}

    def fact(project, stories, text, p, m, fresh_sources=None, claim_ledger=None):
        calls["fact"] += 1
        assert fresh_sources is not None
        ok = state["fact_ok"](text)
        return text, {"status": "pass" if ok else "needs_human_check", "issue_count": 0 if ok else 1,
                      "issues": [] if ok else [{"story_id": "s1", "problem": "x"}]}, p, m

    def audit(text, ledger, p, m):
        calls["audit"] += 1
        return {"status": "pass", "blocked_count": 0, "claims": [], "system_issues": []}, p, m

    def gen(provider, model, system, user):
        if system == main.NARRATION_FLUENCY_POLISH_SYSTEM:
            calls["polish"] += 1
            return state["polish"](DRAFT), provider, model
        calls["repair"] += 1
        text = user.split("<draft_to_repair>\n", 1)[1].split("\n</draft_to_repair>", 1)[0]
        return state["repair"](text), provider, model

    monkeypatch.setattr(main, "fetch_narration_fact_check_sources", fetch)
    monkeypatch.setattr(main, "_run_narration_fact_check", fact)
    monkeypatch.setattr(main, "audit_narration_claims", audit)
    monkeypatch.setattr(main, "generate_text", gen)
    monkeypatch.setattr(main, "masked_status", lambda: {})
    monkeypatch.setattr(main, "_ensure_article_excerpts", lambda stories: None)
    monkeypatch.setattr(main, "narration_structure_audit", lambda text, stories, project: {"status": "pass"})
    monkeypatch.setattr(main, "build_writer_style_packet", lambda *a, **k: "")
    project = {"root_path": str(tmp_path), "date_start": "2026-09-01", "date_end": "2026-09-08",
               "target_minutes": 1, "language": "fa"}
    return calls, state, project


def _finish(project, text=DRAFT):
    return main._finish_draft(project, [{"id": "s1"}], text, [], None, "codex_local", "default", "", [])


def test_clean_draft_needs_three_ai_calls_and_one_search(fakes):
    calls, _, project = fakes
    result = _finish(project)
    assert result["repair_count"] == 0
    assert calls == {"fetch": 1, "fact": 1, "audit": 1, "polish": 1, "repair": 0}


def test_fresh_sources_are_cached_between_passes(fakes):
    calls, _, project = fakes
    _finish(project)
    _finish(project)
    assert calls["fetch"] == 1


def test_repair_that_fixes_the_issue_is_kept(fakes):
    calls, state, project = fakes
    state["fact_ok"] = lambda text: "اصلاح" in text
    result = _finish(project)
    assert result["repair_count"] == 1 and "اصلاح" in result["text"]
    assert result["fact_check"]["status"] == "pass"


def test_repair_without_progress_is_discarded_and_loop_stops(fakes):
    calls, state, project = fakes
    state["fact_ok"] = lambda text: False
    result = _finish(project)
    assert result["repair_count"] == 0 and result["text"] == DRAFT
    assert calls["repair"] == 1  # no second, pointless attempt
    assert "did not reduce" in result["repair_error"]


def test_polish_that_cuts_the_script_is_rejected(fakes):
    _, state, project = fakes
    state["polish"] = lambda text: "<!-- STORY:s1 -->\nکوتاه."
    result = _finish(project)
    assert result["text"] == DRAFT and result["fluency_polished"] is False
