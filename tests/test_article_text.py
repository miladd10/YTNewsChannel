from app.services.article_text import extract_article_text


PAGE = """<html><head>
<meta property="og:description" content="Studio X confirmed a limited run starting March 3 before streaming on March 17.">
<meta property="article:published_time" content="2031-02-20T10:00:00Z">
</head><body>
<nav><p>Home | News | Film | TV | Subscribe to our newsletter for the latest updates today</p></nav>
<article>
<p>Studio X on Tuesday released the first trailer for Moth Kingdom, the animated feature from director Ana Ruiz.</p>
<p>The film will open in a limited run of select theaters on March 3 and arrive on the platform two weeks later.</p>
<p>Short.</p>
<script>var p = "<p>not text</p>";</script>
<p>Ruiz previously directed the award-winning short Paper Lanterns, which screened at several festivals.</p>
</article>
<footer><p>© 2031 Example Media. All rights reserved. Privacy policy and terms of use apply here.</p></footer>
</body></html>"""


def test_extracts_description_and_body_without_chrome():
    result = extract_article_text(PAGE)
    assert result["description"].startswith("Studio X confirmed")
    assert result["published_time"] == "2031-02-20T10:00:00Z"
    assert "first trailer for Moth Kingdom" in result["excerpt"]
    assert "Paper Lanterns" in result["excerpt"]
    assert "newsletter" not in result["excerpt"]
    assert "rights reserved" not in result["excerpt"]
    assert "Short." not in result["excerpt"]


def test_excerpt_is_capped():
    page = "<p>" + ("A long sentence about the film release schedule. " * 200) + "</p>"
    assert len(extract_article_text(page, max_chars=500)["excerpt"]) <= 502


def test_bad_html_does_not_raise():
    assert extract_article_text("<p>unclosed <b>tags")["excerpt"] == ""


def test_excerpts_are_fetched_once_and_cached(tmp_path, monkeypatch):
    import json
    import app.db as dbmod
    import app.main as main
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db", raising=False)
    dbmod.init_db()
    with dbmod.db() as conn:
        conn.execute("INSERT INTO projects(id,name,created_at,updated_at) VALUES ('p','P','x','x')")
        conn.execute("INSERT INTO research_runs(id,project_id,created_at) VALUES ('r','p','x')")
        conn.execute("INSERT INTO research_articles(id,project_id,run_id,title,url,raw_json) VALUES ('a1','p','r','T','https://example.com/a','{}')")
    calls = []
    monkeypatch.setattr(main, "_fetch_one_excerpt", lambda article: calls.append(article["id"]) or
                        {"description": "D", "excerpt": "E body", "resolved_url": "https://example.com/a", "published_time": ""})
    story = {"articles": [{"id": "a1", "url": "https://example.com/a", "temporal_role": "current"}]}
    main._ensure_article_excerpts([story])
    assert story["articles"][0]["excerpt"] == "E body" and calls == ["a1"]
    with dbmod.db() as conn:
        raw = json.loads(conn.execute("SELECT raw_json FROM research_articles WHERE id='a1'").fetchone()[0])
    assert raw["excerpt"] == "E body" and raw["excerpt_fetched_at"]
    main._ensure_article_excerpts([story])
    assert calls == ["a1"]
