# YT News Studio

Local research and narration pipeline for YouTube news channels. The first MVP implements **Cinema → Weekly News**.

## Current pipeline

1. **Research** — searches Google News RSS across cinema query groups for the configured week, stores the raw findings, deduplicates overlapping coverage into unique stories, and optionally asks GPT/Claude to rank the stories.
2. **Pick News** — human editorial gate with Include / Maybe / Skip decisions.
3. **Narration** — generates a narration-led weekly cinema-news script from Included stories only.
4. **Media Plan** — maps narration blocks to real-world visual sourcing needs (trailers, interviews, official stills, social posts, screenshots, graphics, etc.).
5. **Find Media** — MVP provides exact search intents and one-click YouTube / Google Images / Reddit searches. Direct source adapters and candidate capture are the next implementation slice.

No image generation is used.

## GPT / Claude subscription mode

The app can call the official local CLIs:

- **Codex / ChatGPT Subscription** (`codex`)
- **Claude Code / Claude Subscription** (`claude`)

Use **AI & Provider Settings** to inspect sign-in state, open the provider login flow, test the connection, and assign providers to Research, Narration, and Media Planning.

Optional OpenAI / Anthropic API keys are also supported and are stored using the operating-system credential store.

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
├── media-plan/
├── media/
│   ├── candidates/
│   └── selected/
└── exports/
```

The local SQLite index lives in `data/ytnews.db` and is intentionally ignored by Git.
