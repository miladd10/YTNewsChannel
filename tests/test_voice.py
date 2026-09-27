from app.services.voice_pipeline import (
    extract_narration_segments,
    performance_text_is_safe,
)


def test_voice_segments_keep_story_ownership_and_skip_headings():
    text = """# Trends

Intro line.

<!-- STORY:ray-gunn -->
Ray Gunn has its first trailer.

More details follow.

<!-- STORY:resident-evil -->
Resident Evil opened strongly.
"""
    segments = extract_narration_segments(text)
    assert [x["story_id"] for x in segments] == ["", "ray-gunn", "resident-evil"]
    assert segments[0]["source_text"] == "Intro line."
    assert "Ray Gunn has its first trailer." in segments[1]["source_text"]
    assert "# Trends" not in " ".join(x["source_text"] for x in segments)


def test_performance_markup_may_not_change_spoken_words():
    source = "Ray Gunn has its first trailer."
    assert performance_text_is_safe(source, "[thoughtful] Ray Gunn... has its FIRST trailer. [short pause]")
    assert not performance_text_is_safe(source, "[thoughtful] Ray Gunn finally has its first trailer.")


def test_same_story_paragraphs_merge_for_voice_continuity():
    text = """<!-- STORY:abc -->
First paragraph.

Second paragraph.
"""
    segments = extract_narration_segments(text)
    assert len(segments) == 1
    assert "First paragraph." in segments[0]["source_text"]
    assert "Second paragraph." in segments[0]["source_text"]
