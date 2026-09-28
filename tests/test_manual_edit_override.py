import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db", raising=False)
    dbmod.init_db()
    root = tmp_path / "proj"
    root.mkdir()
    with dbmod.db() as conn:
        conn.execute("INSERT INTO projects(id,name,root_path,created_at,updated_at) VALUES ('p','P',?,'x','x')", (str(root),))
        conn.execute("""INSERT INTO narrations(id,project_id,version_number,content,provider,model,created_at,
                        fact_check_status,claim_audit_status) VALUES ('n1','p',1,'متن اول','codex_local','default','x','pass','blocked')""")
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def test_manual_edit_creates_new_version_and_resets_claim_audit(client):
    r = client.post("/api/projects/p/narrations/n1/manual-edit", json={"content": "متن اصلاح‌شده", "note": "fix"})
    assert r.status_code == 200 and r.json()["version_number"] == 2
    import app.db as dbmod
    with dbmod.db() as conn:
        row = dict(conn.execute("SELECT * FROM narrations WHERE id=?", (r.json()["narration_id"],)).fetchone())
    assert row["provider"] == "manual" and row["parent_narration_id"] == "n1"
    assert row["fact_check_status"] == "pass" and row["claim_audit_status"] == "not_run"


def test_manual_edit_rejects_unchanged_text(client):
    assert client.post("/api/projects/p/narrations/n1/manual-edit", json={"content": "متن اول"}).status_code == 400


def test_approve_needs_override_and_reason_when_checks_fail(client):
    assert client.post("/api/projects/p/narrations/n1/approve").status_code == 400
    short = client.post("/api/projects/p/narrations/n1/approve", json={"override": True, "reason": "ok"})
    assert short.status_code == 400
    ok = client.post("/api/projects/p/narrations/n1/approve", json={"override": True, "reason": "Checked every figure against the sources myself."})
    assert ok.status_code == 200 and ok.json()["override"] is True
    assert "Checked every figure" in ok.json()["approval_note"]
    import app.db as dbmod
    with dbmod.db() as conn:
        assert conn.execute("SELECT approved FROM narrations WHERE id='n1'").fetchone()[0] == 1
