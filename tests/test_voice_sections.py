from app.services.voice_pipeline import extract_narration_segments


def test_intro_and_outro_are_reserved_from_story_ids():
    content = """## مقدمه

Intro text.

## روندها

<!-- STORY:story-1 -->

Story one text.

## پایان

Outro text.
"""
    segments = extract_narration_segments(content)
    assert len(segments) == 3
    assert segments[0]["story_id"] == ""
    assert segments[0]["source_text"] == "Intro text."
    assert segments[1]["story_id"] == "story-1"
    assert segments[1]["source_text"] == "Story one text."
    assert segments[2]["story_id"] == ""
    assert segments[2]["source_text"] == "Outro text."


def test_english_outro_heading_resets_previous_story():
    content = """<!-- STORY:story-1 -->

Story text.

## Outro

Closing text.
"""
    segments = extract_narration_segments(content)
    assert [segment["story_id"] for segment in segments] == ["story-1", ""]
