from app.services.media import _youtube_search_queries, story_allows_interview_or_podcast, video_is_usable_broll


def normal_story():
    return {
        "canonical_title": "Resident Evil film breaks franchise box office records",
        "summary": "The new film posted a major opening weekend.",
        "category": "trend",
        "articles": [{"title": "Resident Evil breaks box office records"}],
    }


def test_official_studio_trailer_is_accepted():
    item = {
        "title": "Resident Evil — Official Trailer",
        "channel": "Sony Pictures Entertainment",
        "channel_is_verified": True,
        "height": 2160,
    }
    assert video_is_usable_broll(item, normal_story())


def test_news_package_is_rejected():
    item = {
        "title": "Resident Evil breaks box office record",
        "channel": "ABC News",
        "channel_is_verified": True,
        "height": 1080,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_commentary_and_reaction_are_rejected_even_if_verified():
    item = {
        "title": "Resident Evil Official Trailer Breakdown & Reaction",
        "channel": "Movie Commentary",
        "channel_is_verified": True,
        "height": 2160,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_unverified_reupload_labeled_official_is_rejected():
    item = {
        "title": "Resident Evil Official Trailer",
        "channel": "Random Uploads",
        "channel_is_verified": False,
        "height": 1080,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_interview_is_rejected_for_unrelated_story():
    item = {
        "title": "Actor Full Interview About Resident Evil",
        "channel": "Variety",
        "channel_is_verified": True,
        "height": 1080,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_original_interview_allowed_when_story_is_about_interview():
    story = {
        "canonical_title": "Brad Pitt reveals new details in Variety interview",
        "summary": "The comments were made during a new interview.",
        "category": "celebrities",
        "articles": [{"title": "Brad Pitt discusses the film in new interview"}],
    }
    item = {
        "title": "Brad Pitt Full Interview",
        "channel": "Variety",
        "channel_is_verified": True,
        "height": 1080,
    }
    assert story_allows_interview_or_podcast(story)
    assert video_is_usable_broll(item, story)


def test_interview_queries_only_added_for_interview_story():
    normal_queries = _youtube_search_queries(normal_story())
    assert not any("full interview" in q.lower() or "podcast interview" in q.lower() for q in normal_queries)

    story = {
        "canonical_title": "Actor discusses sequel on Film Talk podcast",
        "summary": "The actor made the comments during the podcast.",
        "category": "celebrities",
        "articles": [],
    }
    queries = _youtube_search_queries(story)
    assert any("podcast interview" in q.lower() for q in queries)


def test_trailer_aggregator_reupload_is_rejected():
    item = {
        "title": "Resident Evil Official Trailer",
        "channel": "IGN",
        "channel_is_verified": True,
        "height": 2160,
    }
    assert not video_is_usable_broll(item, normal_story())


def test_same_studio_but_wrong_movie_is_rejected():
    story = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first trailer for Ray Gunn.",
        "category": "upcoming_films",
        "articles": [{"title": "Ray Gunn gets first trailer"}],
    }
    item = {
        "title": "Ladies First | Official Trailer | Netflix",
        "channel": "Netflix",
        "channel_is_verified": True,
        "height": 1080,
        "_search_query": "Ray Gunn official trailer",
    }
    assert not video_is_usable_broll(item, story)


def test_exact_movie_from_original_studio_is_accepted():
    story = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first trailer for Ray Gunn.",
        "category": "upcoming_films",
        "articles": [{"title": "Ray Gunn gets first trailer"}],
    }
    item = {
        "title": "Ray Gunn | Official Trailer | Netflix",
        "channel": "Netflix",
        "channel_is_verified": True,
        "height": 1080,
        "_search_query": "Ray Gunn official trailer",
    }
    assert video_is_usable_broll(item, story)


def test_known_reupload_channel_is_rejected_even_when_title_matches():
    story = {
        "canonical_title": "‘Ray Gunn’ Trailer: Netflix Sets Theatrical Release With First Look",
        "summary": "Netflix released the first trailer for Ray Gunn.",
        "category": "upcoming_films",
        "articles": [],
    }
    item = {
        "title": "RAY GUNN Official Trailer (2026)",
        "channel": "KinoCheck.com",
        "channel_is_verified": True,
        "height": 2160,
        "_search_query": "Ray Gunn official trailer",
    }
    assert not video_is_usable_broll(item, story)


def test_corporate_story_rejects_unrelated_movie_trailer_from_same_studio():
    story = {
        "canonical_title": "Paramount reaches deal with California, other states over Warner merger",
        "summary": "A legal settlement changes the path of the Paramount-Warner merger.",
        "category": "industry",
        "articles": [{"title": "States settle Paramount Warner merger lawsuit"}],
    }
    item = {
        "title": "Dune: Part Three | Official Trailer",
        "channel": "Warner Bros.",
        "channel_is_verified": True,
        "height": 2160,
        "_search_query": "Warner Bros official trailer",
    }
    assert not video_is_usable_broll(item, story)


def test_corporate_story_accepts_company_logo_or_lot_broll():
    story = {
        "canonical_title": "Paramount reaches deal with California, other states over Warner merger",
        "summary": "A legal settlement changes the path of the Paramount-Warner merger.",
        "category": "industry",
        "articles": [{"title": "States settle Paramount Warner merger lawsuit"}],
    }
    item = {
        "title": "Welcome to the Warner Bros. Studio Lot",
        "channel": "Warner Bros.",
        "channel_is_verified": True,
        "height": 2160,
        "_search_query": "Warner Bros official studio lot",
    }
    assert video_is_usable_broll(item, story)
