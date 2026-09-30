from app.services.cinema_format import (
    annotate_style_quality, build_style_packet, build_writer_style_packet,
    reference_date, style_reference_kind, style_rows_for_window,
    writer_style_rows_for_window, usable_style_transcripts,
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



def test_monthly_preview_is_not_misclassified_as_weekly_news():
    monthly = _row(
        "70K__2026-08-23__معرفی مورد انتظارترین فیلم ها و سریال‌هایی که قراره شهریور ماه منتشر بشن.txt",
        "سلام به همه دوستان. امروز مثل هر ماه بریم ببینیم مورد انتظارترین فیلم‌ها و سریال‌هایی که ماه بعد میان چی هستن. بعداً هر هفته هم خبر داریم.",
    )
    assert style_reference_kind(monthly) == "monthly_preview"


def test_writer_style_rows_use_only_recent_same_format_weekly_examples():
    rows = annotate_style_quality([
        _row("weekly__2026-09-18__آخرین و جدید ترین اخبار سینمای جهان.txt", "سلام. مثل هر هفته بریم سراغ اخبار سینما. " + CLEAN),
        _row("weekly__2026-09-11__آخرین و جدید ترین اخبار سینمای جهان.txt", "سلام. توی هفته گذشته خبرهای زیادی داشتیم. " + CLEAN),
        _row("weekly__2026-09-04__آخرین و جدید ترین اخبار سینمای جهان.txt", "سلام. مثل هر هفته خبرهای سینما. " + CLEAN),
        _row("monthly__2026-08-23__معرفی مورد انتظارترین فیلم ها و سریال‌هایی که قراره شهریور ماه منتشر بشن.txt", "سلام. مثل هر ماه بریم سراغ فیلم‌هایی که ماه بعد میان. " + CLEAN),
    ])
    picked = writer_style_rows_for_window(rows, "2026-09-21", "weekly_news", max_rows=4)
    assert [style_reference_kind(row) for row in picked] == ["weekly_news", "weekly_news", "weekly_news"]
    packet = build_writer_style_packet(rows, "2026-09-21", "weekly_news", max_chars=24000)
    assert "DIRECT SAME-FORMAT REFERENCES ARE THE PRIMARY VOICE AUTHORITY" in packet
    assert "معرفی مورد انتظارترین" not in packet
