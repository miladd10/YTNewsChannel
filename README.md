# YT News Studio

Local research and narration pipeline for YouTube news channels. The first MVP implements **Cinema → Weekly News**.

## Current pipeline

1. **Research** — searches Google News RSS across cinema query groups for the configured week, stores the raw findings, deduplicates overlapping coverage into unique stories, and optionally asks GPT/Claude to rank the stories.
2. **Pick News** — human editorial gate with Include / Maybe / Skip decisions.
3. **Narration** — generates a narration-led weekly cinema-news script from Included stories only.
4. **Voice** — connects to ElevenLabs and uses one narrator voice for the complete episode, but generates each prepared narration segment separately like `video-studio`. Each segment has editable Eleven v3 performance input, Take 1 / Take 2, audio preview, and explicit approval. Voice generation shows a persistent processing panel with spinner, elapsed time, current segment/take, and determinate progress for sequential generation. `Generate Missing Take 1s` loops one segment per API request. The approved take is measured from the real MP3 frames and forced-aligned for exact timing.
5. **Media Sources** — searches curated official/original B-roll after voice timing is ready, shows the real narration duration for each news item, and falls back to a small set of relevant images only when suitable HD video is unavailable.
6. **Downloads** — downloads selected media at the highest available source quality. Shared source videos are downloaded once and can use different source ranges for different stories.
7. **Resolve Plan** — treats the approved ElevenLabs takes as the master timeline, assigns downloaded videos/stills to exact narration windows, keeps video playback at 1.0× with source audio muted, stages every referenced voice/video/image under `resolve/media/`, and writes DaVinci Resolve-compatible raw filesystem paths into the OTIO to avoid missing-media relink failures. The target is UHD 3840×2160.

No image generation is used. Media discovery uses web image/video search, and video downloading is handled locally for selected public media URLs.

## GPT / Claude subscription mode

The app can call the official local CLIs:

- **Codex / ChatGPT Subscription** (`codex`)
- **Claude Code / Claude Subscription** (`claude`)

Use **AI & Provider Settings** to inspect sign-in state, open the provider login flow, test the connection, and assign providers to Research, Narration, and Media Planning.

Optional OpenAI / Anthropic API keys are also supported and are stored using the operating-system credential store.

The **Voice** step accepts an ElevenLabs API key in the same OS credential store and lists the voices available on that ElevenLabs account, including compatible saved/cloned voices.

## Run

The app uses **port 8787** (not 8765 or 8766).

### macOS

Double-click `Start YT News Studio.command`, or:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

### Windows

Double-click `Start YT News Studio.bat`.

Then open `http://127.0.0.1:8787`.

## Project storage

Each project is portable and stores its own durable artifacts:

```text
Cinema Weekly — Sep 21–27/
├── project.json
├── research/
│   ├── raw/
│   └── stories/
├── narration/
├── audio/
│   └── narration/
├── timing/
│   └── resolve_plan.json
├── media-plan/
├── media/
│   ├── candidates/
│   └── selected/
├── resolve/
│   ├── news_timeline.otio
│   ├── voice_timing.csv
│   ├── media_timing.csv
│   ├── package_manifest.json
│   └── README.md
└── exports/
```

The local SQLite index lives in `data/ytnews.db` and is intentionally ignored by Git.
