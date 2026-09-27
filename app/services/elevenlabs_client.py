from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .secrets import get_api_key

BASE_URL = "https://api.elevenlabs.io"
MODEL_ID = "eleven_v3"
OUTPUT_FORMAT = "mp3_44100_128"
V3_END_GUARD_TAG = "[short pause]"
V3_ENDING_PAUSE_RE = re.compile(r"\[(?:short\s+|long\s+)?pause\]\s*$", re.IGNORECASE)
V3_VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True,
}


class ElevenLabsError(RuntimeError):
    pass


def request(method: str, path: str, json_body: dict | None = None, timeout: int = 180) -> tuple[bytes, str]:
    key = get_api_key("elevenlabs")
    if not key:
        raise ElevenLabsError("ElevenLabs API key is not configured.")
    data = None if json_body is None else json.dumps(json_body).encode("utf-8")
    headers = {"xi-api-key": key, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read(), response.headers.get("content-type", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
            detail = parsed.get("detail") or parsed
        except Exception:
            detail = body or str(exc)
        raise ElevenLabsError(f"ElevenLabs: {detail}") from exc
    except Exception as exc:
        raise ElevenLabsError(f"Could not reach ElevenLabs: {exc}") from exc


def list_voices() -> list[dict]:
    raw, _ = request("GET", "/v2/voices?page_size=100&include_total_count=true")
    payload = json.loads(raw.decode("utf-8"))
    result = []
    for item in payload.get("voices") or []:
        result.append({
            "voice_id": item.get("voice_id", ""),
            "name": item.get("name", "Unnamed voice"),
            "category": item.get("category", ""),
            "is_owner": bool(item.get("is_owner")),
        })
    return result


def apply_v3_end_guard(text: str) -> tuple[str, bool]:
    value = (text or "").rstrip()
    if not value:
        return value, False
    if V3_ENDING_PAUSE_RE.search(value):
        return value, False
    return value + "\n\n" + V3_END_GUARD_TAG, True


def text_to_speech(
    voice_id: str,
    text: str,
    *,
    previous_text: str | None = None,
    next_text: str | None = None,
    ensure_end_guard: bool = True,
) -> bytes:
    encoded = urllib.parse.quote(voice_id, safe="")
    synthesis_text, _ = apply_v3_end_guard(text) if ensure_end_guard else ((text or "").rstrip(), False)
    body = {
        "text": synthesis_text,
        "model_id": MODEL_ID,
        "apply_text_normalization": "auto",
        "voice_settings": dict(V3_VOICE_SETTINGS),
    }
    # Keep the same behavior as video-studio: Eleven v3 does not accept
    # previous_text / next_text request stitching, so continuity is handled by
    # the prepared performance text rather than sending unsupported fields.
    if MODEL_ID != "eleven_v3":
        if previous_text:
            body["previous_text"] = previous_text
        if next_text:
            body["next_text"] = next_text
    audio, _ = request(
        "POST",
        f"/v1/text-to-speech/{encoded}?output_format={OUTPUT_FORMAT}",
        body,
        timeout=240,
    )
    return audio


def forced_alignment(audio_path: Path, text: str) -> dict:
    key = get_api_key("elevenlabs")
    if not key:
        raise ElevenLabsError("ElevenLabs API key is not configured.")
    path = Path(audio_path)
    if not path.exists():
        raise ElevenLabsError("Audio file for forced alignment is missing.")

    boundary = "----YTNewsStudio" + uuid.uuid4().hex
    filename = path.name.replace('"', "")
    mime = "audio/mpeg" if path.suffix.lower() == ".mp3" else "application/octet-stream"
    parts = [
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="text"\r\n\r\n'
            f"{text}\r\n"
        ).encode("utf-8"),
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + path.read_bytes() + b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ]
    req = urllib.request.Request(
        BASE_URL + "/v1/forced-alignment",
        data=b"".join(parts),
        headers={
            "xi-api-key": key,
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
            detail = parsed.get("detail") or parsed
        except Exception:
            detail = body or str(exc)
        raise ElevenLabsError(f"ElevenLabs forced alignment: {detail}") from exc
    except Exception as exc:
        raise ElevenLabsError(f"Could not run ElevenLabs forced alignment: {exc}") from exc


def mp3_duration_seconds(path: Path) -> float | None:
    """Measure MP3 duration by summing MPEG frame sample counts, including VBR."""
    try:
        data = Path(path).read_bytes()
        size = len(data)
        if size < 4:
            return None
        pos = 0
        if data[:3] == b"ID3" and size >= 10:
            tag_size = (
                ((data[6] & 0x7F) << 21)
                | ((data[7] & 0x7F) << 14)
                | ((data[8] & 0x7F) << 7)
                | (data[9] & 0x7F)
            )
            footer = 10 if (data[5] & 0x10) else 0
            pos = min(size, 10 + tag_size + footer)

        bitrate_mpeg1_l3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
        bitrate_mpeg2_l3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0]
        sample_rates = {
            3: [44100, 48000, 32000],
            2: [22050, 24000, 16000],
            0: [11025, 12000, 8000],
        }

        total_seconds = 0.0
        frame_count = 0
        while pos + 4 <= size:
            if pos + 128 == size and data[pos:pos + 3] == b"TAG":
                break
            value = int.from_bytes(data[pos:pos + 4], "big")
            if (value & 0xFFE00000) != 0xFFE00000:
                pos += 1
                continue
            version_bits = (value >> 19) & 0x3
            layer_bits = (value >> 17) & 0x3
            bitrate_index = (value >> 12) & 0xF
            sample_index = (value >> 10) & 0x3
            padding = (value >> 9) & 0x1
            if version_bits == 1 or layer_bits != 1 or bitrate_index in (0, 15) or sample_index == 3:
                pos += 1
                continue
            rates = sample_rates.get(version_bits)
            if not rates:
                pos += 1
                continue
            sample_rate = rates[sample_index]
            bitrate_table = bitrate_mpeg1_l3 if version_bits == 3 else bitrate_mpeg2_l3
            bitrate_kbps = bitrate_table[bitrate_index]
            if not bitrate_kbps:
                pos += 1
                continue
            if version_bits == 3:
                frame_length = int((144000 * bitrate_kbps) / sample_rate) + padding
                samples_per_frame = 1152
            else:
                frame_length = int((72000 * bitrate_kbps) / sample_rate) + padding
                samples_per_frame = 576
            if frame_length <= 4 or pos + frame_length > size:
                pos += 1
                continue
            total_seconds += samples_per_frame / sample_rate
            frame_count += 1
            pos += frame_length
        return total_seconds if frame_count else None
    except Exception:
        return None
