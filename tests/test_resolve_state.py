from app.main import _reconcile_voice_story_rows, _resolve_input_signature, _resolve_prerequisites


def voice_row(index=1, story_id="story", approved=True, source_text=""):
    return {
        "id": f"v{index}",
        "segment_index": index,
        "story_id": story_id,
        "source_text": source_text,
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



def story_row(story_id, title, category="upcoming_films", url=""):
    return {
        "id": story_id,
        "canonical_title": title,
        "summary": "",
        "category": category,
        "articles": [{"url": url, "title": title}] if url else [],
    }


def test_resolve_reconciles_legacy_voice_story_ids_to_current_media_story_ids():
    voices = [
        voice_row(1, story_id="old-werwulf"),
        voice_row(2, story_id="old-lotr"),
    ]
    historical = [
        story_row(
            "old-werwulf",
            "‘Feed upon the flesh of mankind!’ Robert Eggers sics chilling new ‘Werwulf’ trailer on fans",
            url="https://goldderby.com/werwulf",
        ),
        story_row(
            "old-lotr",
            "Lord of the Rings takes us back to the Shire in first look at new movie from Andy Serkis",
            url="https://digitalspy.com/lord-of-the-rings",
        ),
    ]
    current = [
        story_row(
            "new-werwulf",
            "‘Feed upon the flesh of mankind!’ Robert Eggers sics chilling new ‘Werwulf’ trailer on fans",
            url="https://goldderby.com/werwulf",
        ),
        story_row(
            "new-lotr",
            "Lord of the Rings takes us back to the Shire in first look at new movie from Andy Serkis",
            url="https://digitalspy.com/lord-of-the-rings",
        ),
    ]

    resolved, info = _reconcile_voice_story_rows(voices, current, historical)

    assert [row["story_id"] for row in resolved] == ["new-werwulf", "new-lotr"]
    assert info["remapped_segment_count"] == 2
    assert info["unresolved_story_ids"] == []

    media = [
        media_row("m1", "new-werwulf"),
        media_row("m2", "new-lotr"),
    ]
    prerequisites = _resolve_prerequisites(resolved, media)
    assert prerequisites["ready"] is True
    assert prerequisites["stories_missing_downloaded_media"] == []


def test_resolve_story_reconciliation_does_not_guess_ambiguous_topic_match():
    voices = [voice_row(1, story_id="old-ray")]
    historical = [story_row("old-ray", "Ray Gunn official trailer")]
    current = [
        story_row("new-ray-1", "Ray Gunn official trailer"),
        story_row("new-ray-2", "Ray Gunn official trailer"),
    ]

    resolved, info = _reconcile_voice_story_rows(voices, current, historical)

    assert resolved[0]["story_id"] == "old-ray"
    assert info["unresolved_story_ids"] == ["old-ray"]


def test_resolve_signature_changes_when_effective_story_mapping_changes():
    voices = [voice_row(story_id="old-story")]
    media = [media_row(story_id="new-story")]
    original = _resolve_input_signature(voices, media)
    remapped = _resolve_input_signature([dict(voices[0], story_id="new-story")], media)
    assert remapped != original



def test_resolve_reconciles_changed_historical_title_with_fuzzy_title_match():
    voices = [voice_row(1, story_id="old-narnia")]
    historical = [
        story_row(
            "old-narnia",
            "Greta Gerwig's Narnia movie gets a 2027 theatrical release",
            url="https://netflix.com/tudum/narnia-old",
        )
    ]
    current = [
        story_row(
            "new-narnia",
            "Narnia: The Magician’s Nephew, Directed by Greta Gerwig, Roars to Life in 2027",
            url="https://netflix.com/tudum/narnia-new",
        )
    ]
    resolved, info = _reconcile_voice_story_rows(voices, current, historical)
    assert resolved[0]["story_id"] == "new-narnia"
    assert info["unresolved_story_ids"] == []


def test_resolve_can_recover_missing_historical_story_from_narration_text():
    voices = [
        voice_row(
            1,
            story_id="hallucinated-old-id",
            source_text="The new Werwulf trailer from Robert Eggers has finally arrived.",
        )
    ]
    current = [
        story_row(
            "new-werwulf",
            "‘Feed upon the flesh of mankind!’ Robert Eggers sics chilling new ‘Werwulf’ trailer on fans",
        ),
        story_row(
            "new-ray",
            "Brad Bird’s ‘Ray Gunn’ Gets First Trailer, 70mm Theatrical Release, Expanded Voice Cast",
        ),
    ]
    resolved, info = _reconcile_voice_story_rows(voices, current, [])
    assert resolved[0]["story_id"] == "new-werwulf"
    assert info["unresolved_story_ids"] == []
    assert info["match_details"]["hallucinated-old-id"]["method"] == "narration-text"
