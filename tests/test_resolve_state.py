from app.main import _resolve_input_signature, _resolve_prerequisites


def voice_row(index=1, story_id="story", approved=True):
    return {
        "id": f"v{index}",
        "segment_index": index,
        "story_id": story_id,
        "audio_path": f"audio/narration/{index:04d}.mp3",
        "duration_seconds": 10.0,
        "selected_take": 1 if approved else 0,
        "approval_status": "approved" if approved else "pending",
        "audio_status": "aligned" if approved else "generated",
    }


def media_row(media_id="m1", story_id="story", downloaded=True):
    return {
        "id": media_id,
        "story_id": story_id,
        "selected": 1,
        "stored_path": f"media/selected/{story_id}/{media_id}.mp4" if downloaded else "",
        "download_status": "downloaded" if downloaded else "not_downloaded",
    }


def test_resolve_prerequisites_require_approved_voice_and_media_per_story():
    ready = _resolve_prerequisites([voice_row()], [media_row()])
    assert ready["ready"] is True
    assert ready["voice_pending"] == 0
    assert ready["stories_missing_downloaded_media"] == []

    pending_voice = _resolve_prerequisites([voice_row(approved=False)], [media_row()])
    assert pending_voice["ready"] is False
    assert pending_voice["voice_pending"] == 1

    missing_media = _resolve_prerequisites([voice_row()], [])
    assert missing_media["ready"] is False
    assert missing_media["stories_missing_downloaded_media"] == ["story"]


def test_resolve_signature_changes_when_approved_take_or_media_changes():
    voices = [voice_row()]
    media = [media_row()]
    base = _resolve_input_signature(voices, media)

    changed_take = [dict(voices[0], selected_take=2, audio_path="audio/narration/take2.mp3")]
    assert _resolve_input_signature(changed_take, media) != base

    changed_media = [dict(media[0], stored_path="media/selected/story/new.mp4")]
    assert _resolve_input_signature(voices, changed_media) != base
