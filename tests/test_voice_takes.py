def test_regenerating_other_take_keeps_approved_take(tmp_path, monkeypatch):
    import app.db as dbmod
    import app.services.voice_takes as vt
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db", raising=False)
    dbmod.init_db()
    root = tmp_path / "proj"; root.mkdir()
    with dbmod.db() as conn:
        conn.execute("INSERT INTO projects(id,name,root_path,created_at,updated_at) VALUES ('p','P',?,'x','x')", (str(root),))
        conn.execute("INSERT INTO voice_settings(project_id,voice_id,updated_at) VALUES ('p','voice','x')")
        conn.execute("INSERT INTO narrations(id,project_id,version_number,content,provider,model,created_at) VALUES ('n','p',1,'x','m','m','x')")
        conn.execute("""INSERT INTO voice_segments(id,project_id,narration_id,segment_index,source_text,performance_text,
                        take2_path,audio_path,selected_take,approval_status,audio_status,duration_seconds,created_at,updated_at)
                        VALUES ('s','p','n',1,'متن','متن','audio/narration/0001_narration_take2.mp3',
                                'audio/narration/0001_narration_take2.mp3',2,'approved','aligned',4.2,'x','x')""")
    monkeypatch.setattr(vt, "get_api_key", lambda provider: "k")
    monkeypatch.setattr(vt, "text_to_speech", lambda *a, **k: b"ID3fake")
    result = vt.generate_take("p", "s", 1, "now")
    assert result["kept_approved_take"] == 2
    with dbmod.db() as conn:
        row = dict(conn.execute("SELECT * FROM voice_segments WHERE id='s'").fetchone())
    assert row["approval_status"] == "approved" and row["selected_take"] == 2 and row["duration_seconds"] == 4.2
    assert row["take1_path"].endswith("take1.mp3")
    vt.generate_take("p", "s", 2, "now")  # regenerating the approved take resets approval
    with dbmod.db() as conn:
        assert conn.execute("SELECT approval_status FROM voice_segments WHERE id='s'").fetchone()[0] == "pending"
