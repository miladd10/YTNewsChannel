# YT News Studio

A local app that turns a week of cinema news into a narrated YouTube episode: research → story selection → fact-locked narration → ElevenLabs voice → B-roll sourcing → a DaVinci Resolve timeline. The first format is **Cinema → Weekly News**, written in Persian by default.

It runs on your own computer at `http://127.0.0.1:8787`. See [CHANGELOG.md](CHANGELOG.md) for version history.

## Pipeline

1. **Format Research** — searches Google News and public social posts for each section of the weekly format (Trends, Industry, Upcoming Films, TV, Box Office, …) inside the project's date window. Coverage is clustered into stories, ranked by AI, and duplicate stories about the same subject are merged. Every story gets a specific news hook and the date the event actually happened; stories whose event falls outside the window, or that lack independent current sources, cannot be included.
2. **Section Selection** — you choose Include / Maybe / Skip per story. Freshness, verification status, sources and any familiarity cue are shown for each.
3. **Narration Writer** — builds a source-locked claim ledger from the approved stories (headlines plus each article's description and opening paragraphs), plans with claim IDs rather than English prose, and writes a spoken draft from a compact factual packet plus same-format reference transcripts. Before a generated/enriched/revised draft is saved, the app checks that every selected story is actually present under the correct section and that the claim audit passes. Factual repair is kept minimal and separate from the final spoken-Persian fluency pass, so fact checking cannot silently rewrite the whole episode into generic news prose. Every draft is still independently fact-checked and reviewed. You can revise from the review, edit the draft by hand, and approve — or approve over failed checks with a recorded reason.
4. **Voice** — one ElevenLabs narrator for the whole episode, generated segment by segment with Take 1 / Take 2 and explicit approval. A pronunciation list adds vowel marks to names. The step warns if the recorded voice is from a different draft than the approved one.
5. **Media Sources** — finds official/original video and images for what the narration actually says (people, related titles, interviews, BTS, comparisons), ranked by quality and provenance.
6. **Downloads** — downloads the selected media at the best available quality.
7. **Resolve Plan** — uses the approved voice timing as the master timeline, cuts trailer scenes on narration phrase boundaries, renders Resolve-safe H.264 media, and writes an OTIO timeline plus CSV timing sheets.

No images are generated. The app does not clear reuse rights for downloaded media — check licensing before publishing.

## How the writing is kept accurate and natural

- **Claim ledger.** Every checkable fact in a draft must map to a verified ledger claim from the approved sources. Numbers keep their scope (opening weekend vs cumulative, domestic vs worldwide, limited vs wide release).
- **Attribution policy.** Sources are spoken only when the ledger requires it; an estimate needs only a light marker such as «حدود».
- **Length target.** The project's target minutes become a word budget the writer aims for with real material, never filler.
- **Style references.** Imported transcripts teach tone and pacing only. For weekly news, the writer/reviser/polisher now use the four closest earlier **weekly-news** transcripts as their primary voice authority; the AI-generated Style Blueprint is secondary. Monthly preview/list videos are excluded from direct weekly prose examples. Each direct reference contributes a real opening plus a cue-centered transition/quick-news stretch, with ASR line breaks normalized. Garbled transcripts and references from the episode's own week are excluded.
- **Names.** Transliterated names that would read as ordinary words get vowel marks.

## Requirements

- Python 3.11+
- FFmpeg and FFprobe on your PATH (needed for highest-quality Step 6 video downloads and Step 7 Resolve packaging)
- An AI provider for research, writing and review — either signed-in local CLIs (**Codex** for a ChatGPT subscription, **Claude Code** for a Claude subscription) or OpenAI / Anthropic API keys
- An ElevenLabs API key for Step 4

API keys are stored in your operating system's credential store, never in the project folder. Configure providers under **AI & Provider Settings**.

## Run

**macOS:** double-click `Start YT News Studio.command` (stop it with `Stop YT News Studio.command`).

**Windows:** double-click `Start YT News Studio.bat` (stop it with `Stop YT News Studio.bat`).

**Manually:**

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Then open `http://127.0.0.1:8787`. Set `YT_NEWS_PORT` to use another port.

The server only accepts requests addressed to localhost, and rejects state-changing requests from other websites.

## Project folders

Each project is a portable folder:

```text
Cinema Weekly — <dates>/
├── project.json
├── research/        raw/ (search results) · stories/ (clustered stories)
├── narration/       vNN.md drafts · plans/ · reviews/ · fact-checks/ · claims/
├── audio/           narration/ (voice takes)
├── timing/          resolve_plan.json
├── media-plan/
├── media/           candidates/ · selected/ · analysis/ (scene cache) · composites/
├── resolve/         news_timeline.otio · voice_timing.csv · media_timing.csv · media/ · package_manifest.json
└── exports/
```

The app's own index database lives in `data/ytnews.db` and is not committed to Git.

## Tests

```bash
pip install pytest
PYTHONPATH=. pytest -q
```
