from app.main import _request_is_allowed


def test_same_origin_browser_post_is_allowed():
    assert _request_is_allowed("POST", {"host": "127.0.0.1:8787", "origin": "http://127.0.0.1:8787",
                                        "sec-fetch-site": "same-origin"})[0]


def test_cross_site_browser_post_is_blocked():
    assert not _request_is_allowed("POST", {"host": "127.0.0.1:8787", "origin": "https://evil.example"})[0]
    assert not _request_is_allowed("POST", {"host": "127.0.0.1:8787", "origin": "null"})[0]
    assert not _request_is_allowed("POST", {"host": "127.0.0.1:8787", "sec-fetch-site": "cross-site"})[0]
    assert not _request_is_allowed("POST", {"host": "127.0.0.1:8787", "origin": "http://127.0.0.1:9999"})[0]


def test_non_local_host_is_blocked_even_for_reads():
    assert not _request_is_allowed("GET", {"host": "attacker.example:8787"})[0]


def test_reads_and_non_browser_clients_are_allowed():
    assert _request_is_allowed("GET", {"host": "localhost:8787", "origin": "https://evil.example"})[0]
    assert _request_is_allowed("POST", {"host": "localhost:8787"})[0]


def test_middleware_blocks_cross_site_post_end_to_end():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.post("/api/pronunciations", json={"text": ""}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_meta_endpoint_works():
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).get("/api/meta")
    assert r.status_code == 200 and "Intro" in r.json()["cinema_weekly_sections"]
