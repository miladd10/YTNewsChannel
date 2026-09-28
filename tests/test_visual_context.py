from app.services.media import story_visual_plan
from app.services.research import _validated_visual_context


def _sources():
    return [
        {
            "url": "https://example.com/brad-bird",
            "source": "Example",
            "title": "Brad Bird on Ray Gunn and The Incredibles",
            "snippet": "Brad Bird previously directed The Incredibles.",
            "raw": {},
        }
    ]


def test_visual_context_requires_supplied_evidence_and_keeps_layout():
    raw = [
        {
            "kind": "related_title",
            "label": "The Incredibles",
            "subjects": ["The Incredibles"],
            "related_title": "The Incredibles",
            "narration_cue": "the director of The Incredibles",
            "why": "The narration uses the previous film as the familiarity cue.",
            "preferred_media": ["poster", "official still"],
            "layout_hint": "person_plus_title",
            "source_urls": ["https://example.com/brad-bird"],
        },
        {
            "kind": "fun_fact",
            "label": "Unsupported",
            "subjects": ["Unsupported"],
            "source_urls": ["https://not-supplied.example/fact"],
        },
    ]
    cleaned = _validated_visual_context(raw, _sources())
    assert len(cleaned) == 1
    assert cleaned[0]["kind"] == "related_title"
    assert cleaned[0]["layout_hint"] == "person_plus_title"
    assert cleaned[0]["narration_cue"] == "the director of The Incredibles"


def test_people_group_expands_to_multi_panel_visual_beats():
    story = {
        "canonical_title": "Awards night",
        "_narration_text": "Martin Scorsese, Robert De Niro and Leonardo DiCaprio appeared together.",
        "_voice_duration_seconds": 18.0,
        "visual_context": [
            {
                "kind": "people_group",
                "label": "Scorsese, De Niro and DiCaprio",
                "subjects": ["Martin Scorsese", "Robert De Niro", "Leonardo DiCaprio"],
                "narration_cue": "appeared together",
                "why": "All three are discussed in the same narration beat.",
                "layout_hint": "three_up",
                "source_urls": ["https://example.com/event"],
            }
        ],
    }
    plan = story_visual_plan(story)
    grouped = [beat for beat in plan["beats"] if beat.get("group_id")]
    assert [beat["label"] for beat in grouped] == [
        "Martin Scorsese",
        "Robert De Niro",
        "Leonardo DiCaprio",
    ]
    assert len({beat["group_id"] for beat in grouped}) == 1
    assert all(beat["layout_hint"] == "three_up" for beat in grouped)
    assert all(beat["kind"] == "person" for beat in grouped)


def test_fun_fact_is_a_distinct_visual_beat():
    story = {
        "canonical_title": "Ray Gunn",
        "_narration_text": "Ray Gunn is out soon. Brad Bird also directed The Incredibles.",
        "_voice_duration_seconds": 20.0,
        "visual_context": [
            {
                "kind": "fun_fact",
                "label": "The Incredibles",
                "subjects": ["The Incredibles"],
                "narration_cue": "also directed The Incredibles",
                "why": "Dedicated sourced context beat.",
                "layout_hint": "single",
                "source_urls": ["https://example.com/brad-bird"],
            }
        ],
    }
    plan = story_visual_plan(story)
    assert any(
        beat["kind"] == "fun_fact" and beat["label"] == "The Incredibles"
        for beat in plan["beats"]
    )
