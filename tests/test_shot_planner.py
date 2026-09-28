from app.services.shot_planner import choose_video_shot


def test_choose_video_shot_avoids_used_range():
    analysis = {
        "mode": "scene_detection",
        "shots": [
            {"index": 0, "start": 8.0, "end": 13.0, "score": 55},
            {"index": 1, "start": 22.0, "end": 27.0, "score": 52},
            {"index": 2, "start": 36.0, "end": 41.0, "score": 48},
        ],
    }
    first = choose_video_shot(analysis, wanted=5.0, used_ranges=[])
    assert first["start"] == 8.0

    second = choose_video_shot(
        analysis,
        wanted=5.0,
        used_ranges=[(first["start"], first["end"])],
    )
    assert second["start"] == 36.0
    assert second["end"] <= 41.0


def test_choose_video_shot_prefers_non_overlapping_scene_over_repeat():
    analysis = {
        "mode": "scene_detection",
        "shots": [
            {"index": 0, "start": 5.0, "end": 11.0, "score": 70},
            {"index": 1, "start": 30.0, "end": 36.0, "score": 45},
        ],
    }
    chosen = choose_video_shot(
        analysis,
        wanted=5.0,
        used_ranges=[(5.0, 11.0)],
    )
    assert chosen["start"] >= 30.0



def test_reused_trailer_prefers_farther_scene_when_scores_are_similar():
    analysis = {
        "mode": "scene_detection",
        "shots": [
            {"index": 0, "start": 10.0, "end": 15.0, "score": 50},
            {"index": 1, "start": 16.0, "end": 21.0, "score": 49},
            {"index": 2, "start": 70.0, "end": 75.0, "score": 48},
        ],
    }
    chosen = choose_video_shot(
        analysis,
        wanted=5.0,
        used_ranges=[(10.0, 15.0)],
        hint_start=None,
    )
    assert chosen["start"] == 70.0
