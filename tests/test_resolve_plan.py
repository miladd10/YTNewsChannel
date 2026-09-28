import app.services.resolve_plan as resolve_plan_module
import json

from app.services.resolve_plan import _assign_transitions, _clamp_video_source_in, _visual_slices, build_edit_plan, crop_instruction, story_windows, voice_timeline, write_resolve_package


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
    assert len(clips) == 3
    assert round(sum(x["timeline_duration"] for x in clips), 3) == 14.0
    assert all(x["playback_speed"] == 1.0 for x in clips)
    assert all(x["timeline_duration"] <= 5.5 for x in clips)
    assert len({x["source_in"] for x in clips}) == len(clips)
    assert plan["timeline"]["duration_seconds"] == 14.0


def test_resolve_package_writes_importable_otio_with_source_in(tmp_path, monkeypatch):
    (tmp_path / "audio/narration").mkdir(parents=True)
    (tmp_path / "media/selected/story").mkdir(parents=True)
    (tmp_path / "audio/narration/1.mp3").write_bytes(b"fake-audio")
    (tmp_path / "media/selected/story/video.mp4").write_bytes(b"fake-video")

    def fake_stage_video(source, target, *, source_in, duration, fps, source_duration=None):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"resolve-safe-video")
        return {
            "source_duration": source_duration,
            "requested_source_in": source_in,
            "adjusted_source_in": source_in,
            "frame_count": int(round(duration * fps)),
            "staged_duration": duration,
            "measured_duration": duration,
        }

    def fake_stage_image_hold(source, target, *, duration, fps):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"resolve-safe-image-hold")
        return {
            "frame_count": int(round(duration * fps)),
            "staged_duration": duration,
            "measured_duration": duration,
        }

    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_video_cut", fake_stage_video)
    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_image_hold", fake_stage_image_hold)
    monkeypatch.setattr(resolve_plan_module, "_probe_media_duration", lambda path: 120.0)

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
    assert files["staged_unique_files"] == 3
    assert (tmp_path / "resolve/media").is_dir()
    assert len(list((tmp_path / "resolve/media").iterdir())) == 3

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



def test_resolve_package_renders_stills_as_exact_duration_mp4_holds(tmp_path, monkeypatch):
    (tmp_path / "audio/narration").mkdir(parents=True)
    (tmp_path / "media/selected/story").mkdir(parents=True)
    (tmp_path / "audio/narration/1.mp3").write_bytes(b"fake-audio")
    (tmp_path / "media/selected/story/poster.webp").write_bytes(b"fake-webp")

    def fake_stage_video(source, target, *, source_in, duration, fps, source_duration=None):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"resolve-safe-video")
        return {
            "source_duration": source_duration,
            "requested_source_in": source_in,
            "adjusted_source_in": source_in,
            "frame_count": int(round(duration * fps)),
            "staged_duration": duration,
            "measured_duration": duration,
        }

    def fake_stage_image_hold(source, target, *, duration, fps):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"still-hold-video")
        return {
            "frame_count": int(round(duration * fps)),
            "staged_duration": duration,
            "measured_duration": duration,
        }

    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_video_cut", fake_stage_video)
    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_image_hold", fake_stage_image_hold)

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
    assert staged_path.endswith(".mp4")
    assert (tmp_path / staged_path).exists()
    clip = saved_plan["visual_clips"][0]
    assert clip["source_in"] == 0.0
    assert clip["source_out"] == 3.0
    assert clip["source_media_duration"] == 3.0
    assert clip["resolve_frame_count"] == 90
    assert clip["resolve_media_format"].startswith("H.264 MP4 still hold")



def test_resolve_source_in_is_clamped_to_real_download_duration():
    assert _clamp_video_source_in(90.0, 7.0, 30.0) == 23.0
    assert _clamp_video_source_in(5.0, 7.0, 30.0) == 5.0
    assert _clamp_video_source_in(15.0, 40.0, 30.0) == 0.0


