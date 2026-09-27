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
