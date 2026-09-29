from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable

CINEMA_WEEKLY_FORMAT = [
    {
        "key": "intro",
        "label": "Intro",
        "research": False,
        "min_items": 0,
        "max_items": 0,
        "writer_role": "Short warm opening. Welcome the viewer and tease the strongest stories without giving away the whole episode.",
    },
    {
        "key": "trend",
        "label": "Trends",
        "research": True,
        "min_items": 1,
        "max_items": 2,
        "queries": [
            "movie film biggest trend this week box office record critics audience",
            "movie opening weekend record Rotten Tomatoes CinemaScore director interview",
        ],
        "writer_role": "The lead story. Go deeper than other sections: numbers, comparisons, reaction, controversy, release timing, and a useful follow-up thread when supported.",
    },
    {
        "key": "industry",
        "label": "Industry & Business",
        "research": True,
        "min_items": 1,
        "max_items": 3,
        "queries": [
            "Hollywood studio merger acquisition lawsuit regulator streaming business",
            "film studio finance executive deal antitrust production commitment",
        ],
        "writer_role": "Explain the behind-the-scenes power/business story and why it can matter to audiences.",
    },
    {
        "key": "upcoming_films",
        "label": "Upcoming Films",
        "research": True,
        "min_items": 3,
        "max_items": 8,
        "queries": [
            "upcoming movie first look official trailer casting release date director",
            "new film production starts festival reaction sequel announced first images",
        ],
        "writer_role": "The largest quick-news block. For each film: what changed this week, useful cast/director context, one-line premise when supported, and release timing.",
    },
    {
        "key": "tv_series",
        "label": "TV Series",
        "research": True,
        "min_items": 0,
        "max_items": 4,
        "queries": [
            "TV series streaming renewal cancellation delay showrunner Netflix HBO Apple Marvel",
            "streaming series strategy cancellation renewal premiere delay",
        ],
        "writer_role": "Cover renewals, cancellations, delays, showrunner changes, and platform strategy.",
    },
    {
        "key": "celebrities",
        "label": "Celebrities",
        "research": True,
        "min_items": 0,
        "max_items": 5,
        "queries": [
            "actor actress director filmmaker award honour museum event interview cinema celebrity",
            "Hollywood celebrity unusual incident press tour personal news film",
        ],
        "writer_role": "People-focused stories. Prefer a mix of significant events, personal news, unusual incidents, and entertaining anecdotes.",
    },
    {
        "key": "ai_tech",
        "label": "AI & Tech",
        "research": True,
        "min_items": 0,
        "max_items": 3,
        "queries": [
            "AI artificial intelligence film actor VFX Hollywood movie production",
            "cinema robot virtual actor generative AI film technology viral",
        ],
        "writer_role": "AI/technology stories relevant to film or entertainment. Add a concise reality check when reporting viral tech claims.",
    },
    {
        "key": "viral_images",
        "label": "Viral Images",
        "research": True,
        "min_items": 0,
        "max_items": 4,
        "queries": [
            "movie celebrity viral photo Instagram this week cinema",
            "actor director viral image photo award social media film",
        ],
        "writer_role": "Fast visual items. Keep each one short and explain why the image/post was notable.",
    },
    {
        "key": "box_office",
        "label": "Box Office",
        "research": True,
        "min_items": 1,
        "max_items": 6,
        "queries": [
            "weekend box office top 5 domestic worldwide total movie",
            "box office milestone studio record highest grossing this week",
        ],
        "writer_role": "A compact ranked rundown: top five when reliable data is available, plus one notable milestone outside the top five.",
    },
    {
        "key": "channel_polls",
        "label": "Channel Polls",
        "research": False,
        "min_items": 0,
        "max_items": 2,
        "writer_role": "Use only poll data explicitly supplied by the channel/user. Never invent poll percentages.",
    },
    {
        "key": "now_available",
        "label": "Now Available in HD",
        "research": True,
        "min_items": 0,
        "max_items": 4,
        "queries": [
            "movie digital release VOD streaming this week available now",
            "new movie PVOD digital HD release date this week",
        ],
        "writer_role": "Quick home-viewing availability. Say what became available and a one-line reason it may matter.",
    },
    {
        "key": "toxic_news",
        "label": "Toxic News",
        "research": True,
        "min_items": 0,
        "max_items": 3,
        "queries": [
            "Hollywood weird funny bizarre movie celebrity incident this week",
            "film director actor strange viral incident gossip cinema this week",
        ],
        "writer_role": "A light, funny closer. Only use well-sourced odd/embarrassing stories; the humor is in the telling, not invented facts.",
    },
    {
        "key": "outro",
        "label": "Outro",
        "research": False,
        "min_items": 0,
        "max_items": 0,
        "writer_role": "Brief goodbye/call to action. Do not attach a news STORY id.",
    },
]

PERSIAN_SECTION_LABELS = {
    "intro": "مقدمه",
    "trend": "ترندها",
    "industry": "صنعت سینما",
    "upcoming_films": "فیلم‌های جدید",
    "tv_series": "سریال‌ها",
    "celebrities": "سلبریتی‌ها",
    "ai_tech": "هوش مصنوعی و تکنولوژی",
    "viral_images": "تصاویر وایرال",
    "box_office": "گیشه",
    "channel_polls": "نظرسنجی‌ها",
    "now_available": "کیفیت خوب",
    "toxic_news": "خبرای سمی",
    "outro": "پایان",
}