def test_resolve_stage_uses_actual_download_duration_not_candidate_metadata(tmp_path, monkeypatch):
    (tmp_path / "audio/narration").mkdir(parents=True)
    (tmp_path / "media/selected/story").mkdir(parents=True)
    (tmp_path / "audio/narration/1.mp3").write_bytes(b"fake-audio")
    source = tmp_path / "media/selected/story/video.mp4"
    source.write_bytes(b"fake-video")

    captured = []

    def fake_probe(path):
        if path == source:
            return 12.0
        return 7.0

    def fake_stage_video(source_path, target, *, source_in, duration, fps, source_duration=None):
        captured.append({
            "source_in": source_in,
            "source_duration": source_duration,
            "duration": duration,
        })
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"resolve-safe-video")
        return {
            "source_duration": source_duration,
            "requested_source_in": source_in,
            "adjusted_source_in": source_in,
            "frame_count": int(round(duration * fps)),
            "staged_duration": duration,
            "measured_duration": duration,
        }

    monkeypatch.setattr(resolve_plan_module, "_probe_media_duration", fake_probe)
    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_video_cut", fake_stage_video)

    project = {"id": "p", "name": "Clamp Test"}
    voice_rows = [{
        "id": "v1", "segment_index": 1, "story_id": "story",
        "duration_seconds": 7.0, "audio_path": "audio/narration/1.mp3",
        "alignment_json": "{}",
    }]
    media = [{
        "id": "m1", "story_id": "story", "selected": 1,
        "download_status": "downloaded", "stored_path": "media/selected/story/video.mp4",
        "media_type": "video", "title": "Official Trailer", "source": "Studio",
        "page_url": "https://example.com/video", "duration": "2:00",
        "clip_start_sec": 90, "width": 1920, "height": 1080,
        "shared_source": 0,
    }]

    plan = build_edit_plan(project, voice_rows, media, fps=30)
    write_resolve_package(tmp_path, plan)
    saved = json.loads((tmp_path / "timing/resolve_plan.json").read_text())
    clip = saved["visual_clips"][0]

    # Discovery metadata says 2:00, but the actual downloaded file is only 12s.
    # A 7s cut must therefore start no later than 5s.
    assert len(captured) == 2
    assert all(call["source_duration"] == 12.0 for call in captured)
    assert all(call["source_in"] >= 0.0 for call in captured)
    assert all(call["source_in"] + call["duration"] <= 12.000001 for call in captured)
    assert clip["adjusted_source_in"] <= 12.0 - clip["timeline_duration"] + 0.000001
    assert clip["source_in"] >= 0.0
    assert clip["resolve_frame_count"] == int(round(clip["timeline_duration"] * 30))



def test_image_only_story_uses_each_still_once_for_three_seconds_max():
    window = {"story_id": "story", "start": 0.0, "end": 12.0, "duration": 12.0}
    images = [
        {"id": "i1", "media_type": "image", "title": "A", "stored_path": "a.jpg", "width": 1920, "height": 1080},
        {"id": "i2", "media_type": "image", "title": "B", "stored_path": "b.jpg", "width": 1920, "height": 1080},
        {"id": "i3", "media_type": "image", "title": "C", "stored_path": "c.jpg", "width": 1920, "height": 1080},
    ]
    clips = _visual_slices(window, images)
    assert [round(x["timeline_duration"], 1) for x in clips] == [3.0, 3.0, 3.0]
    assert [x["candidate_id"] for x in clips] == ["i1", "i2", "i3"]
    assert round(sum(x["timeline_duration"] for x in clips), 1) == 9.0


def test_same_trailer_scene_changes_use_hard_cuts_but_image_change_dissolves():
    video_a = {
        "story_id": "s", "candidate_id": "v", "media_type": "video",
        "timeline_start": 0.0, "timeline_end": 4.0, "timeline_duration": 4.0,
    }
    video_b = {
        "story_id": "s", "candidate_id": "v", "media_type": "video",
        "timeline_start": 4.0, "timeline_end": 8.0, "timeline_duration": 4.0,
    }
    image = {
        "story_id": "s", "candidate_id": "i", "media_type": "image",
        "timeline_start": 8.0, "timeline_end": 13.0, "timeline_duration": 5.0,
    }
    clips = [video_a, video_b, image]
    _assign_transitions(clips, 30)
    assert clips[0]["transition_out_frames"] == 0
    assert clips[1]["transition_in_frames"] == 0
    assert clips[1]["transition_out_frames"] > 0
    assert clips[2]["transition_in_frames"] > 0


