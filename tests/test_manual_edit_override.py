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


def test_voice_status_flags_voice_from_unapproved_or_older_draft(client):
    import app.db as dbmod
    import app.main as main
    with dbmod.db() as conn:
        conn.execute("""INSERT INTO voice_segments(id,project_id,narration_id,segment_index,source_text,created_at,updated_at)
                        VALUES ('v1','p','n1',1,'x','x','x')""")
        segs = [dict(r) for r in conn.execute("SELECT * FROM voice_segments")]
        assert main._voice_draft_status(conn, "p", segs)["stale"]
        conn.execute("""INSERT INTO narrations(id,project_id,version_number,content,provider,model,created_at,approved)
                        VALUES ('n2','p',2,'y','manual','editor','x',1)""")
        status = main._voice_draft_status(conn, "p", segs)
        assert status["stale"] and "V2" in status["message"]
        conn.execute("UPDATE voice_segments SET narration_id='n2'")
        segs = [dict(r) for r in conn.execute("SELECT * FROM voice_segments")]
        assert not main._voice_draft_status(conn, "p", segs)["stale"]


def test_resolve_refuses_stale_voice_and_downloads_skip_old_runs(client):
    import app.db as dbmod
    with dbmod.db() as conn:
        conn.execute("""INSERT INTO voice_segments(id,project_id,narration_id,segment_index,source_text,created_at,updated_at)
                        VALUES ('v1','p','n1',1,'x','x','x')""")
        conn.execute("INSERT INTO research_runs(id,project_id,created_at) VALUES ('old','p','2000')")
        conn.execute("""INSERT INTO stories(id,project_id,run_id,canonical_title,decision,created_at,updated_at)
                        VALUES ('s_old','p','old','Old story','include','x','x')""")
        conn.execute("""INSERT INTO media_candidates(id,project_id,story_id,media_type,page_url,selected,created_at,updated_at)
                        VALUES ('m1','p','s_old','video','https://example.com/v',1,'x','x')""")
    r = client.post("/api/projects/p/resolve-plan/generate")
    assert r.status_code == 409 and "no longer approved" in r.json()["detail"]
    r = client.post("/api/projects/p/media/download-selected")
    assert r.status_code == 400 and "older research runs" in r.json()["detail"]


def test_timeline_links_outside_project_are_detected(tmp_path):
    from app.main import _timeline_links_outside
    root = tmp_path / "proj"; (root / "resolve" / "media").mkdir(parents=True)
    good = root / "resolve" / "media" / "a.mp4"; good.write_bytes(b"x")
    otio = root / "resolve" / "news_timeline.otio"
    otio.write_text('{"target_url": "%s"}' % good, encoding="utf-8")
    assert _timeline_links_outside(otio, root) is None
    otio.write_text('{"target_url": "/Users/someone/Old Folder/resolve/media/a.mp4"}', encoding="utf-8")
    moved = _timeline_links_outside(otio, root)
    assert moved and moved["count"] == 1 and "Old Folder" in moved["example_folder"]


def test_channel_name_is_saved_and_reaches_the_greeting_rule(client):
    r = client.patch("/api/projects/p", json={"channel_name": "Cine Notes"})
    assert r.status_code == 200
    assert client.get("/api/projects/p").json()["channel_name"] == "Cine Notes"
    from app.services.cinema_format import WRITER_SYSTEM, REVISION_SYSTEM, ENRICHMENT_REWRITE_SYSTEM
    for prompt in (WRITER_SYSTEM, REVISION_SYSTEM, ENRICHMENT_REWRITE_SYSTEM):
        assert "project.channel_name" in prompt and "Never borrow a channel name" in prompt
