import json
import pytest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db", raising=False)
    dbmod.init_db()
    root = tmp_path / "proj"; root.mkdir()
    with dbmod.db() as conn:
        conn.execute("INSERT INTO projects(id,name,root_path,created_at,updated_at) VALUES ('p','P',?,'x','x')", (str(root),))
        conn.execute("""INSERT INTO narrations(id,project_id,version_number,content,provider,model,created_at)
                        VALUES ('n1','p',1,'متن','codex_local','default','x')""")
        conn.execute("""INSERT INTO narrations(id,project_id,version_number,content,provider,model,created_at,parent_narration_id)
                        VALUES ('n2','p',2,'متن دستی','manual','editor','x','n1')""")
        claim = {"id": "C001", "story_id": "s1", "claim_type": "cast", "canonical_text": "Ana Ruiz stars.",
                 "verification_status": "verified", "source_urls": ["u"]}
        conn.execute("""INSERT INTO claim_ledger(id,project_id,narration_id,story_id,claim_type,canonical_text,
                        verification_status,attribution_required,source_urls_json,data_json,created_at)
                        VALUES ('r1','p','n1','s1','cast','Ana Ruiz stars.','verified',0,'[]',?,'x')""", (json.dumps(claim),))
    return dbmod


def test_reusable_ledger_walks_to_parent_and_respects_selected_stories(env):
    import app.main as main
    with env.db() as conn:
        assert main._reusable_ledger(conn, "n2", [{"id": "s1"}])[0]["id"] == "C001"
        assert main._reusable_ledger(conn, "n2", [{"id": "other"}]) is None


def test_claim_audit_uses_the_drafts_ledger_instead_of_rebuilding(env, monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "selected_story_packet", lambda conn, pid: [{"id": "s1"}])
    def no_rebuild(*a, **k):
        raise AssertionError("ledger should have been reused")
    monkeypatch.setattr(main, "_build_verified_claim_ledger", no_rebuild)
    seen = {}
    def fake_audit(text, ledger, provider, model):
        seen["ids"] = [c["id"] for c in ledger]
        return {"status": "pass", "claim_count": 1, "verified_count": 1, "attributed_count": 0,
                "blocked_count": 0, "claims": [], "system_issues": []}, provider, model
    monkeypatch.setattr(main, "audit_narration_claims", fake_audit)
    from fastapi.testclient import TestClient
    r = TestClient(main.app).post("/api/projects/p/narrations/n2/claim-audit", json={})
    assert r.status_code == 200 and r.json()["ledger_reused"] is True and seen["ids"] == ["C001"]
