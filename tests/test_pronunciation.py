from app.services.voice_pipeline import apply_pronunciations, parse_pronunciation_lines, performance_text_is_safe


def test_pronunciation_entries_may_only_add_vowel_marks():
    entries, rejected = parse_pronunciation_lines("کار سار = کارِ سار\nfoo = bar\n# comment\nنام = نام")
    assert entries == [{"written": "کار سار", "spoken": "کارِ سار"}]
    assert len(rejected) == 2


def test_pronunciations_apply_to_whole_words_and_keep_voice_text_safe():
    entries, _ = parse_pronunciation_lines("کار سار = کارِ سار")
    text = "فیلم تازهٔ کار سار رسید. کار سارها چیز دیگه‌ای‌ان."
    out = apply_pronunciations(text, entries)
    assert "فیلم تازهٔ کارِ سار رسید" in out
    assert "کار سارها" in out
    assert performance_text_is_safe(text, out)


def test_voice_safety_still_rejects_changed_words():
    assert not performance_text_is_safe("کار سار رسید", "کار سام رسید")


def test_pronunciation_api_roundtrip(tmp_path, monkeypatch):
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db", raising=False)
    from fastapi.testclient import TestClient
    from app.main import app
    dbmod.init_db()
    client = TestClient(app)
    r = client.put("/api/pronunciations", json={"language": "Persian", "text": "کار سار = کارِ سار\nbad line"})
    assert r.status_code == 200 and len(r.json()["entries"]) == 1 and len(r.json()["rejected"]) == 1
    assert client.get("/api/pronunciations", params={"language": "persian"}).json()["entries"][0]["spoken"] == "کارِ سار"