SECTION_CONTRACTS = {
    "intro": {
        "mission": "Open the episode, establish the week, and tease the strongest current stories.",
        "include": ["short greeting", "episode hook", "brief tease of selected stories"],
        "exclude": ["new factual claims not present in selected news", "long setup", "news item that belongs in another section"],
        "evidence": ["approved episode selection only"],
        "preferred_sources": [],
        "social_sources": [],
    },
    "trend": {
        "mission": "Cover the single biggest conversation-driving cinema story of the week in more depth than any other section.",
        "include": ["major film trend", "box-office performance tied to the lead story", "critic/audience response", "controversy or production change", "director/star follow-up when directly connected"],
        "exclude": ["minor trailer announcements with little attention", "generic celebrity gossip", "unrelated box-office chart items"],
        "evidence": ["multiple reputable reports when possible", "official studio/filmmaker statements", "box-office/ratings data from attributable sources"],
        "preferred_sources": ["official studio/filmmaker", "trade press", "major entertainment press", "box-office/ratings sources"],
        "social_sources": ["x", "tiktok", "reddit"],
    },
    "industry": {
        "mission": "Explain studio, streaming, legal, regulatory, finance, executive, or labor stories and why they matter to audiences/production.",
        "include": ["mergers/acquisitions", "lawsuits/regulation", "studio finance", "executive moves", "platform strategy", "production commitments"],
        "exclude": ["ordinary casting", "celebrity personal life", "box-office chart unless it materially drives the business story"],
        "evidence": ["company/regulator filings or statements", "trade press", "reputable business reporting"],
        "preferred_sources": ["official company/regulator", "trade press", "major business press"],
        "social_sources": ["x"],
    },
    "upcoming_films": {
        "mission": "Cover meaningful developments for unreleased or newly announced films.",
        "include": ["official trailer/teaser", "first look", "casting", "production start", "festival/critic first reactions", "release date", "sequel/film announcement"],
        "exclude": ["TV-only stories", "old trailers resurfacing with no new development", "fan rumor with no reporting"],
        "evidence": ["official studio/filmmaker post", "trade press", "festival source", "reputable entertainment press"],
        "preferred_sources": ["official studio/filmmaker", "trade press", "festival", "major entertainment press"],
        "social_sources": ["x", "tiktok"],
    },
    "tv_series": {
        "mission": "Cover meaningful television/streaming-series developments.",
        "include": ["renewal", "cancellation", "delay", "premiere", "showrunner change", "platform strategy tied to a series"],
        "exclude": ["feature-film news", "celebrity-only personal news", "generic platform corporate news better suited to Industry"],
        "evidence": ["network/platform statement", "trade press", "reputable entertainment press"],
        "preferred_sources": ["official network/platform", "trade press", "major entertainment press"],
        "social_sources": ["x"],
    },
    "celebrities": {
        "mission": "People-focused cinema/entertainment news: significant events, honors, personal announcements, unusual incidents, and strong interview anecdotes.",
        "include": ["awards/honors", "museum/opening/event", "marriage/family announcement", "verified personal announcement", "detention/legal incident", "press-tour anecdote/interview", "notable public post"],
        "exclude": ["unsupported relationship gossip", "anonymous rumor presented as fact", "fan speculation", "appearance/health speculation"],
        "evidence": ["celebrity/representative's own public post", "verified interview", "official event/award source", "reputable entertainment reporting"],
        "preferred_sources": ["official X/TikTok/Instagram post", "direct interview", "official event", "reputable entertainment press"],
        "social_sources": ["x", "tiktok", "reddit"],
        "social_policy": "Own-account X/TikTok posts may be primary evidence for what the person posted. Reddit is discovery/reaction only unless the story itself is about Reddit reaction; corroborate factual claims elsewhere.",
    },
    "ai_tech": {
        "mission": "Cover AI/technology developments that meaningfully intersect with film, performers, production, VFX, or entertainment culture.",
        "include": ["AI actors", "generative production tools", "VFX/production tech", "robots/virtual performers when cinema-relevant", "viral tech demonstration with a reality check"],
        "exclude": ["general tech news with no entertainment connection", "obviously staged viral content presented as real"],
        "evidence": ["original demo/post", "company/research source", "reputable reporting", "independent reality-check source when needed"],
        "preferred_sources": ["original source", "company/research source", "reputable tech/entertainment press"],
        "social_sources": ["x", "tiktok", "reddit"],
    },
    "viral_images": {
        "mission": "Fast visual stories centered on a specific image/post that became notable during the week.",
        "include": ["celebrity/studio post", "award image", "on-set/photo reveal", "widely shared image with clear provenance"],
        "exclude": ["generic publicity still with no viral/news hook", "unverified repost", "appearance/health speculation"],
        "evidence": ["original social post preferred", "official account", "reputable reporting that embeds/identifies original post"],
        "preferred_sources": ["original X/TikTok/Instagram post", "official account", "reputable entertainment press"],
        "social_sources": ["x", "tiktok", "reddit"],
        "social_policy": "Prefer the original post. Reddit can show community reaction but should not replace the original image/post or independent verification.",
    },
    "box_office": {
        "mission": "Give the week's compact box-office rundown and one useful milestone.",
        "include": ["domestic weekend top five", "worldwide/total when notable", "days/weeks in release", "major milestone or studio record"],
        "exclude": ["unverified forecast presented as actual gross", "social-media estimates without a box-office source"],
        "evidence": ["recognized box-office reporting/data", "studio release when appropriate"],
        "preferred_sources": ["box-office data/reporting", "trade press"],
        "social_sources": [],
    },
    "channel_polls": {
        "mission": "Report the channel's own prior audience poll results.",
        "include": ["actual supplied poll results", "viewer count/sample when supplied", "good/average/bad split", "brief verdict"],
        "exclude": ["invented poll data", "third-party public polls substituted for channel polls"],
        "evidence": ["user/channel supplied poll data only"],
        "preferred_sources": ["channel data"],
        "social_sources": [],
    },
    "now_available": {
        "mission": "Tell viewers which relevant films became available for home viewing during the week.",
        "include": ["digital/PVOD/VOD release", "streaming availability", "brief premise/context"],
        "exclude": ["theatrical-only release", "rumored digital date without confirmation"],
        "evidence": ["platform/studio listing", "reputable release-date reporting"],
        "preferred_sources": ["official platform/studio", "reputable entertainment press"],
        "social_sources": ["x"],
    },
    "toxic_news": {
        "mission": "End the news portion with a light, weird, embarrassing, or absurd but still verifiable entertainment story.",
        "include": ["odd celebrity incident", "weird production/location story", "funny social-media mishap", "low-stakes verified gossip"],
        "exclude": ["serious allegation treated as a joke", "unverified rumor", "private-person harassment", "health/appearance speculation"],
        "evidence": ["primary public post when applicable", "reputable report", "official record/source for incidents"],
        "preferred_sources": ["original social post", "reputable entertainment press", "local/official source"],
        "social_sources": ["x", "tiktok", "reddit"],
        "social_policy": "Reddit can suggest a lead or provide reaction, but factual claims require a primary/reputable source before narration.",
    },
    "outro": {
        "mission": "Close briefly and invite engagement.",
        "include": ["short goodbye", "like/subscribe/comment call", "viewer submission prompt when desired"],
        "exclude": ["new news item", "unverified factual claim"],
        "evidence": ["none"],
        "preferred_sources": [],
        "social_sources": [],
    },
}

SECTION_INTELLIGENCE_SCHEMA_VERSION = 1

COMMON_FRESHNESS_POLICY = {
    "require_current_week_hook": True,
    "window_semantics": "date_start inclusive; date_end exclusive",
    "allow_followup": True,
    "background_sources_allowed": True,
    "background_sources_count_as_freshness": False,
    "undated_source_counts_as_freshness": False,
    "republished_old_story_rule": (
        "A source published inside the window is not enough by itself. The story must contain a "
        "specific new development inside the selected window. Pure recaps/reposts of an older event are stale."
    ),
}

COMMON_VERIFICATION_POLICY = {
    "reddit_role": "discovery_or_reaction_only",
    "social_account_rule": (
        "A discovered X/TikTok URL may support what that account posted, but discovery alone does not prove "
        "the account is official. Corroborate external factual claims."
    ),
    "cross_source_rule": "Prefer independent sources; syndicated copies do not count as independent confirmation.",
    "background_rule": "Background/context may use older sources but every current-week claim must trace to current evidence.",
    "include_gate": (
        "Include requires an in-window news hook plus verified/reported evidence. "
        "needs_verification, stale, date_unknown, or missing-hook stories stay Maybe/Skip."
    ),
}

SECTION_VERIFICATION_OVERRIDES = {
    "trend": {
        "verification_target": "Prefer 2 independent current sources; one authoritative primary source may establish a straightforward announcement, but performance/reaction claims should be corroborated.",
        "freshness_examples": ["new opening-weekend result", "new score/reaction", "new controversy/development", "new filmmaker statement tied to the lead story"],
    },
    "industry": {
        "verification_target": "Prefer an official company/regulator/legal source plus reputable trade/business reporting, or 2 independent reputable reports.",
        "freshness_examples": ["new filing", "new deal term", "new regulator action", "new executive move", "new labor/business decision"],
    },
    "upcoming_films": {
        "verification_target": "One clearly authoritative studio/filmmaker/festival announcement can establish the new hook; rumors require reputable corroboration.",
        "freshness_examples": ["new trailer", "new first look", "new casting", "production start", "festival reaction", "release-date change", "new sequel announcement"],
    },
    "tv_series": {
        "verification_target": "Prefer network/platform or trade confirmation for renewal/cancellation/delay/showrunner/premiere claims.",
        "freshness_examples": ["renewed this week", "cancelled this week", "new delay/premiere date", "new showrunner/platform decision"],
    },
    "celebrities": {
        "verification_target": "Direct verified interview/event/representative source is strongest. Personal social posts need account authenticity plus corroboration when the claim extends beyond what was visibly posted.",
        "freshness_examples": ["new award/honor", "new public announcement", "new interview anecdote", "new incident", "new event appearance"],
    },
    "ai_tech": {
        "verification_target": "Prefer original demo/company/research source plus independent reporting for capability claims or viral demonstrations.",
        "freshness_examples": ["new demo", "new production use", "new policy/tool announcement", "new viral tech incident with a verified reality check"],
    },
    "viral_images": {
        "verification_target": "Prefer the original dated post/image. Reposts and screenshots need provenance; Reddit reaction does not establish image origin.",
        "freshness_examples": ["original image/post published in the selected week", "new award/on-set/photo reveal that became notable this week"],
    },
    "box_office": {
        "verification_target": "Use recognized current box-office reporting/data. Forecasts and actuals must be labeled separately.",
        "freshness_examples": ["current weekend chart", "new running total", "new milestone reached during the selected week"],
    },
    "now_available": {
        "verification_target": "Prefer official platform/studio availability or reputable release-date reporting.",
        "freshness_examples": ["digital/PVOD/VOD/streaming availability that begins during the selected week"],
    },
    "toxic_news": {
        "verification_target": "Low-stakes does not mean low-evidence: verify the incident/post through a primary or reputable source; Reddit-only gossip cannot be narrated as fact.",
        "freshness_examples": ["new odd incident", "new public social mishap", "new location/production anecdote reported during the selected week"],
    },
}

