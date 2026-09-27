from app.services.research import cluster_articles, normalize_title

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
