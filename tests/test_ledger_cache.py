import app.main as main


def _stories(url="https://a/1"):
    return [{"id": "s1", "news_hook": "trailer", "articles": [{"url": url}]}]


def test_second_build_for_same_stories_uses_the_cache(tmp_path, monkeypatch):
    project = {"id": "p", "root_path": str(tmp_path), "date_start": "2026-09-21", "date_end": "2026-09-28"}
    calls = []
    ledger = [{"id": "C1", "story_id": "s1", "claim_role": "current_hook", "verification_status": "verified"}]

    def build(stories, project, fresh, provider, model):
        calls.append(1)
        return ledger, provider, model

    monkeypatch.setattr(main, "build_claim_ledger", build)
    monkeypatch.setattr(main, "_ensure_article_excerpts", lambda stories: None)
    monkeypatch.setattr(main, "_fresh_sources_for", lambda project, stories: {})
    first = main._build_verified_claim_ledger(project, _stories(), "p", "m")[0]
    second = main._build_verified_claim_ledger(project, _stories(), "p", "m")[0]
    assert first == second == ledger and len(calls) == 1
    # different source articles -> rebuilt
    main._build_verified_claim_ledger(project, _stories("https://a/2"), "p", "m")
    assert len(calls) == 2