for _section in CINEMA_WEEKLY_FORMAT:
    _section.update(SECTION_CONTRACTS.get(_section["key"], {}))
    _section["freshness_policy"] = dict(COMMON_FRESHNESS_POLICY)
    _section["verification_policy"] = {
        **COMMON_VERIFICATION_POLICY,
        **SECTION_VERIFICATION_OVERRIDES.get(_section["key"], {}),
    }

FORMAT_BY_KEY = {item["key"]: item for item in CINEMA_WEEKLY_FORMAT}
RESEARCH_SECTIONS = [item for item in CINEMA_WEEKLY_FORMAT if item.get("research")]
SECTION_ORDER = {item["key"]: index for index, item in enumerate(CINEMA_WEEKLY_FORMAT)}


# Spoken pace used to turn the project's target minutes into a word budget.
# Conversational Persian narration runs roughly 130-150 words per minute.
SPOKEN_WORDS_PER_MINUTE = {"persian": 140, "farsi": 140}
DEFAULT_WORDS_PER_MINUTE = 150


def _words_per_minute(language: str) -> int:
    return SPOKEN_WORDS_PER_MINUTE.get(str(language or "").strip().casefold(), DEFAULT_WORDS_PER_MINUTE)


def narration_word_count(text: str) -> int:
    body = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    body = re.sub(r"(?m)^\s*#+\s.*$", " ", body)
    body = re.sub(r"\[[^\]]{1,40}\]", " ", body)  # ElevenLabs performance tags
    return len(re.findall(r"[^\s\u200c]+(?:\u200c[^\s\u200c]+)*", body))


def length_target(project: dict, draft_text: str | None = None) -> dict:
    minutes = float(project.get("target_minutes") or 0) or 0.0
    wpm = _words_per_minute(project.get("language") or "")
    target_words = int(round(minutes * wpm))
    result = {
        "target_minutes": minutes,
        "spoken_words_per_minute": wpm,
        "target_words": target_words,
        "acceptable_words": [int(round(target_words * 0.85)), int(round(target_words * 1.10))],
        "rule": (
            "Aim for acceptable_words by using more of the supported beats and selected stories. "
            "Never pad with filler; if the approved evidence cannot fill the range, a shorter draft is acceptable."
        ),
    }
    if draft_text is not None:
        words = narration_word_count(draft_text)
        result["current_draft_words"] = words
        result["current_draft_minutes"] = round(words / wpm, 1) if wpm else 0.0
    return result


def section_label(key: str) -> str:
    return (FORMAT_BY_KEY.get(key) or {}).get("label") or key.replace("_", " ").title()


def research_query_groups() -> list[tuple[str, str]]:
    groups: list[tuple[str, str]] = []
    for section in RESEARCH_SECTIONS:
        for query in section.get("queries") or []:
            groups.append((section["key"], query))
    return groups


def format_packet() -> list[dict]:
    return [
        {
            "key": item["key"],
            "label": item["label"],
            "spoken_label_fa": PERSIAN_SECTION_LABELS.get(item["key"], item["label"]),
            "research": bool(item.get("research")),
            "min_items": int(item.get("min_items") or 0),
            "max_items": int(item.get("max_items") or 0),
            "writer_role": item.get("writer_role") or "",
            "mission": item.get("mission") or "",
            "include": item.get("include") or [],
            "exclude": item.get("exclude") or [],
            "evidence": item.get("evidence") or [],
            "preferred_sources": item.get("preferred_sources") or [],
            "social_sources": item.get("social_sources") or [],
            "social_policy": item.get("social_policy") or "",
            "freshness_policy": item.get("freshness_policy") or {},
            "verification_policy": item.get("verification_policy") or {},
            "intelligence_schema_version": SECTION_INTELLIGENCE_SCHEMA_VERSION,
        }
        for item in CINEMA_WEEKLY_FORMAT
    ]


