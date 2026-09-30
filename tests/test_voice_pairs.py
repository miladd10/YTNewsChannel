import json

import pytest

from app.services.cinema_format import voice_pair_passages, voice_pairs_packet

EPISODE = " ".join(
    f"فیلم شماره {i} این آخر هفته {i} میلیون دلار فروخت یعنی از قبلی جلو زد و کارگردانش گفتش که راضیه."
    for i in range(60)
)


def test_passages_are_verbatim_and_spread_across_episodes():
    rows = [{"content": EPISODE}, {"content": EPISODE.replace("فیلم", "سریال")}]
    passages = voice_pair_passages(rows, per_episode=4)
    assert len(passages) == 8
    assert all(p in EPISODE or p in EPISODE.replace("فیلم", "سریال") for p in passages)


def test_packet_pairs_english_with_host_speech():
    text = voice_pairs_packet([{"english": "Film X grossed $5 million.", "persian": "فیلم ۵ میلیون فروخت."}])
    assert "EN: Film X grossed $5 million." in text and "HOST: فیلم ۵ میلیون فروخت." in text
    assert voice_pairs_packet([]) == ""


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import app.db as dbmod
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db", raising=False)
    dbmod.init_db()
    import app.main as main
    rows = [{"name": "ep 2026-01-01", "content": EPISODE, "enabled": 1}]
    monkeypatch.setattr(main, "writer_style_rows_for_window", lambda styles, *a, **k: rows)
    return main


def test_pairs_are_built_once_then_cached(env, monkeypatch):
    calls = []

    def fake(provider, model, system, user):
        calls.append(system)
        count = user.count("\n\n") + 1
        return json.dumps({"english": [f"News sentence {i}." for i in range(count)]}), provider, model

    monkeypatch.setattr(env, "generate_text", fake)
    project = {"date_start": "2026-02-01", "content_type": "weekly_news"}
    first = env._ensure_voice_pairs([], project, "p", "m")
    second = env._ensure_voice_pairs([], project, "p", "m")
    assert "EN: News sentence 0." in first and first == second
    assert len(calls) == 1


def test_pair_failure_is_silent(env, monkeypatch):
    def broken(*a):
        raise RuntimeError("Codex hit its usage limit")
    monkeypatch.setattr(env, "generate_text", broken)
    assert env._ensure_voice_pairs([], {"date_start": "2026-02-01"}, "p", "m") == ""
