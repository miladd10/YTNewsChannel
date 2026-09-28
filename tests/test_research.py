from app.services.research import _fact_check_queries, _fact_check_trust_tier, cluster_articles, normalize_title

def test_normalize_title_removes_noise():
    assert "movie" in normalize_title("The Movie: First Trailer - Variety")
    assert "variety" not in normalize_title("The Movie: First Trailer - Variety")

def test_cluster_articles_groups_similar_headlines():
    articles=[
        {"id":"1","title":"Resident Evil opens to huge box office weekend","url":"u1","source":"A","published_at":"2026-01-01","category":"trend","snippet":"one","query_key":"q"},
        {"id":"2","title":"Resident Evil scores huge opening weekend at box office","url":"u2","source":"B","published_at":"2026-01-01","category":"trend","snippet":"two","query_key":"q"},
        {"id":"3","title":"Netflix renews a separate TV series","url":"u3","source":"C","published_at":"2026-01-01","category":"tv_series","snippet":"three","query_key":"q"},
    ]
    stories=cluster_articles(articles)
    assert len(stories)==2
    assert max(s["source_count"] for s in stories)>=2



def test_fact_check_queries_treat_box_office_as_volatile():
    story = {
        "canonical_title": "Resident Evil",
        "search_subject": "Resident Evil",
        "category": "box_office",
        "summary": "Worldwide opening weekend",
        "news_hook": "Second weekend box office",
    }
    queries = _fact_check_queries(story, "2026-09-21", "2026-09-28")
    assert any("latest box office worldwide total" in query for query in queries)
    assert any("second weekend cumulative total" in query for query in queries)
    assert all("after:2026-09-20" in query for query in queries)
    assert all("before:2026-09-28" in query for query in queries)


def test_fact_check_prefers_recognized_box_office_and_official_sources():
    assert _fact_check_trust_tier("https://www.boxofficemojo.com/title/tt123") == "preferred"
    assert _fact_check_trust_tier("https://www.sonypictures.com/movies/residentevil") == "preferred"
    assert _fact_check_trust_tier("https://random-movie-blog.example/post") == "supplemental"
