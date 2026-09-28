# YT News Studio

Local research and narration pipeline for YouTube news channels. The first MVP implements **Cinema → Weekly News**.

## Current pipeline

1. **Research** — searches Google News RSS across cinema query groups for the configured week, stores the raw findings, deduplicates overlapping coverage into unique stories, and optionally asks GPT/Claude to rank the stories.
2. **Pick News** — human editorial gate with Include / Maybe / Skip decisions.
3. **Narration** — generates a narration-led weekly cinema-news script from Included stories only.
4. **Voice** — connects to ElevenLabs and uses one narrator voice for the complete episode, but generates each prepared narration segment separately like `video-studio`. Each segment has editable Eleven v3 performance input, Take 1 / Take 2, audio preview, and explicit approval. Voice generation shows a persistent processing panel with spinner, elapsed time, current segment/take, and determinate progress for sequential generation. `Generate Missing Take 1s` loops one segment per API request. The approved take is measured from the real MP3 frames and forced-aligned for exact timing.
5. **Media Sources** — gathers acceptable official/original copies from YouTube, embedded news/reference-page video, Vimeo/Dailymotion and other supported video pages, then ranks all copies globally by quality rather than source location. For likely copies of the same trailer/clip the order is 4K → 1440p → 1080p → 720p, with original/clean studio-distributor provenance used as the tiebreaker. Search runs are split into configurable narration-duration chunks (default 1 minute per request) using the approved voice timing, so each chunk is saved before the next request starts. Step 5 supports Search Missing, Regenerate All, and an always-visible per-story B-roll action: Find B-roll for stories with zero results, Regenerate B-roll for stories that already have results. While any B-roll search is active, the clicked action shows a spinner and Searching/Regenerating state, all other Step 5 search actions are disabled, and the progress card can be dismissed without cancelling the search. Search completion now reports actual saved candidate counts; a finished search with zero accepted media is shown as a no-result warning rather than a successful find. Step 5 now plans visual coverage from the actual narration instead of assuming one story equals one B-roll source. Reference/news pages are inspected first and publisher-specific resolution is used for Google News links; when a reference page already provides usable HD footage for a visual beat, the expensive broad search for that beat is skipped. Official webpages are expanded to their embedded players instead of being handed blindly to yt-dlp, and discovery timeouts/retries are bounded. Comparison/multi-title stories search each visual subject separately, longer narration can recommend multiple visual changes, and supporting images are kept when there are not enough distinct video choices. When an exact/current-title beat has no usable HD video, Step 5 automatically tries contextual cast/director footage when the narration supports it, then official previous-installment/franchise trailers/clips/featurettes, and only then falls back to images. Contextual candidates are labeled so archive footage is not presented as footage from the newly announced movie/show. Headline subject extraction also handles quoted slogans, box-office prefixes, trailing director credits, and news verbs such as takes/beats. The configurable narration-time chunking remains internal to the global searches; downloaded assets are preserved when a story is regenerated. Google News links are resolved back to publisher pages when possible. Images are only a fallback when no suitable HD video survives.
6. **Downloads** — downloads selected media at the highest available source quality. Shared source videos are downloaded once and can use different source ranges for different stories.
7. **Resolve Plan** — treats the approved ElevenLabs takes as the master timeline, assigns downloaded videos/stills to exact narration windows, keeps video playback at 1.0× with source audio muted, and stages Resolve-safe media under `resolve/media/`. Every video timeline cut is normalized to H.264 MP4 / yuv420p / constant timeline fps with source audio removed, still-image holds are rendered to exact-duration H.264 MP4 clips, and the OTIO uses raw absolute filesystem paths. Before export, the app probes the actual downloaded video duration, clamps any invalid source-in point, renders an exact frame count, pads the final frame when a source is shorter than the requested visual window, and probes the staged MP4 again before writing the OTIO. Still images are also rendered to exact-duration H.264 MP4 hold clips instead of giving Resolve a multi-second source range on a single PNG frame. This avoids Resolve offline-media failures caused by AV1/VP9/WebM/WebP/AVIF/container differences, bad discovery-duration metadata, out-of-range source cuts, and OTIO still-image duration handling. The target is UHD 3840×2160.

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
│   └── reviews/
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


### v0.3.18 media reliability
- Selected YouTube videos retry with fresh format extraction and alternate player-client strategies before failing.
- Step 6 shows Retry Failed / Pending after a partial download and skips files already downloaded.
- Generic franchise footage is no longer labeled as current footage when its subtitle/installment is absent from the story; it is eligible only as contextual franchise/archive B-roll.
- Reference article OG/Twitter hero images are preferred over generic image-search fallback when a story still needs supporting stills.


### v0.3.19 Resolve story reconciliation
- Resolve now reconciles approved narration segments that still reference story IDs from an older research run to the matching current Included stories.
- Matching uses exact title/topic identity and source-article overlap, and refuses ambiguous duplicate matches.
- The reconciled IDs are used for prerequisite checks, Resolve visual windows, and package signatures, so valid downloaded media no longer appears missing solely because research/story IDs changed after voice generation.