def _distributed_style_excerpt(text: str, allowance: int) -> str:
    """Sample the full transcript evenly so every reference contributes structure.

    We deliberately avoid taking only the opening/middle/end. Filmbaz-style
    section rhythm often changes across Trends, quick-news runs, box office,
    viral/celebrity items, and the closer, so evenly spaced windows preserve
    more of the episode's craft within a bounded prompt budget.
    """
    text = str(text or "").strip()
    if not text or allowance <= 0:
        return ""
    if len(text) <= allowance:
        return text

    windows = 6 if allowance >= 2400 else 4
    chunk_size = max(160, allowance // windows)
    usable = max(1, len(text) - chunk_size)
    parts: list[str] = []
    for index in range(windows):
        ratio = index / max(1, windows - 1)
        start = int(usable * ratio)
        excerpt = text[start:start + chunk_size].strip()
        if excerpt:
            parts.append(excerpt)
    joined = "\n... [distributed style sample] ...\n".join(parts)
    return joined[:allowance]


def _contiguous_style_excerpt(text: str, allowance: int, offset_ratio: float = 0.0) -> str:
    """Preserve a long uninterrupted stretch so the model can see real spoken flow."""
    text = str(text or "").strip()
    if not text or allowance <= 0:
        return ""
    if len(text) <= allowance:
        return text
    start = int(max(0.0, min(1.0, offset_ratio)) * max(0, len(text) - allowance))
    return text[start:start + allowance].strip()


def style_corpus_hash(transcripts: Iterable[dict]) -> str:
    enabled = [dict(item) for item in transcripts if int(item.get("enabled", 1) or 0)]
    payload = [
        {
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "content": str(item.get("content") or ""),
            "updated_at": str(item.get("updated_at") or ""),
        }
        for item in enabled
        if str(item.get("content") or "").strip()
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


GARBLED_UNIQUE_WORD_SHARE = 0.25
_REFERENCE_DATE_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)")


def reference_date(name: str) -> str:
    """YYYY-MM-DD found in a transcript's name (e.g. an upload date), or ''."""
    match = _REFERENCE_DATE_RE.search(str(name or ""))
    return "-".join(match.groups()) if match else ""


def annotate_style_quality(transcripts: Iterable[dict]) -> list[dict]:
    """Flag transcripts that look like garbled automatic transcription.

    Signal: share of a transcript's words that occur in no other transcript.
    Clean speech reuses the corpus vocabulary (roughly 5-10% unique words);
    broken ASR invents non-words (well above 25%). Needs at least 4
    transcripts to compare against, otherwise nothing is flagged.
    """
    rows = [dict(item) for item in transcripts]
    tokenized = [re.findall(r"[^\W\d_]+", str(row.get("content") or "").casefold()) for row in rows]
    document_frequency: dict[str, int] = {}
    for tokens in tokenized:
        for token in set(tokens):
            document_frequency[token] = document_frequency.get(token, 0) + 1
    comparable = sum(1 for tokens in tokenized if tokens) >= 4
    for row, tokens in zip(rows, tokenized):
        share = (sum(1 for token in tokens if document_frequency.get(token, 0) <= 1) / len(tokens)) if tokens else 0.0
        row["unique_word_share"] = round(share, 3)
        row["likely_garbled"] = bool(comparable and share > GARBLED_UNIQUE_WORD_SHARE)
        row["reference_date"] = reference_date(row.get("name") or "")
    return rows


def usable_style_transcripts(transcripts: Iterable[dict]) -> list[dict]:
    return [row for row in transcripts
            if int(row.get("enabled", 1) or 0) and str(row.get("content") or "").strip()
            and not row.get("likely_garbled")]


def style_rows_for_window(transcripts: Iterable[dict], date_start: str) -> list[dict]:
    """Drop references dated on/after the episode's first day: they may cover
    the same news the episode is about, and their facts must never leak in."""
    start = str(date_start or "")[:10]
    return [row for row in transcripts
            if not (start and row.get("reference_date") and str(row["reference_date"]) >= start)]


def build_style_packet(transcripts: Iterable[dict], max_chars: int = 120000) -> str:
    enabled = usable_style_transcripts(transcripts)
    if not enabled:
        return "<style_corpus>No usable style transcripts are available for this episode.</style_corpus>"

    # Two complementary views are useful:
    # 1) every transcript contributes distributed samples, so the model learns
    #    recurring habits instead of one episode's quirks;
    # 2) a few long contiguous anchors preserve the actual minute-to-minute flow
    #    that gets destroyed when everything is chopped into small excerpts.
    anchor_count = min(3, len(enabled))
    anchor_budget = min(45000, max(9000, int(max_chars * 0.38)))
    distributed_budget = max(12000, max_chars - anchor_budget)
    per_item = max(350, distributed_budget // max(1, len(enabled)))

    chunks = [
        "<style_corpus>",
        "STYLE REFERENCES ONLY. Never treat facts, dates, names, numbers, claims, or opinions in these transcripts as factual authority for the current episode.",
        "Learn recurring spoken behavior: oral register, story expansion, sentence rhythm, causal connectors, mini-explanations, familiarity context, playful asides, transitions, section pacing, and how concrete facts are turned into a small story.",
        "The packet contains both distributed corpus samples and longer uninterrupted FLOW ANCHORS. Flow anchors are present specifically so you can see how the host moves through several minutes without sounding like article summaries.",
        "Do not copy distinctive sentences verbatim. Reproduce recurring craft and conversational behavior.",
        "References may contain automatic-transcript spelling, punctuation, or recognition errors. Learn the spoken rhythm and structure; do NOT imitate ASR mistakes.",
        "Prefer patterns repeated across the corpus over a one-off quirk.",
        "<distributed_samples>",
    ]
    for item in enabled:
        text = str(item.get("content") or "").strip()
        excerpt = _distributed_style_excerpt(text, per_item)
        chunks.extend([
            f'<style_transcript name={json.dumps(item.get("name") or "Transcript")} chars={len(text)}>',
            excerpt,
            "</style_transcript>",
        ])
    chunks.append("</distributed_samples>")

    anchors = sorted(enabled, key=lambda item: len(str(item.get("content") or "")), reverse=True)[:anchor_count]
    if anchors:
        chunks.append("<flow_anchors>")
        anchor_each = max(2500, anchor_budget // len(anchors))
        offsets = (0.04, 0.34, 0.64)
        for index, item in enumerate(anchors):
            text = str(item.get("content") or "").strip()
            excerpt = _contiguous_style_excerpt(text, anchor_each, offsets[index % len(offsets)])
            chunks.extend([
                f'<flow_anchor name={json.dumps(item.get("name") or "Transcript")} chars={len(text)}>',
                excerpt,
                "</flow_anchor>",
            ])
        chunks.append("</flow_anchors>")

    chunks.append("</style_corpus>")
    return "\n".join(chunks)


STYLE_PROFILE_SYSTEM = """You are a style director. Distill a reusable spoken-writing blueprint from the supplied reference transcripts.

The references are STYLE ONLY, never factual authority. Do not preserve their movie names, dates, numbers, claims, opinions, or news as usable facts. They may contain ASR/transcription mistakes: infer spoken craft, but never treat misspellings or recognition errors as part of the desired style.

Your profile must describe recurring craft rather than generic advice. Pay special attention to:
- how colloquial Persian differs from polished written Persian;
- how a story grows from headline -> explanation -> specific detail -> aside/payoff;
- how the host explains unfamiliar concepts or reminds viewers where they know a person from;
- causal connectors and mini turns such as "حالا", "ولی", "برای همین", "یعنی", "مشکل اینجاست", "جالبش اینجاست" and how often they are naturally varied;
- when rhetorical questions are useful;
- how humor/irony comes from a fact rather than fake hype;
- how stories transition into one another without sounding like database rows;
- how long/deep a normal item, a quick item, and a lead item feel;
- how release/platform/date information is placed;
- how box-office/list sections speed up;
- what would make a draft sound like a formal entertainment-news article or an AI news presenter instead of this host.

Return Markdown using exactly these headings:
# Voice & Register
# Story Micro-Arc
# Rhythm & Connectors
# Explanation & Familiarity
# Humor & Asides
# Transitions & Section Flow
# Depth & Pacing
# Anti-Patterns
# Reviewer Checklist

Be concrete enough that another writer can follow it without seeing the transcripts. Do not quote more than a few common connective words from the references.
"""


CONTENT_PLAN_SYSTEM = """You are the factual story architect for a spoken weekly cinema-news episode.

Use ONLY the supplied approved current-week packet and its verified_claim_ledger. Do not use outside knowledge or the style references.

Return ONLY valid JSON:
{
  "intro_hooks": ["note"],
  "sections": [
    {
      "section": "key",
      "stories": [
        {
          "id": "story id (join several ids with + when they are one event)",
          "depth": "lead|normal|quick",
          "headline_hook": "note",
          "setup": ["note"],
          "familiarity": ["note"],
          "interesting_details": ["note"],
          "why_it_matters": ["note"],
          "optional_spice": ["note"],
          "ending_fact": "note",
          "bridge_hint": "note"
        }
      ]
    }
  ]
}

HOW TO WRITE NOTES (this plan is raw material, not the script):
- Write every note as a terse ENGLISH fact note, never a finished sentence and never Persian. The writer composes the spoken Persian from scratch; prose here gets copied and makes the script sound written.
- End every factual note with the ledger id(s) that support it, e.g. "Encore opening weekend: ~$86M worldwide [C002]". A note without a supporting verified ledger id must not exist.
- Keep scope inside the note itself (market, period, estimate). Mark attribution only as "(estimate)" or "(attrib: <outlet>, conflicting)" when the ledger claim has attribution_required=true. Do not add outlet names otherwise.
- Never write disclaimers, "not specified", "evidence does not show", or any note about what is unknown. If something is unknown, leave it out.
- Round volatile figures only in the writer, not here: copy ledger values exactly.

WHAT TO PLAN:
- Extract as many genuinely useful supported beats as the packet provides. Do not compress a rich source packet into two facts; article descriptions and excerpts are the richest source of setup, premise and detail.
- headline_hook: the concrete current-week development.
- setup: only context a casual viewer needs to follow the hook.
- familiarity: the recognition cue for a non-obvious central person/company, only when a verified person_credit ledger claim supports it.
- interesting_details: premise, numbers, contrasts, production or reaction details that make the item a small story.
- why_it_matters: a concrete consequence stated in the evidence that is DIFFERENT from the hook (who it affects and how). If there is none, return an empty list; never restate the hook or write generic importance.
- optional_spice: only safe_to_narrate angles that map to verified ledger claims.
- depth: lead for the week's biggest story, quick when evidence is thin. Never invent filler to reach a length.
- Merge several story ids into one planned item only when they clearly describe the same film/event; keep every id in "id".
- SOURCE DATE IS NOT EVENT DATE: a current article can mention an older figure; never plan it as the current value. Use the latest reliable in-window value for "now/has reached" notes; never plan "approaching" when a later source shows the milestone was crossed.
- Keep rumors marked as rumor and social reaction tied to its platform and scale.
"""


ATTRIBUTION_POLICY = """
ATTRIBUTION POLICY (single shared rule for writer, reviser, fact checker and reviewer):
- Speak a source or estimate marker ONLY for ledger claims with attribution_required=true. Never add source names to other facts (cast, trailers, titles, announcements).
- DEFAULT: a light marker in the same sentence, not an outlet name: "حدود"، "تقریباً"، "طبق برآوردها"، "طبق گزارش‌ها"، "گفته می‌شه". Most viewers do not know trade outlets; a string of outlet names sounds like a news agency.
- Name an outlet ONLY when figures from different outlets conflict, when the claim is an exclusive or still-unconfirmed report, or when the outlet itself is part of the story. Then name it once, naturally ("ورایتی می‌گه...").
- Across the whole episode, name outlets rarely (aim for at most 2-3 in total). Never name the same outlet twice in one story; never open consecutive sentences with a source.
- Reviewers must NOT flag required attribution as a style problem. Flag attribution added where the ledger does not require it, outlet names where a light marker would do, repeated outlets, or a required marker that is missing.
"""


SPOKEN_QUALITY_RULES = """
SPOKEN QUALITY RULES (shared by writer, reviser, enrichment writer and fact checker):
- Never speak pipeline language. No "in the available evidence/sources", "it is not specified", "the data does not show", ledger/audit/verification talk, or any variant («در شواهد موجود»، «مشخص نشده»، «در منابع موجود»). If a detail is unknown, simply leave it out.
- State a figure's scope once, inside the sentence that gives the figure ("در آخرهفتهٔ افتتاحیه حدود ... فروخت"). Never add a separate sentence that only restates or clarifies scope ("این رقم مربوط به ... است"، "نه فروش کل ..."، "رقمی که دقیقاً مربوط به ...").
- Speak numbers the way a host says them: round to natural spoken precision within the ledger value ("حدود ۱۰۸ میلیون دلار"، "نزدیک ۲ میلیارد و ۹۰۰ میلیون دلار"). Avoid decimals unless the decimal itself is the point.
- Keep ONE spoken register for the whole episode. In Persian use conversational forms consistently («رو» not «را»، «داره» not «دارد»، «اومده» not «آمده»، «ـه/هست» not «است»، «شدن» not «شده‌اند»). Names, titles and exact numbers stay as they are.
- Organization, guild and union names: say them in plain Persian description when a transliteration would be unfamiliar or would sound like another name or word in the same passage. Never let two different organizations sound alike within one story.
- Greeting: use the channel name from project.channel_name only when it is set; otherwise greet without a channel name. Never borrow a channel name from the style references.
- Every sentence must add a new beat. Do not recap what was just said ("پس ... هم ..." summaries), and do not end an item with low-value evaluation ("اطلاعات بدی نیست"، "جالبه").
"""


FACT_CHECK_SYSTEM = """You are the final factual freshness auditor for a weekly cinema-news narration.

You receive:
1. the approved story packet and its dated source snippets,
2. a small fresh verification supplement gathered immediately before this audit,
3. the completed narration draft.

Your job is NOT to rewrite the style. Your job is to make every hard factual claim accurately scoped and current enough for the selected weekly window.

Return ONLY valid JSON:
{
  "status": "pass|corrected|needs_human_check",
  "issue_count": 0,
  "issues": [
    {
      "story_id": "...",
      "claim": "exact or concise description of the problematic draft claim",
      "problem": "what is wrong/stale/overstated",
      "correction_basis": "what the supplied evidence supports instead"
    }
  ],
  "corrected_narration": "complete narration markdown"
}

STRICT RULES:
- Use ONLY the supplied evidence. Do not use memory or outside facts.
- The supplied verified_claim_ledger is the structured factual boundary. A correction must remain semantically equivalent to a verified ledger claim. If fresh evidence reveals a correction that is not represented in the ledger, do not improvise it: mark needs_human_check so the ledger can be rebuilt.
- A blocked ledger claim cannot be narrated.
- For verified_with_attribution ledger claims, preserve explicit attribution/estimate/conflict framing.
- Preserve wording/style/structure unless a factual correction is needed.
- A corrected sentence must use the same spoken register as the surrounding draft and must not add hedges, disclaimers or pipeline language.
- Every number must keep its scope: domestic vs international vs worldwide; weekend-only vs cumulative total; opening weekend vs current total; estimate/projection vs final/actual.
- A source published this week may mention an OLDER event or subtotal. Publication date does not make every number inside it a current-week value.
- BOX OFFICE IS VOLATILE. If a film opened last weekend and the draft is being written after its second weekend, an opening-weekend worldwide number must be called an opening-weekend number, never phrased as the film's current worldwide total.
- Prefer the latest reliable in-window evidence for cumulative totals/rankings. If later supplied evidence says a milestone has already been crossed, reject wording such as "approaching" or "close to".
- In fresh_verification_sources, prefer trust_tier=preferred over supplemental search results when they conflict. Supplemental results can corroborate/discover, but should not override a preferred official/data/trade/major-news source.
- deterministic_red_flags are backend-detected high-confidence contradictions. You MUST address every listed red flag explicitly in issues and correct the narration when the supplied fresh evidence supports the correction. Never return pass while a deterministic_red_flag remains unresolved.
- Distinguish weekend rank from daily rank and domestic rank from worldwide rank.
- Also distinguish WEEKLY domestic chart from WEEKEND domestic chart. A title can be absent from the latest completed weekly chart yet rank #1 on a later weekend that falls inside the project window.
- Never let vague wording such as "this week topped the chart", "went straight to #1", "صدر جدول این هفته", or "رتبه اول" survive unless the exact chart scope is clear from the sentence: daily / weekend / weekly, domestic / worldwide, and the relevant date window when needed.
- fresh_verification_sources include query_scope. For ranking claims, compare like with like: weekly_domestic evidence cannot directly prove weekend_domestic rank and vice versa.
- RELEASE SCOPE matters. A limited, special-format, festival or event theatrical run is not the same as a general/wide theatrical release.
- DEAL VALUES can use different valuation conventions. If supplied reputable sources conflict (for example equity value vs enterprise/transaction value), keep attribution and do not flatten them into one unqualified number.
- If two supplied sources conflict and the difference cannot be reconciled from the packet, do not guess. Qualify the claim or mark needs_human_check.
- Do not silently delete the STORY marker for a corrected claim.
- Do not add a fact simply because it would make the narration better.
- If no factual correction is needed, corrected_narration must exactly preserve the supplied draft.
""" + ATTRIBUTION_POLICY + SPOKEN_QUALITY_RULES


WRITER_SYSTEM = """You are the narration writer for a weekly cinema-news YouTube show. You write the words one host will say on camera.

INPUTS
1. APPROVED CURRENT-WEEK NEWS with its VERIFIED CLAIM LEDGER: the ONLY factual authority for this episode.
2. CONTENT PLAN: terse English fact notes tagged with ledger ids. It is raw material. Retell it in your own spoken words; never translate the notes line by line.
3. FORMAT BLUEPRINT: what each section is for.
4. STYLE BLUEPRINT and STYLE CORPUS: how the host talks. Voice and flow only, never facts.

PRIORITIES, in order: (1) every fact is supported, (2) it sounds like one person talking, (3) each item is a small story worth hearing, (4) it fills the length target.

1. FACTS
- VERIFIED CLAIM LEDGER IS THE HARD FACTUAL BOUNDARY. Every externally checkable statement must be supported by a verified/verified_with_attribution ledger claim for that STORY id. Never use a blocked claim. If a useful fact is missing, leave it out; never fill it from memory or inference.
- Never import a fact, number, date, quote, opinion, event, cast detail, score, rumor, or release date from the style corpus.
- Each story is about its news_hook. Older background may explain it but is never presented as this week's development; a fresh article can quote an old number.
- A figure keeps its ledger scope (market, period, opening vs cumulative, estimate, release type, title identity), stated once inside the sentence that gives it. A ranking always names its chart ("در جدول آخرهفتهٔ آمریکای شمالی ... رتبهٔ اول"). Weekly, weekend and daily charts are different datasets. A limited or special-format run is not a wide release.
- Attribution follows the ATTRIBUTION POLICY below; mention sources aloud only as it allows or when the source itself is part of the story.
- STORY SPICE RULE: use only spice_angles with safe_to_narrate=true. Weave the strongest 1 into a quick item and up to 2-3 into the lead story. If there are no strong supported angles, do not pretend there are.
- RUMORS: only from a safe type=rumor angle, always framed as unconfirmed ("فعلاً در حد شایعه‌ست..."، "گزارش‌ها می‌گن..."), never replacing the verified hook. SOCIAL REACTION names its real platform and scale ("توی ردیت بعضی از کاربرا...") and never implies consensus. Critic reaction only from type=critic_reaction.
- Keep every factual paragraph traceable with <!-- STORY:<id> --> immediately before the sentences it supports. Intro and Outro have no STORY id. Story ids are evidence boundaries, not paragraph boundaries: items about the same film/event become one flowing item with each marker kept next to its claims.
- Omit any format section without approved material (except Intro/Outro). Do not revive skipped stories.

2. VOICE
- This is a SPOKEN TRANSCRIPT, not entertainment journalism. Follow the STYLE BLUEPRINT first and the corpus flow anchors second: a host telling the week to a friend, in natural colloquial Persian, never "corrected" into written Persian.
- Let the host reason out loud when it helps ("یعنی..."، "برای همین..."، "مشکل اینجاست..."، "حالا چرا این جالبه؟"). These are tools, varied naturally, not catchphrases. Rhetorical questions are fine when they set up a real answer.
- Humor and interest come from actual contrasts and odd facts, never from empty adjectives ("عجیب"، "خفن"، "سنگین"، "کنجکاوی‌برانگیز") or fake excitement.
- No abstract stakes ("برای مخاطب مهمه چون...") without a concrete supported consequence; no ceremonial setups; no placeholder endings ("حالا باید دید..."، "باید زیر نظرش داشت") unless the evidence leaves a concrete open question. End an item on its strongest detail.
- Transitions come from the content ("حالا که..."، "از این یکی بگذریم..."), not "خبر بعدی" or "اما می‌رسیم به..." every time. Vary sentence length; connected spoken chains are fine.
- Section headings are quiet metadata for the app: use the supplied spoken_label_fa values and never output English headings inside a Persian narration. The prose under them flows without announcing the template.
- NAMES READ ALOUD: the script is voiced by text-to-speech. Transliterate each foreign name once and spell it identically every time; add short-vowel marks (اعراب) to a name whose bare spelling could be read as ordinary words. Keep film/series titles in their official form.
- The greeting uses the channel name from project.channel_name only when it is set; otherwise greet without a channel name. Never borrow a channel name from the style references.

3. STORYTELLING
- STORY MICRO-ARC: a normal item moves through its supported beats: concrete hook -> just enough setup -> the most interesting detail or contrast -> optional explanation/familiarity -> supported aside or reaction -> practical ending fact. Pacing: lead story roughly 6-10 beats, normal 4-7, quick 2-4, only as far as the evidence goes.
- Lead with the strongest concrete hook. Make it interesting because the facts are interesting.
- A cast list by itself is not a payoff: use premise, creator context, production detail, history or reaction to show why the names matter.
- CASUAL-AUDIENCE FAMILIARITY RULE: on the first important mention of a person or company a general viewer may not place, give the story's familiarity cue once, as a short natural reminder ("<name>، همون <role> که احتمالاً از <best-known work> می‌شناسیدش"), only when a ledger claim supports it. Do not turn it into a biography, do not stack credits, skip it for household names, and never invent an anchor.
- FUN-FACT BEAT: a strong safe cool_fact that has a matching visual_context item gets one short self-contained sentence, so the editor can give it one shot. Related-work mentions from visual_context may name that title naturally.
- Box office is a compact rundown with movement and comparison, not separate paragraphs that each restate a title. Business stories are explained in plain language, only as much as a viewer needs.
- The INTRO teases this episode's most intriguing concrete hooks, never a template line that fits any week. The OUTRO is brief.

4. LENGTH
- The packet's length_target gives the spoken word budget. Reach acceptable_words by telling supported beats more fully and covering every selected story, never with filler. If the evidence cannot fill it, stay shorter.

Return only the complete narration in Markdown.
""" + ATTRIBUTION_POLICY + SPOKEN_QUALITY_RULES


REVIEWER_SYSTEM = """You are the independent editor of a weekly cinema-news YouTube show. Decide whether this narration draft is ready to be voiced, and if not, give the writer the shortest list of concrete fixes that gets it there.

WHAT YOU RECEIVE
- The approved current-week packet, its VERIFIED CLAIM LEDGER and the NARRATION CLAIM AUDIT (a sentence-by-sentence check of the draft against the ledger, already done by code).
- The format blueprint, length_target and spoken_lint findings (measured by code).
- The STYLE BLUEPRINT and style corpus. The style corpus is never factual authority: use it only to compare voice and flow; never ask the writer to copy its wording or facts.

HOW TO JUDGE FACTS
- automatic_fact_check is the fresh-evidence fact check. If its status is needs_human_check, every issue it lists that is still present in the draft is a blocking issue.
- The claim audit is the fact gate. Every blocked audit claim is a blocking issue: quote it and give the fix (remove it, or reword it to match the ledger claim it should map to).
- Beyond the audit, raise a factual issue only when you can point to the exact draft sentence and the exact ledger claim or source that contradicts it: wrong scope (opening vs cumulative, weekend vs weekly, domestic vs worldwide, estimate vs final, limited vs wide release), an older figure presented as current, a milestone called "approaching" after it was crossed, a background fact presented as this week's news, a fact under the wrong STORY marker, or a story that does not narrate its news_hook.
- Never ask the writer to add a fact that is not a verified ledger claim or a safe_to_narrate spice angle; name the ledger id or angle you want used.

SEVERITY (use these definitions exactly)
- blocking: the listener would hear something false, unsupported, stale-as-current or attributed to the wrong story; or a blocked audit claim; or a missing/incorrect STORY marker that breaks traceability.
- major: a problem a viewer would feel across a whole item or the episode:
  - OVER-COMPRESSION: a story with several supported beats (incl. its excerpts, spice and familiarity cue) reduced to a headline summary; a headline-summary draft should be NEEDS_WORK in Style;
  - FORMAL WRITTEN-PERSIAN DRIFT across an item, or pipeline language spoken aloud;
  - generic AI/news-presenter phrasing, empty hype or EMPTY ADJECTIVE PAYOFFS ("ترکیب سنگینی جمع شده"، "اتفاق بزرگیه") carrying an item instead of a concrete detail;
  - items that start, summarize and stop like database cards with no bridges;
  - more outlet names than the ATTRIBUTION POLICY allows, or scope-disclaimer sentences;
  - a selected story omitted; the lead story shallower than quick items; LENGTH below length_target.acceptable_words while supported material is unused, or more than 15% over it;
  - a CASUAL-AUDIENCE FAMILIARITY cue missing when a verified ledger claim supports it, or a biography/credit dump instead of one short cue;
  - a strong safe_to_narrate spice angle ignored where it would clearly lift a flat story, or spice that is invented/overstated (rumor stated as fact, one post presented as consensus, fans presented as critics, a platform not named).
- minor: one awkward phrase, one repeated connector, a small rhythm or word-choice improvement, a single name missing vowel marks. Minor issues never fail an audit.

AUDIT STATUS: an audit is NEEDS_WORK only if it contains at least one blocking or major issue in its area; otherwise PASS, even with minor notes.
RECOMMENDATION: REVISION_REQUIRED if any blocking or major issue exists; POLISH_OPTIONAL if only minor issues exist; PASS if none.

WHAT GOOD LOOKS LIKE (compare against the STYLE BLUEPRINT and the full style corpus)
- One host talking to a friend in natural colloquial Persian, one consistent register, varied sentence length.
- Each item is a small story: concrete hook, just enough setup, the most interesting detail or contrast, a short explanation or familiarity cue where needed, a supported aside, an ending fact. The lead story breathes; quick sections move fast; box office is a compact comparative rundown.
- Natural connectors ("حالا"، "یعنی"، "برای همین"، "جالبش اینجاست") are fine; penalize only mechanical repetition that adds no new beat.
- Transitions come from the content; the intro teases this week's concrete hooks; the outro is brief; headings use the Persian spoken labels.
- Names are spelled consistently and carry vowel marks where text-to-speech could misread them.
- Confirm spoken_lint findings against the text before reporting them; do not report a lint finding that is wrong.

HOW TO WRITE ISSUES
- At most 8 issues, most severe first. Merge repeats of the same problem into one issue that lists every place.
- Problem: quote the exact draft sentence(s) in «» and say what is wrong in one or two sentences.
- Fix: give a concrete rewrite in spoken Persian when it is a wording problem, or name the exact ledger id / spice angle to use or the sentence to delete. Never "make it more engaging" without saying how.
- Never ask for required attribution to be removed, for disclaimers to be added, or for anything the ATTRIBUTION POLICY or SPOKEN QUALITY RULES forbid.

Return Markdown using exactly this structure:

# Review Summary
First line: "Ready to voice: yes" or "Ready to voice: no". Then two or three sentences on the draft's biggest strength and biggest problem.

# Keep
Up to five lines or choices that already work and must survive revision (quote them in «»).

# Format Audit
- Status: PASS | NEEDS_WORK
- Notes: section fit, story coverage, lead depth, length vs length_target.

# Style Audit
- Status: PASS | NEEDS_WORK
- Notes: spoken register, over-compression, connectors, humor from facts, names, spoken_lint.

# Factual / Source Audit
- Status: PASS | NEEDS_WORK
- Notes: claim audit result and any additional scope/source problems.

# Freshness Audit
- Status: PASS | NEEDS_WORK
- Notes: news hooks narrated as this week's development; no stale value presented as current.

# Context / Spice Audit
- Status: PASS | NEEDS_WORK
- Notes: spice used correctly; strong safe_to_narrate spice angle missed or misused; familiarity cues.

# Storytelling Audit
- Status: PASS | NEEDS_WORK
- Notes: micro-arcs, bridges, intro hook, endings.

# Issues
For each issue:
## ISSUE N — short title
- Severity: blocking | major | minor
- Section: section name
- Problem: exact problem with quoted text
- Fix: concrete revision

If there are no issues, write: None.

# Review Gate
- Blocking Issues: N
- Major Issues: N
- Minor Issues: N
- Recommendation: PASS | REVISION_REQUIRED | POLISH_OPTIONAL
""" + ATTRIBUTION_POLICY + SPOKEN_QUALITY_RULES


ENRICHMENT_REWRITE_SYSTEM = """You are the enrichment rewrite writer inside YT News Studio.

You receive the existing first draft plus the same approved current-week stories, the distilled Style Blueprint/reference anchors, and some per-story context searches collected AFTER the draft.

Do not restart the episode from scratch. Preserve the useful structure, facts, section order, STORY markers, and lines that already work. Enrich only the stories where the newly collected evidence genuinely improves the narration.

Rules:
- VERIFIED CLAIM LEDGER IS THE HARD FACTUAL BOUNDARY. Any factual sentence you keep or add must map to a verified/verified_with_attribution ledger claim for that STORY id.
- Never preserve or add a factual detail that is absent from the ledger, even if it appeared in the previous draft.
- Keep exact numeric/temporal/market/financial/release/title-identity scope from the ledger and preserve attribution_required framing.
- Use only spice_angles with safe_to_narrate=true.
- It is correct for a searched story to receive no extra line if nothing strong was found.
- Keep each verified news_hook as the core. Related context enriches it; it never replaces it.
- Do not regress factual freshness while enriching. Preserve exact scope for box-office numbers, dates, rankings, opening-weekend figures, current cumulative totals, and release type. Never turn an older subtotal into a current "has reached" statement.
- Rumor may appear ONLY when type=rumor and safe_to_narrate=true. Keep it explicitly unconfirmed/reporting/speculation.
- Never turn rumor into fact.
- For social_buzz, NAME THE PLATFORM. Prefer wording like "توی ردیت بعضی از کاربرا..." or "توی X یکی از بحث‌ها..." when that is where the evidence comes from. Avoid vague "مردم توی شبکه‌های اجتماعی می‌گن" unless multiple explicitly named platforms genuinely support the same pattern.
- Do not imply broad consensus from a handful of posts. Use restrained wording such as "بعضی", "یکی از بحث‌ها", or "بین بخشی از طرفدارها".
- Keep critic reaction separate from fan/social reaction.
- A quick story normally needs at most one strong extra angle. A deep Trends story may use up to 2-3 distinct strong angles.
- Prefer useful drama, rumor, critic reaction, social discussion, cool supported facts, production context, or surprising comparisons over generic filler.
- When a strong safe cool_fact has matching visual_context, shape it as one clean short beat/sentence so it can receive one dedicated shot in the edit.
- Preserve supported creator/actor-to-related-title context when visual_context marks it; this lets Media Sources cover the exact related movie/show instead of showing only the current trailer.
- Do not pad a story merely because a context search was run.
- Preserve concise casual-audience familiarity cues when supported.
- Related database story IDs can be merged into one flowing spoken item when they are about the same film/event, while keeping every <!-- STORY:id --> marker immediately before the claim(s) it supports.
- Remove empty endings like "حالا باید دید..." when a concrete supported detail can end the item better.
- Keep Persian conversational and orally natural. Follow the Style Blueprint and long flow anchors, not generic polished news prose.
- When new context turns a previously thin item into a rich one, rebuild that item's micro-arc instead of just appending one sentence at the end.
- Use natural causal/explanatory turns when they genuinely help: "یعنی", "برای همین", "مشکل اینجاست", a short rhetorical setup, or a fact-based aside. Vary them; do not turn them into a template.
- Do not use empty adjective payoffs such as "ترکیب سنگینی", "کنجکاوی‌برانگیز", or "مهم برای مخاطب" unless a concrete supported detail immediately earns that description.
- Keep Persian conversational, compact and natural. Follow recurring Filmbaz craft without copying reference wording.
- Return only the complete rewritten narration in Markdown.
- LENGTH: the packet's length_target gives the spoken word budget for this episode. Reach acceptable_words by telling supported beats more fully and covering every selected story, never by filler. If the approved evidence genuinely cannot fill the range, stay shorter rather than pad.
""" + ATTRIBUTION_POLICY + SPOKEN_QUALITY_RULES

REVISION_SYSTEM = """You are the narration revision writer inside YT News Studio.
Apply the supplied reviewer feedback to the existing narration.

Rules:
- The review is the change list.
- Also fix every issue in the packet's automatic_fact_check when its status is needs_human_check, using only verified ledger claims.
- Preserve every line quoted under the review's "# Keep" section unless an issue explicitly requires changing it.
- Apply issues in severity order; a Fix that contains a Persian rewrite may be used as written if it fits the surrounding register.
- VERIFIED CLAIM LEDGER IS THE HARD FACTUAL BOUNDARY. Every factual sentence in the revised output must remain supported by a verified/verified_with_attribution ledger claim for that STORY id.
- Never introduce a replacement number/date/rank/budget/revenue/deal/release/title fact that is absent from the ledger. If the reviewer asks for such a correction but no verified ledger claim exists, remove/qualify the unsupported statement rather than guessing.
- Preserve attribution_required framing from the ledger.
- Make only changes needed to resolve the review, BUT if the Style/Storytelling audit says an affected story is fundamentally over-compressed or article-like, rewrite that whole story's spoken passage rather than patching one sentence.
- Preserve everything already correct.
- Preserve current-week factual fidelity and STORY markers.
- Preserve claim scope exactly: opening weekend is not current cumulative total; weekend gross is not total gross; domestic is not worldwide; limited theatrical is not wide theatrical. If reviewer feedback identifies a stale volatile value, use only the newer supported value in the packet or qualify/remove the claim.
- Do not import facts from the style transcript corpus.
- When fixing style, obey the supplied Style Blueprint first and use the corpus/flow anchors for recurring behavior (oral syntax, story micro-arcs, rhythm, context, transitions, natural humor), never for copied phrases.
- A revision must not preserve a weak two-sentence news brief merely because its facts are correct. If the approved packet contains richer supported beats, rebuild the passage into a natural spoken mini-story.
- Do not create length with abstract filler. If evidence is thin, leave the item short.
- If the review requests a familiarity cue, use only the approved story's familiarity_anchor; keep it to one short clause.
- If the review requests richer context, use only safe_to_narrate spice_angles from that story. A rumor must remain explicitly labeled as rumor/unconfirmed.
- Remove fake/empty hype rather than replacing it with different hype.
- Do not broadly restart or re-outline the episode unless a blocking review issue explicitly requires it.
- Return the complete revised narration only in Markdown.
- LENGTH: the packet's length_target gives the spoken word budget for this episode. Reach acceptable_words by telling supported beats more fully and covering every selected story, never by filler. If the approved evidence genuinely cannot fill the range, stay shorter rather than pad.
""" + ATTRIBUTION_POLICY + SPOKEN_QUALITY_RULES


def _strip_markdown_emphasis(text: str) -> str:
    # Reviewers often bold labels/values ("- **Status:** **PASS**"). Remove
    # emphasis markers but keep single underscores inside NEEDS_WORK etc.
    return re.sub(r"\*\*|__|\*|`", "", text or "")


_META_SPEECH_RE = re.compile(
    r"(شواهد\s+موجود|منابع\s+موجود|داده[\u200c ]?های\s+موجود|در\s+دسترس\s+نیست|مشخص\s+نشده|"
    r"ledger|claim\s+audit|verification|evidence)",
    re.IGNORECASE,
)
_SCOPE_DISCLAIMER_RE = re.compile(r"(مربوط\s+به\s+(?:همان|همون)|نه\s+فروش\s+(?:کل|تجمعی|یک)|رقمی\s+که\s+دقیقاً)")
_SPOKEN_DECIMAL_RE = re.compile(r"[0-9۰-۹]+[.٫][0-9۰-۹]+\s*(?:میلیون|میلیارد|هزار|درصد|million|billion)")
_OUTLET_RE = re.compile(
    r"(ددلاین|ورایتی|هالیوود\s*ریپورتر|رویترز|بلومبرگ|آسوشیتدپرس|ورج|اسکرین\s*دیلی|ایندی\s*وایر|"
    r"باکس[\u200c ]?آفیس\s*(?:پرو|موجو)|د\s*رپ|Deadline|Variety|Reuters|Bloomberg|Hollywood Reporter|TheWrap|IndieWire)",
    re.IGNORECASE,
)
_FORMAL_FORMS_RE = re.compile(r"(?<![\w\u200c])(را|است|دارد|آمده|می[\u200c ]?باشد|شده[\u200c ]?اند|کرده[\u200c ]?اند)(?![\w\u200c])")
_COLLOQUIAL_FORMS_RE = re.compile(r"(?<![\w\u200c])(رو|داره|اومده|هست|شدن|کردن|اینه)(?![\w\u200c])")


def spoken_lint(text: str) -> list[dict]:
    """Deterministic checks for things that make a script sound written or
    machine-made. Findings are advisory: shown in Step 3 and given to the
    reviewer, never an automatic block."""
    body = re.sub(r"<!--.*?-->", " ", text or "", flags=re.S)
    body = re.sub(r"(?m)^\s*#+\s.*$", " ", body)
    findings: list[dict] = []

    def add(rule: str, message: str, examples: list[str]) -> None:
        findings.append({"rule": rule, "message": message, "examples": [e.strip()[:160] for e in examples[:3]]})

    meta = [m.group(0) for m in _META_SPEECH_RE.finditer(body)]
    if meta:
        add("pipeline_language", "Pipeline/evidence language is spoken aloud.", meta)
    sentences = [x.strip() for x in re.split(r"[.!؟?\n]+", body) if x.strip()]
    disclaimers = [x for x in sentences if _SCOPE_DISCLAIMER_RE.search(x)]
    if disclaimers:
        add("scope_disclaimer", "Standalone sentences that only restate a figure's scope.", disclaimers)
    decimals = [m.group(0) for m in _SPOKEN_DECIMAL_RE.finditer(body)]
    if decimals:
        add("spoken_decimal", "Decimals that are hard to say aloud; round to natural spoken precision.", decimals)
    outlets = [m.group(0) for m in _OUTLET_RE.finditer(body)]
    if len(outlets) > 3:
        add("outlet_names", f"{len(outlets)} outlet names spoken; prefer light markers and keep outlet names to 2-3 per episode.", outlets)
    formal = [m.group(0) for m in _FORMAL_FORMS_RE.finditer(body)]
    colloquial = _COLLOQUIAL_FORMS_RE.findall(body)
    if formal and colloquial and len(formal) >= 3:
        add("register_drift", f"Mixed register: {len(formal)} formal forms next to {len(colloquial)} conversational forms.", formal)
    return findings


def parse_review_gate(text: str) -> dict:
    raw = _strip_markdown_emphasis(text)
    severity_values = re.findall(r"(?im)^\s*[-*]?\s*Severity\s*:\s*(blocking|major|minor)\b", raw)
    counts = {"blocking": 0, "major": 0, "minor": 0}
    for value in severity_values:
        counts[value.lower()] += 1

    def status(label: str) -> str:
        match = re.search(r"(?im)^\s*[-*]?\s*Status\s*:\s*(PASS|NEEDS[_ ]WORK)\b", _section_text(raw, label))
        return (match.group(1).lower().replace(" ", "_") if match else "")

    gate_match = re.search(
        r"(?im)^\s*[-*]?\s*Recommendation\s*:\s*(PASS|REVISION[_ ]REQUIRED|POLISH[_ ]OPTIONAL)\b", raw
    )
    recommendation = gate_match.group(1).lower().replace(" ", "_") if gate_match else ""
    audits = {
        "format_status": status("# Format Audit"),
        "style_status": status("# Style Audit"),
        "factual_status": status("# Factual / Source Audit"),
        "freshness_status": status("# Freshness Audit"),
        "spice_status": status("# Context / Spice Audit"),
        "storytelling_status": status("# Storytelling Audit"),
    }
    if counts["blocking"] or counts["major"] or any(value != "pass" for value in audits.values()):
        recommendation = "revision_required"
    elif not recommendation:
        recommendation = "revision_required"
    return {
        **audits,
        "blocking_count": counts["blocking"],
        "major_count": counts["major"],
        "minor_count": counts["minor"],
        "gate_status": recommendation,
    }


def _section_text(text: str, heading: str) -> str:
    index = text.find(heading)
    if index < 0:
        return ""
    rest = text[index + len(heading):]
    next_heading = re.search(r"(?m)^# ", rest)
    return rest[:next_heading.start()] if next_heading else rest