def test_otio_contains_dissolve_with_real_still_handles(tmp_path, monkeypatch):
    (tmp_path / "audio/narration").mkdir(parents=True)
    (tmp_path / "media/selected/story").mkdir(parents=True)
    (tmp_path / "audio/narration/1.mp3").write_bytes(b"audio")
    (tmp_path / "media/selected/story/a.jpg").write_bytes(b"a")
    (tmp_path / "media/selected/story/b.jpg").write_bytes(b"b")

    def fake_stage_image_hold(source, target, *, duration, fps):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"hold")
        return {
            "frame_count": int(round(duration * fps)),
            "staged_duration": duration,
            "measured_duration": duration,
        }

    monkeypatch.setattr(resolve_plan_module, "_stage_resolve_image_hold", fake_stage_image_hold)

    project = {"id": "p", "name": "Transitions"}
    voice_rows = [{
        "id": "v1", "segment_index": 1, "story_id": "story",
        "duration_seconds": 10.0, "audio_path": "audio/narration/1.mp3",
        "alignment_json": "{}",
    }]
    media = [
        {"id": "i1", "story_id": "story", "selected": 1, "download_status": "downloaded",
         "stored_path": "media/selected/story/a.jpg", "media_type": "image",
         "title": "A", "source": "Studio", "page_url": "https://x/a", "width": 1920, "height": 1080},
        {"id": "i2", "story_id": "story", "selected": 1, "download_status": "downloaded",
         "stored_path": "media/selected/story/b.jpg", "media_type": "image",
         "title": "B", "source": "Studio", "page_url": "https://x/b", "width": 1920, "height": 1080},
    ]

    plan = build_edit_plan(project, voice_rows, media, fps=30)
    write_resolve_package(tmp_path, plan)
    otio = json.loads((tmp_path / "resolve/news_timeline.otio").read_text())
    track = otio["tracks"]["children"][0]
    transitions = [x for x in track["children"] if x["OTIO_SCHEMA"] == "Transition.1"]
    assert len(transitions) == 1
    assert transitions[0]["transition_type"] == "SMPTE_Dissolve"

    saved = json.loads((tmp_path / "timing/resolve_plan.json").read_text())
    left, right = saved["visual_clips"]
    assert left["source_media_duration"] > left["timeline_duration"]
    assert right["source_in"] > 0



def test_one_image_is_never_repeated_to_fill_story():
    window = {"story_id": "story", "start": 0.0, "end": 11.0, "duration": 11.0}
    images = [
        {"id": "only", "media_type": "image", "title": "Only", "stored_path": "only.jpg", "width": 1920, "height": 1080},
    ]
    clips = _visual_slices(window, images)
    assert len(clips) == 1
    assert clips[0]["candidate_id"] == "only"
    assert clips[0]["timeline_duration"] == 3.0


def test_logo_or_fanfare_video_is_used_only_once():
    window = {"story_id": "story", "start": 0.0, "end": 20.0, "duration": 20.0}
    media = [
        {
            "id": "logo", "media_type": "video",
            "title": "Paramount Pictures Logo with Fanfare Official (1080p, HD)",
            "page_url": "https://example.com/logo", "duration": "0:15",
            "stored_path": "logo.mp4", "width": 1920, "height": 1080,
        },
        {
            "id": "img", "media_type": "image", "title": "Paramount studio",
            "stored_path": "studio.jpg", "width": 1920, "height": 1080,
        },
    ]
    clips = _visual_slices(window, media)
    assert sum(1 for clip in clips if clip["candidate_id"] == "logo") == 1
    assert sum(1 for clip in clips if clip["candidate_id"] == "img") == 1


def test_story_windows_reserve_aligned_outro_tail():
    rows = [{
        "id": "v1", "segment_index": 1, "story_id": "ray",
        "duration_seconds": 36.0, "audio_path": "audio/ray.mp3",
        "alignment_json": "{}",
        "reserved_tail_seconds": 15.0,
        "reserved_tail_kind": "outro",
    }]
    voice, total = voice_timeline(rows)
    assert total == 36.0
    windows = story_windows(voice)
    assert len(windows) == 2
    assert windows[0]["story_id"] == "ray"
    assert windows[0]["duration"] == 21.0
    assert windows[1]["story_id"] == ""
    assert windows[1]["duration"] == 15.0
    assert windows[1]["reserved_kind"] == "outro"