### v0.3.20 Resolve final story mapping
- Resolve reconciliation now also handles safely changed story titles with distinctive-token/fuzzy matching.
- If an old STORY marker no longer exists in the database, the approved narration text is used as a guarded fallback to identify the current Included story.
- Ambiguous matches remain blocked rather than guessed.
- Step 7 now shows the exact unresolved story/title, voice segment indexes, and narration excerpt when a mapping still cannot be resolved.


### v0.3.21 Resolve-safe media staging
- Resolve packaging no longer points OTIO clips directly at arbitrary downloaded YouTube/image formats.
- Each video cut is rendered to a short H.264 MP4/yuv420p clip at the timeline frame rate, with source audio removed; each still is converted to PNG.
- Staged video cuts begin at source frame 0 in OTIO while retaining the original trailer source in/out as metadata for review.
- FFmpeg is required for package generation so broken/offline Resolve media is caught during generation instead of after import.


### v0.3.23 Resolve-safe still holds
- Uploaded project inspection showed the remaining red Media Offline sections matched still-image timeline windows exactly; the staged H.264 video cuts themselves were valid.
- Step 7 now pre-renders every still hold as an exact-duration H.264 MP4/yuv420p/CFR clip with the expected frame count and validates it before writing OTIO.
- The original image remains the source asset for crop metadata, but Resolve receives a time-based MP4 source instead of a one-frame PNG with a multi-second source range.


### v0.3.24 Smart shot selection
- Step 7 analyzes each selected downloaded trailer/clip with cached keyframe-first scene analysis instead of taking arbitrary 7-second ranges. Full pixel scene detection is used only when a file exposes too few useful keyframes.
- The planner avoids typical trailer intro/outro regions when possible, prefers roughly 2.5–6 second scene-aware shots, and penalizes overlap so repeated use of the same source moves to a different part of the trailer.
- Hard cuts are kept between detected scenes from the same trailer. Short SMPTE dissolves are used only for still/media changes and story boundaries, with real staged transition handles so Resolve has source frames on both sides.
- Each selected still is used once only and for at most 3 seconds. If unique media runs out, the remaining narration is intentionally left open instead of looping the same image. Step 7 warns when a long image-only story does not have enough distinct stills.
- Scene analysis is cached under media/analysis so regenerating the Resolve package does not need to re-analyze unchanged video files.


### v0.3.25 Fast smart-shot analysis
- Smart shot discovery now reads encoded keyframe/scene-cut timestamps first, which is far faster on 4K trailers than decoding every frame for scene scoring.
- Full FFmpeg scene detection remains a fallback for sources with too few useful keyframes.
- Image-only Resolve warnings state the exact number of distinct stills recommended for the story duration at the 3-second maximum cadence.


### v0.3.26 Unique stills + reserved intro/outro
- Still images are never repeated within a story and are capped at 3 seconds each. If unique visual media is exhausted, Resolve leaves the remaining narration visually open rather than looping a still.
- Logo/fanfare/ident/title-announcement videos are limited to one use per story so short corporate/logo footage does not repeat across the same narration.
- Intro and outro headings are editorially reserved: they receive no automatic news B-roll. Future voice preparation creates separate blank-story intro/outro segments.
- Existing projects created before this rule are repaired without re-generating ElevenLabs audio: forced-alignment timestamps are used to detect where an outro leaked into the final story take, and Resolve ends that story's B-roll at the aligned outro boundary.


### v0.3.27 Smart coverage + UHD landscape media
- Resolve now keeps selecting different non-overlapping sections from the same selected trailer/clip until the narration window is covered or the source is genuinely exhausted; this fixes cases where a long 4K trailer supplied only one short shot and left the rest black.
- Low-variety logo/fanfare/title-announcement footage is strongly penalized after its first use, but can still contribute a different unused source range as a last-resort coverage source instead of leaving a news section empty.
- Media ranking now values editorial usefulness as well as resolution: a real official trailer/clip outranks a slightly higher-resolution title announcement or logo, while quality still decides between copies of the same asset.
- Image search now targets 4K/high-resolution landscape/16:9 stills and can return up to eight image candidates for stories that need still coverage. Portrait/poster imagery is strongly penalized and Step 5 displays image dimensions/orientation/4K readiness.
- Fixed an image-domain bug where the banned domain x.com falsely matched netflix.com, which could suppress official Netflix stills.
- Current-title validation is stricter for movie-vs-series/franchise mismatches so footage such as Rings of Power is not mislabeled as current footage for a different Lord of the Rings movie.
- Step 7 warns when selected media is below HD, portrait/square, or contextual archive footage so weak UHD inputs are visible before Resolve export.
- Corporate searches now try more official studio-tour/backlot/centennial sources rather than relying on one logo clip.


### v0.3.28 Narration-aware smart shot selection
- Resolve visual cuts now use ElevenLabs forced-alignment word timing and punctuation to prefer natural narration phrase/sentence boundaries instead of a fixed 5.5-second rhythm.
- Trailer reuse now favors scenes from noticeably different parts of the source, not merely any non-overlapping adjacent scene.
- Final narration beats are kept intact so the planner does not create tiny cleanup/flash cuts at the end of a sentence.
- Step 7 now warns when the selected downloaded moving footage is shorter than the narration window, making cases such as an 11-second title announcement for an 18-second story explicit before export.
- Scene selection still uses cached keyframe/scene analysis and never deliberately repeats the same source frames.


