from __future__ import annotations

import json
import re
import uuid

from .ai import generate_text
from .elevenlabs_client import V3_END_GUARD_TAG
from .secrets import masked_status

NARRATION_CONTINUITY_TARGET_CHARS = 1800
STORY_MARKER_RE = re.compile(r"<!--\s*STORY:([^>]+?)\s*-->", re.IGNORECASE)
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
RESERVED_INTRO_HEADINGS = {"intro", "introduction", "opening", "مقدمه"}
RESERVED_OUTRO_HEADINGS = {"outro", "ending", "closing", "conclusion", "پایان", "خاتمه"}


def _normalized_heading(value: str) -> str:
    value = re.sub(r"[*_\`]+", "", value or "")
    value = re.sub(r"[^\w\u0600-\u06ff]+", " ", value, flags=re.UNICODE)
    return " ".join(value.casefold().split())


def reserved_heading_kind(line: str) -> str:
    match = HEADING_RE.match((line or "").strip())
    if not match:
        return ""
    heading = _normalized_heading(match.group(1))
    if heading in RESERVED_INTRO_HEADINGS:
        return "intro"
    if heading in RESERVED_OUTRO_HEADINGS:
        return "outro"
    return ""


def _plain_markdown_line(line: str) -> str:
    value = line.strip()
    if not value or value.startswith("#") or value.startswith("<!--"):
        return ""
    value = re.sub(r"^[-*+]\s+", "", value)
    value = re.sub(r"^>\s*", "", value)
    value = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", value)
    value = value.replace("**", "").replace("__", "")
    value = re.sub(r"^[_*](.+)[_*]$", r"\1", value)
    return value.strip()


def _split_long_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    paragraphs = [x.strip() for x in text.split("\n\n") if x.strip()]
    pieces: list[str] = []
    current = ""
    for paragraph in paragraphs:
        sentences = re.split(r"(?<=[.!?؟])\s+", paragraph) if len(paragraph) > limit else [paragraph]
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if current and len(current) + len(sentence) + 2 > limit:
                pieces.append(current)
                current = ""
            if len(sentence) > limit:
                words = sentence.split()
                chunk = ""
                for word in words:
                    if chunk and len(chunk) + len(word) + 1 > limit:
                        pieces.append(chunk)
                        chunk = ""
                    chunk = f"{chunk} {word}".strip()
                if chunk:
                    if current:
                        pieces.append(current)
                        current = ""
                    pieces.append(chunk)
            else:
                current = f"{current}\n\n{sentence}".strip()
    if current:
        pieces.append(current)
    return pieces or [text]


