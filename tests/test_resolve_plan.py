import app.services.resolve_plan as resolve_plan_module
import json

from app.services.resolve_plan import build_edit_plan, crop_instruction, story_windows, voice_timeline, write_resolve_package


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


def test_resolve_package_writes_importable_otio_with_source_in(tmp_path, monkeypatch):
    (tmp_path / "audio/narration").mkdir(parents=True)
    (tmp_path / "media/selected/story").mkdir(parents=True)
    (tmp_path / "audio/narration/1.mp3").write_bytes(b"fake-audio")
    (tmp_path / "media/selected/story/video.mp4").write_bytes(b"fake-video")

    def fake_stage_video(source, target, *, source_in, duration, fps):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"resolve-safe-video")

    def fake_stage_image(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"resolve-safe-image")

    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_video_cut", fake_stage_video)
    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_image", fake_stage_image)

    project = {"id": "p", "name": "Test News"}
    voice_rows = [
        {
            "id": "v1", "segment_index": 1, "story_id": "story",
            "duration_seconds": 7.0, "audio_path": "audio/narration/1.mp3",
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
    files = write_resolve_package(tmp_path, plan)

    assert (tmp_path / "resolve/news_timeline.otio").exists()
    assert (tmp_path / "resolve/media_timing.csv").exists()
    assert (tmp_path / "resolve/voice_timing.csv").exists()
    assert files["timeline_path"].endswith("news_timeline.otio")
    assert files["staged_unique_files"] == 2
    assert (tmp_path / "resolve/media").is_dir()
    assert len(list((tmp_path / "resolve/media").iterdir())) == 2

    otio = json.loads((tmp_path / "resolve/news_timeline.otio").read_text())
    assert otio["metadata"]["yt_news_studio"]["target_resolution"] == [3840, 2160]
    video_track = otio["tracks"]["children"][0]
    video_clip = next(x for x in video_track["children"] if x["OTIO_SCHEMA"] == "Clip.1")
    assert video_clip["source_range"]["start_time"]["value"] == 0
    assert video_clip["metadata"]["yt_news_studio"]["playback_speed"] == 1.0
    assert video_clip["media_reference"]["target_url"].startswith(str(tmp_path.resolve()))
    assert not video_clip["media_reference"]["target_url"].startswith("file://")
    assert "/resolve/media/" in video_clip["media_reference"]["target_url"]
    assert video_clip["media_reference"]["target_url"].endswith(".mp4")

    saved_plan = json.loads((tmp_path / "timing/resolve_plan.json").read_text())
    assert saved_plan["visual_clips"][0]["original_source_in"] == 5.0
    assert saved_plan["visual_clips"][0]["source_in"] == 0.0
    assert saved_plan["visual_clips"][0]["resolve_media_format"].startswith("H.264 MP4")

    audio_track = otio["tracks"]["children"][1]
    audio_clip = next(x for x in audio_track["children"] if x["OTIO_SCHEMA"] == "Clip.1")
    assert not audio_clip["media_reference"]["target_url"].startswith("file://")
    assert "/resolve/media/" in audio_clip["media_reference"]["target_url"]



def test_resolve_package_normalizes_stills_to_png(tmp_path, monkeypatch):
    (tmp_path / "audio/narration").mkdir(parents=True)
    (tmp_path / "media/selected/story").mkdir(parents=True)
    (tmp_path / "audio/narration/1.mp3").write_bytes(b"fake-audio")
    (tmp_path / "media/selected/story/poster.webp").write_bytes(b"fake-webp")

    def fake_stage_video(source, target, *, source_in, duration, fps):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"resolve-safe-video")

    def fake_stage_image(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"png-bytes")

    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_video_cut", fake_stage_video)
    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_image", fake_stage_image)

    project = {"id": "p", "name": "Still Test"}
    voice_rows = [{
        "id": "v1", "segment_index": 1, "story_id": "story",
        "duration_seconds": 5.0, "audio_path": "audio/narration/1.mp3",
        "alignment_json": "{}",
    }]
    media = [{
        "id": "m1", "story_id": "story", "selected": 1,
        "download_status": "downloaded", "stored_path": "media/selected/story/poster.webp",
        "media_type": "image", "title": "Poster", "source": "Studio",
        "page_url": "https://example.com/poster.webp", "duration": "",
        "width": 1200, "height": 1800, "shared_source": 0,
    }]

    plan = build_edit_plan(project, voice_rows, media, fps=30)
    write_resolve_package(tmp_path, plan)
    saved_plan = json.loads((tmp_path / "timing/resolve_plan.json").read_text())
    staged_path = saved_plan["visual_clips"][0]["stored_path"]
    assert staged_path.endswith(".png")
    assert (tmp_path / staged_path).exists()
    assert saved_plan["visual_clips"][0]["resolve_media_format"] == "PNG still"