### v0.3.29 Cinema format writer/reviewer loop
- Cinema weekly research is now driven by a reusable 13-section format blueprint: Intro, Trends, Industry & Business, Upcoming Films, TV Series, Celebrities, AI & Tech, Viral Images, Box Office, Channel Polls, Now Available in HD, Toxic News, and Outro.
- Step 1 runs section-specific research intents instead of one generic cinema-news search. Intro, Outro, and Channel Polls are not fabricated from web research; polls require supplied channel data.
- Step 2 groups research by format section so the editor selects the news that belongs inside each part before narration writing.
- Step 3 is now a versioned Narration Writer workspace with a reusable cinema style-transcript library. Filmbaz transcripts are treated only as style/craft references for tone, pacing, section rhythm, transitions, density, and storytelling behavior; they are explicitly forbidden as factual authority for the current week.
- The narration workflow mirrors the Story Draft architecture in video-studio: Generate Fresh Draft → independent Reviewer → structured review gate → targeted revision → review again → explicit approval.
- Reviewer audits Format, Style, Factual/Source fidelity, and Storytelling. Drafts with blocking/major issues or any failed audit cannot be approved.
- Revisions use the reviewer feedback as the change list and preserve already-correct material instead of broadly restarting the draft.
- Only an approved narration is eligible for Voice preparation. Approved narration is preferred over newer unapproved experiments.
- Narration review files are stored under narration/reviews and review metadata is persisted in project.json.
- The format/style architecture is data-driven so Games and Music can later add their own section blueprints and transcript libraries without replacing the Writer/Reviewer engine.


### v0.3.30 Cinema section intelligence + social discovery
- Every recurring cinema section now has an explicit semantic contract: mission, included story types, excluded story types, evidence expectations, preferred source types, social-source policy, and target story count.
- AI ranking now also acts as a section-fit classifier. Stories are assigned by meaning rather than being permanently tied to whichever search query discovered them; weak-fit stories are downgraded instead of padding a section.
- Public social discovery is added for appropriate sections using web-indexed Reddit, X/Twitter, and TikTok URLs. Celebrity, Viral Images, Toxic News, AI/Tech, Trends, Upcoming Films, Industry, and Now Available use social discovery only where the section contract allows it.
- Social trust is explicit: a public X/TikTok post can be a primary-post candidate for what that account posted, but the app does not assume a discovered account is official. Reddit is discovery/community reaction and cannot by itself confirm an external factual claim unless the story is explicitly about Reddit reaction.
- Section Selection shows platform badges (News, X/Twitter, TikTok, Reddit), section-fit status, and a warning for Reddit-only stories.
- Step 2 now shows every cinema section, including zero-result sections, with a concise description of what belongs there and the expected story-count range. Missing coverage is visible instead of silently disappearing.
- Social platform matching uses exact hostname boundaries, preventing false matches such as netflix.com being mistaken for x.com.
- Public social discovery does not imply authenticated/private-feed access; logged-in-only, private, deleted, or non-indexed posts remain unavailable without a platform-specific authenticated integration.


### v0.3.31 Verified current-window research
- The cinema section blueprint now exposes a versioned Section Intelligence schema. Every researchable section carries: mission, include/exclude rules, evidence expectations, preferred source types, social-source policy, freshness policy, verification policy, and section-specific freshness examples.
- Freshness is tied to the PROJECT date window, not the computer clock. The window is date_start inclusive and date_end exclusive.
- Search intentionally widens the front edge by one day so providers with exclusive `after:` semantics do not miss the first selected date; deterministic filtering then labels every source as current, background, out_of_window, or undated.
- Every candidate story now stores a semantic `news_hook`: the specific new development that happened during the selected window. A recently published recap of an older event is stale unless it contains an actual new hook in the selected week.
- Older sources may be retained as background/context, but background and undated sources never count as freshness evidence.
- Story verification metadata now includes verification_status, verification_notes, temporal_gate, verification_gate, in-window/background/undated source counts, independent current-source count, current non-Reddit source count, and current primary-social-post candidate count.
- Verification rules are conservative: 2+ independent current non-Reddit sources can be verified; one current non-Reddit source is treated as reported unless stronger primary evidence is established; public X/TikTok discoveries do not automatically prove the account is official; Reddit-only external factual claims remain needs_verification.
- Step 2 shows the current-window hook, hook date when supported, freshness status, verification status, current/background source counts, and a per-source temporal badge/date.
- Include is disabled and the API rejects the action unless the story has: a current/follow-up status, a specific current-window news hook, at least one in-window source, a passing temporal gate, and a passing verification gate.
- The narration writer receives only stories that pass those gates. The narration reviewer now has a separate Freshness Audit and must catch any draft that turns older background context into this week's development.
- Existing research runs from older versions should be rerun once after upgrading; their old story rows intentionally do not inherit trust they never earned under the new freshness/verification schema.
