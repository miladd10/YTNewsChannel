from app.services.resolve_plan import build_edit_plan, crop_instruction, story_windows, voice_timeline


def test_crop_instruction_for_portrait_image():
    crop = crop_instruction(1080, 1920)
    assert crop["mode"] == "scale_full_frame_with_crop"
    assert crop["crop_axis"] == "vertical"
    assert crop["crop_fraction"] > 0


def test_voice_timeline_is_contiguous_and_story_aware():
    rows = [
        {
            "id": "v1", "segment_index": 1, "story_id": "a",
            "duration_seconds": 5.25, "audio_path": "audio/narration/1.mp3",
            "alignment_json": "{}",
        },
        {
            "id": "v2", "segment_index": 2, "story_id": "a",
            "duration_seconds": 3.75, "audio_path": "audio/narration/2.mp3",
            "alignment_json": "{}",
        },
        {
            "id": "v3", "segment_index": 3, "story_id": "b",
            "duration_seconds": 4.0, "audio_path": "audio/narration/3.mp3",
            "alignment_json": "{}",
        },
    ]
    voice, total = voice_timeline(rows)
    assert total == 13.0
    assert voice[1]["start"] == 5.25
    windows = story_windows(voice)
    assert windows[0]["story_id"] == "a"
    assert windows[0]["duration"] == 9.0
    assert windows[1]["story_id"] == "b"
    assert windows[1]["duration"] == 4.0


def test_edit_plan_keeps_video_at_normal_speed_and_fills_voice_window():
    project = {"id": "p", "name": "Test"}
    voice_rows = [
        {
            "id": "v1", "segment_index": 1, "story_id": "story",
            "duration_seconds": 14.0, "audio_path": "audio/narration/1.mp3",
            "alignment_json": "{}",
        },
    ]
    media = [
        {
            "id": "m1", "story_id": "story", "selected": 1,
            "download_status": "downloaded", "stored_path": "media/selected/story/video.mp4",
            "media_type": "video", "title": "Official Trailer", "source": "Studio",
            "page_url": "https://example.com/video", "duration": "2:00",
            "clip_start_sec": 5, "width": 3840, "height": 2160,
            "shared_source": 0,
        },
    ]
    plan = build_edit_plan(project, voice_rows, media, fps=30)
    clips = plan["visual_clips"]
    assert len(clips) == 2
    assert round(sum(x["timeline_duration"] for x in clips), 3) == 14.0
    assert all(x["playback_speed"] == 1.0 for x in clips)
    assert clips[0]["source_in"] != clips[1]["source_in"]
    assert plan["timeline"]["duration_seconds"] == 14.0