def extract_narration_segments(content: str, target_chars: int = NARRATION_CONTINUITY_TARGET_CHARS) -> list[dict]:
    lines = (content or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[dict] = []
    current_story = ""
    current_lines: list[str] = []

    def flush_block() -> None:
        nonlocal current_lines
        text = "\n".join(x for x in current_lines if x).strip()
        if text:
            blocks.append({"story_id": current_story, "text": text})
        current_lines = []

    for raw in lines:
        reserved_kind = reserved_heading_kind(raw)
        if reserved_kind:
            flush_block()
            current_story = ""
            continue
        marker = STORY_MARKER_RE.search(raw)
        if marker:
            flush_block()
            current_story = marker.group(1).strip()
            continue
        spoken = _plain_markdown_line(raw)
        if not spoken:
            if current_lines and current_lines[-1] != "":
                current_lines.append("")
            continue
        current_lines.append(spoken)
    flush_block()

    merged: list[dict] = []
    for block in blocks:
        text = block["text"].strip()
        if not text:
            continue
        previous = merged[-1] if merged else None
        if previous and previous["story_id"] == block["story_id"] and len(previous["source_text"]) + len(text) + 2 <= target_chars:
            previous["source_text"] += "\n\n" + text
        else:
            for piece in _split_long_text(text, target_chars):
                merged.append({"id": str(uuid.uuid4()), "story_id": block["story_id"], "source_text": piece})
    for index, item in enumerate(merged, 1):
        item["segment_index"] = index
    return merged


# Arabic-script short-vowel and pronunciation marks (fatha, kasra, damma,
# tanwin, sukun, shadda, superscript alef, hamza above/below). They change how
# a word is pronounced, not which word it is.
VOWEL_MARKS_RE = re.compile("[\u064B-\u0652\u0654\u0655\u0670]")


def strip_vowel_marks(text: str) -> str:
    return VOWEL_MARKS_RE.sub("", text or "")


def _normalize_spacing(text: str) -> str:
    return re.sub(r"\s+", " ", strip_vowel_marks(text or "")).strip()


def parse_pronunciation_lines(text: str) -> tuple[list[dict], list[str]]:
    """Parse "written = pronounced" lines.

    An entry may only add vowel marks to the written form, so the spoken
    words stay exactly the approved narration (the voice safety check still
    holds). Anything else is rejected with a reason.
    """
    entries: list[dict] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            rejected.append(f"{line} — use: written = pronounced")
            continue
        written, spoken = (part.strip() for part in line.split("=", 1))
        if not written or not spoken:
            rejected.append(f"{line} — both sides are required")
            continue
        if _normalize_spacing(spoken) != _normalize_spacing(written):
            rejected.append(f"{line} — the pronounced form may only add vowel marks (اعراب) to the written form")
            continue
        if spoken == written:
            rejected.append(f"{line} — pronounced form adds no vowel marks")
            continue
        key = _normalize_spacing(written)
        if key in seen:
            rejected.append(f"{line} — duplicate entry")
            continue
        seen.add(key)
        entries.append({"written": written, "spoken": spoken})
    return entries, rejected


def apply_pronunciations(text: str, entries: list[dict]) -> str:
    value = text or ""
    for entry in sorted(entries or [], key=lambda item: len(item.get("written") or ""), reverse=True):
        written = str(entry.get("written") or "").strip()
        spoken = str(entry.get("spoken") or "").strip()
        if not written or not spoken:
            continue
        pattern = r"\s+".join(re.escape(part) for part in written.split())
        value = re.sub(rf"(?<![\w\u200c]){pattern}(?![\w\u064B-\u0652])", lambda _m: spoken, value)
    return value


def _spoken_words(text: str) -> list[str]:
    value = re.sub(r"\[[^\]]+\]", " ", strip_vowel_marks(text or ""))
    return [x.casefold().replace("’", "'") for x in re.findall(r"[^\W_]+(?:['’\-][^\W_]+)*", value, flags=re.UNICODE)]


def performance_text_is_safe(source_text: str, performance_text: str) -> bool:
    return bool((performance_text or "").strip()) and _spoken_words(source_text) == _spoken_words(performance_text)


def ensure_visible_end_pause(text: str) -> str:
    value = (text or "").rstrip()
    if not value:
        return value
    if re.search(r"\[(?:short\s+|long\s+)?pause\]\s*$", value, flags=re.IGNORECASE):
        return value
    return value + "\n\n" + V3_END_GUARD_TAG


PERFORMANCE_SYSTEM = """You are a production voice-performance director preparing exact narration for ElevenLabs Eleven v3.
The episode uses ONE narrator voice from beginning to end.
Never add, remove, replace, translate, paraphrase, reorder, or normalize spoken words.
Preserve names, numbers, currencies, dates, titles, abbreviations, facts, and wording exactly.
You may only add Eleven v3 square-bracket vocal tags, punctuation, ellipses, em dashes, capitalization for emphasis, paragraph breaks, and spacing.
For Persian, you may also add short-vowel marks (اعراب) to a foreign name whose bare spelling could be read as ordinary Persian words; never change its letters.
Never use SSML/XML and never put original spoken words inside square brackets.
Keep one stable narrator identity, baseline energy, pace, and vocal placement across the whole episode.
Treat each segment as one continuous recording session even when visuals change.
Use restrained vocal tags such as [thoughtful], [dryly], [curious], [quietly amused], [sighs], [chuckles], [short pause] only when earned.
Shape setup/reveal/punchline beats with punctuation and pauses without restarting the emotional tone every paragraph.
Use previous_context and next_context only for continuity; never copy their words into the segment.
Return ONLY a JSON array in the same order with objects shaped {\"id\":\"...\",\"performance_text\":\"...\"}."""


def _json_array(text: str) -> list:
    value = (text or "").strip()
    value = re.sub(r"^```(?:json)?\s*", "", value)
    value = re.sub(r"\s*```$", "", value)
    start, end = value.find("["), value.rfind("]")
    if start < 0 or end < start:
        raise ValueError("Performance model did not return a JSON array.")
    return json.loads(value[start:end + 1])


def prepare_performance(segments: list[dict]) -> tuple[dict[str, str], list[str], str, str]:
    settings = masked_status()
    provider = settings.get("writer_provider", "codex_local")
    model = settings.get("writer_model", "default")
    output: dict[str, str] = {}
    warnings: list[str] = []
    actual_provider, actual_model = provider, model

    def context(index: int) -> dict | None:
        if index < 0 or index >= len(segments):
            return None
        item = segments[index]
        return {"story_id": item.get("story_id", ""), "spoken_text": item.get("source_text", "")}

    batch_size = 10
    for start in range(0, len(segments), batch_size):
        batch = segments[start:start + batch_size]
        payload = []
        for offset, seg in enumerate(batch):
            absolute = start + offset
            payload.append({
                "id": seg["id"], "segment_index": seg["segment_index"], "story_id": seg.get("story_id", ""),
                "spoken_text": seg["source_text"], "previous_context": context(absolute - 1), "next_context": context(absolute + 1),
            })
        prompt = "Prepare these narration segments for Eleven v3. Maintain one narrator identity and continuous performance across story boundaries. Spoken words are immutable.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
        try:
            raw, actual_provider, actual_model = generate_text(provider, model, PERFORMANCE_SYSTEM, prompt)
            parsed = _json_array(raw)
            candidates = {str(item.get("id")): str(item.get("performance_text") or "") for item in parsed if isinstance(item, dict)}
        except Exception as exc:
            candidates = {}
            warnings.append(f"Performance direction failed for a batch; exact narration kept: {exc}")

        for seg in batch:
            candidate = candidates.get(seg["id"], "").strip()
            if candidate and performance_text_is_safe(seg["source_text"], candidate) and "<" not in candidate:
                base = candidate
            else:
                base = seg["source_text"]
                if candidate:
                    warnings.append("Segment {}: unsafe performance markup rejected; exact narration kept.".format(seg["segment_index"]))
            output[seg["id"]] = ensure_visible_end_pause(base)

    return output, warnings, actual_provider, actual_model