from app.services.cinema_format import (
    annotate_style_quality, build_style_packet, reference_date, style_rows_for_window, usable_style_transcripts,
)

CLEAN = "این هفته خبرهای زیادی داشتیم و حالا بریم سراغ فیلم‌ها که خیلی جالب بودن و سریال‌ها هم بودن " * 30


def _row(name, content, enabled=1):
    return {"id": name, "name": name, "content": content, "enabled": enabled}


def test_garbled_transcript_is_flagged_and_excluded():
    garbled = " ".join(f"قزلف{i} بکلن{i} مرتبو{i}" for i in range(200))
    rows = annotate_style_quality([_row(f"ep{i}", CLEAN) for i in range(4)] + [_row("bad", garbled)])
    flags = {row["name"]: row["likely_garbled"] for row in rows}
    assert flags["bad"] and not any(flags[f"ep{i}"] for i in range(4))
    assert "bad" not in [row["name"] for row in usable_style_transcripts(rows)]
    assert "قزلف1 " not in build_style_packet(rows)


def test_too_few_transcripts_are_never_flagged():
    rows = annotate_style_quality([_row("a", CLEAN), _row("b", "واژه‌های کاملاً متفاوت دیگر اینجا")])
    assert not any(row["likely_garbled"] for row in rows)


def test_same_week_or_later_references_are_kept_from_the_writer():
    assert reference_date("12K-views__2031-03-12__episode.txt") == "2031-03-12"
    assert reference_date("no date here") == ""
    rows = annotate_style_quality([_row("x__2031-03-01__a", CLEAN), _row("x__2031-03-12__b", CLEAN), _row("undated", CLEAN)])
    names = [row["name"] for row in style_rows_for_window(rows, "2031-03-10")]
    assert names == ["x__2031-03-01__a", "undated"]
