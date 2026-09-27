from app.main import _chunk_story_durations


def test_media_search_chunks_follow_approved_narration_duration():
    chunks = _chunk_story_durations(
        [
            ("story-a", 20.0),
            ("story-b", 25.0),
            ("story-c", 20.0),
            ("story-d", 75.0),
            ("story-e", 10.0),
        ],
        60.0,
    )
    assert chunks == [
        [("story-a", 20.0), ("story-b", 25.0)],
        [("story-c", 20.0)],
        [("story-d", 75.0)],
        [("story-e", 10.0)],
    ]


def test_smaller_broll_chunk_setting_creates_more_requests():
    stories = [
        ("a", 20.0),
        ("b", 20.0),
        ("c", 20.0),
        ("d", 20.0),
    ]
    one_minute = _chunk_story_durations(stories, 60.0)
    half_minute = _chunk_story_durations(stories, 30.0)
    assert len(one_minute) == 2
    assert len(half_minute) == 4


def test_long_story_is_one_chunk_instead_of_being_split_mid_story():
    chunks = _chunk_story_durations(
        [("long-story", 92.0), ("next-story", 18.0)],
        60.0,
    )
    assert chunks[0] == [("long-story", 92.0)]
    assert chunks[1] == [("next-story", 18.0)]
