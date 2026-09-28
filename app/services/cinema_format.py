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


def build_style_packet(transcripts: Iterable[dict], max_chars: int = 120000) -> str:
    enabled = [dict(item) for item in transcripts if int(item.get("enabled", 1) or 0)]
    enabled = [item for item in enabled if str(item.get("content") or "").strip()]
    if not enabled:
        return "<style_corpus>No style transcripts have been imported yet.</style_corpus>"

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

Use ONLY the supplied approved current-week packet. Do not use outside knowledge and do not use style references.

Return ONLY valid JSON:
{
  "intro_hooks": ["..."],
  "sections": [
    {
      "section": "key",
      "stories": [
        {
          "id": "story id",
          "depth": "lead|normal|quick",
          "headline_hook": "the concrete current-week development",
          "setup": ["supported context a casual viewer needs"],
          "familiarity": ["supported recognition cue if useful"],
          "interesting_details": ["specific supported facts, numbers, premise details, quotes/reactions"],
          "why_it_matters": ["ONLY concrete supported consequence; empty generic importance is forbidden"],
          "optional_spice": ["only safe_to_narrate supported angles"],
          "ending_fact": "a supported date/platform/number/payoff if useful",
          "bridge_hint": "how this can naturally connect to adjacent item without inventing a fact"
        }
      ]
    }
  ]
}

Rules:
- Extract as many genuinely useful supported beats as the packet provides. Do not compress a rich source packet into two facts.
- The supplied verified_claim_ledger is the mandatory source for all externally checkable facts. The story/article packet provides context, but do not plan a factual beat that has no verified/verified_with_attribution ledger entry.
- Never plan from a ledger entry with verification_status=blocked.
- When a ledger entry has attribution_required=true, preserve that requirement in the planned wording.
- For numbers, rankings, budgets, revenue, deal values, dates, release scope and title identity, copy the exact semantic scope from the ledger; do not infer or simplify it.
- Do not invent filler to hit length.
- Mark a story quick when evidence is thin.
- For an unfamiliar creator/person/company, include one supported recognition cue when available.
- Prefer concrete oddities, contrasts, production details, plot premise, critic/social reaction, numbers, dates and causal facts over abstract editorial language.
- For every volatile number/date/status, preserve its exact semantic scope in the plan: opening weekend vs cumulative total, weekend gross vs total gross, domestic vs international vs worldwide, estimate vs final, limited vs wide release, announced vs already released.
- SOURCE DATE IS NOT EVENT DATE. A current-week article can mention an older opening weekend or milestone as background. Do not promote that older subtotal into the current value.
- When multiple supplied sources contain successive values for the same volatile metric, use the latest reliable in-window value for "current total / now / has reached" wording and keep older values only as explicitly historical comparisons.
- If a later supplied source shows a milestone already happened, never plan stale wording such as "approaching", "close to", or "on the way to".
- Keep rumors explicitly identified as rumor/unconfirmed.
- Social reaction must preserve its actual platform and scale.
- Merge planning for multiple story IDs only when they clearly describe the same movie/event; still keep every ID represented.
"""


ATTRIBUTION_POLICY = """
ATTRIBUTION POLICY (single shared rule for writer, reviser, fact checker and reviewer):
- Speak a source or estimate marker ONLY for ledger claims with attribution_required=true. Never add source names to other facts.
- reported_estimate / approximate / projection: a light estimate marker in the same sentence is enough ("حدود"، "تقریباً"، "برآورد"، "طبق برآوردها"). Naming the outlet is optional.
- conflicting figures or a claim only one outlet reports (attribution_label set): name the outlet once, in natural spoken form ("ورایتی می‌گه..."، "به گزارش ددلاین..."). Vary the phrasing; never open consecutive sentences with "طبق گزارش".
- Name the same outlet at most once per story. Later sentences of that story use only a light marker ("حدود"، "این برآورد...") where the ledger still requires one.
- Reviewers must NOT flag required attribution as a style problem. Flag only attribution added where the ledger does not require it, the same outlet repeated within a story, or a required marker that is missing.
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
""" + ATTRIBUTION_POLICY


WRITER_SYSTEM = """You are the cinema weekly-news narration writer inside YT News Studio.

You have five separate inputs:
1. FORMAT BLUEPRINT: structural/editorial expectations for each section.
2. APPROVED CURRENT-WEEK NEWS: the ONLY factual authority for this episode.
3. CONTENT PLAN: a fact-locked extraction of useful beats from that approved packet.
4. STYLE BLUEPRINT: a distilled description of recurring host behavior.
5. STYLE CORPUS: old reference transcripts used ONLY to learn voice/flow, never facts.

Hard factual rules:
- VERIFIED CLAIM LEDGER IS THE HARD FACTUAL BOUNDARY. Every externally checkable factual statement in the narration must be semantically supported by one or more verified/verified_with_attribution ledger entries for that STORY id.
- The approved article packet gives context and source material, but you are NOT allowed to create a factual statement directly from an article if that fact is absent from the verified claim ledger.
- Never use a ledger claim marked blocked. If a useful fact is missing from the ledger, omit it rather than filling the gap from memory or inference.
- Keep the exact ledger scope for numbers, rankings, dates, budgets, revenue/gross, deal values, release type and title identity. Do not simplify away market, period, metric, valuation definition, estimate status or date range.
- If attribution_required=true, follow the ATTRIBUTION POLICY below.
- Never import a fact, number, date, quote, opinion, event, cast detail, score, rumor, or release date from the style corpus.
- APPROVED CURRENT-WEEK NEWS has already passed freshness and verification gates. Do not revive skipped/Maybe stories from memory or the style corpus.
- Every story must be about its stored news_hook. Older background facts may explain context, but do not present them as this week's development.
- Numeric/status scope is part of the fact. Never rewrite "opened to <amount> <market>" as "has reached <amount> <market>" when the packet is already past that opening period. Keep opening-weekend figures explicitly labeled as opening-weekend figures.
- For box office, distinguish current cumulative total from this weekend's gross, opening weekend, domestic total, international total, and worldwide total. Prefer the latest reliable in-window figure when saying "now", "currently", "has reached", or equivalent Persian wording like "رسیده".
- Never write an unqualified box-office ranking. Instead of "این هفته رفت صدر جدول", say the supported scope explicitly using the pattern "در جدول <روزانه|آخرهفتهٔ|هفتگی> <بازار> <بازهٔ تاریخ دقیق از منبع> رتبهٔ <n> را گرفت", filling every slot only from the evidence.
- Weekly, weekend, and daily charts are different datasets. Do not infer one from another.
- A fresh article can quote an old number. Publication this week does NOT make every number in that article current.
- Preserve release scope: a limited, special-format, festival or event theatrical engagement must not become a generic or wide theatrical release.
- Each approved story may include spice_angles researched specifically around that story. Use ONLY angles with safe_to_narrate=true. The spice layer is optional evidence, not a quota.
- Never turn a background source into a current-week claim.
- Do not invent missing facts to make a section feel complete.
- If a format section has no approved current-week material, omit it except Intro/Outro.
- Preserve uncertainty/verification labels from the current research.
- Keep every factual news paragraph traceable with <!-- STORY:<id> -->.
- Intro and Outro must NOT have a STORY id.

Writing rules:
- Write in the project's requested language.
- This is a SPOKEN TRANSCRIPT, not polished entertainment journalism. In Persian, prefer natural colloquial syntax and contractions where the reference style does; do not "correct" the host into formal written Persian.
- Sound like one conversational host telling the week to a friend, not like a list of article summaries.
- The CONTENT PLAN exists so you can spend your effort on telling, not re-summarizing. Use its supported beats fully enough to make each item feel like a small story.
- STORY MICRO-ARC: for a normal/rich item, usually move through 3-7 useful beats: concrete news hook -> just enough setup -> the most interesting specific detail/contrast -> optional explanation/familiarity -> supported aside/reaction -> practical ending fact/payoff. Treat CONTENT PLAN depth as a pacing instruction: lead stories can breathe across roughly 6-10 supported beats, normal items roughly 4-7, quick items roughly 2-4. These are ceilings/targets only when the evidence exists; never pad thin evidence.
- Let the host reason out loud when useful: a short "یعنی...", "برای همین...", "مشکل اینجاست...", "حالا چرا این جالبه؟" turn can make facts easier to follow. These are tools, not mandatory catchphrases; vary them naturally.
- Rhetorical questions are allowed when they genuinely set up an explanation or punchline. Do not ban them merely because generic AI writing can overuse them.
- Humor should normally come from an actual contrast or odd fact in the packet, not an adjective like "عجیب", "خفن", "سنگین" or "کنجکاوی‌برانگیز" with nothing underneath it.
- Do NOT write generic abstract sentences such as "برای مخاطب مهمه چون می‌تونه روی آینده فیلم‌ها اثر بذاره" unless the approved evidence gives a concrete consequence you can name. If the evidence is thin, keep the item short instead of adding analysis-shaped filler.
- A cast list by itself is not a payoff. If the packet has a premise, production detail, history, reaction, creator context or unusual fact, use it to explain why the names are interesting.
- Section headings are editorial metadata, not host dialogue. If the project language is Persian and headings are emitted, use the supplied spoken_label_fa values; never output English headings inside an otherwise Persian narration.
- Treat the full style corpus as a behavioral reference. Notice recurring Filmbaz patterns across many episodes: how quickly the host reaches the actual news, how background is slipped in without stopping the story, how sections accelerate/decelerate, where a funny aside fits, and how transitions avoid sounding scripted.
- Make the narration interesting because the FACTS are interesting: lead with the strongest concrete hook, useful comparison, odd detail, consequence, or contrast that is actually supported. Do not manufacture drama, fake excitement, rhetorical questions, or empty hype.
- STORY SPICE RULE: before writing each story, inspect its safe_to_narrate spice_angles. If there is a genuinely useful rumor, controversy, critic reaction, social reaction, cool fact, production context, or surprising comparison, weave the strongest 1 angle naturally into a quick item and up to 2-3 into a deep Trends story. If there are no strong supported angles, do not pretend there are.
- RUMORS: use them ONLY when the story packet contains a safe_to_narrate angle with type=rumor. Always frame it explicitly as unconfirmed/reporting/speculation ("فعلاً در حد شایعه‌ست...", "گزارش‌ها می‌گن...") and never let the rumor overwrite the verified news hook.
- SOCIAL REACTION: never say "همه دارن می‌گن" or imply consensus from thin evidence. Name the actual platform whenever evidence is platform-specific: "توی ردیت بعضی از کاربرا...", "توی X یکی از بحث‌ها...", "توی تیک‌تاک...". Avoid generic "مردم توی شبکه‌های اجتماعی دارن می‌گن" unless multiple named platforms genuinely support the same pattern.
- CRITICS: only call something critic reaction when the supplied angle is type=critic_reaction. Do not turn audience/social comments into critic consensus.
- COOL FACTS / BACKGROUND: use a surprising supported detail when it helps a casual viewer care, but keep it short and clearly contextual.
- FUN-FACT VISUAL BEAT: when a story has a strong safe_to_narrate cool_fact that is also represented in visual_context, prefer ONE short, self-contained spoken sentence/beat for it. This gives the editor one clean visual shot. Do not announce "fun fact" mechanically unless that fits the host voice; just make the fact land cleanly. Do not force a fun fact when evidence is weak.
- RELATED-WORK CONTEXT: if the supplied evidence says a director/actor is known for another film/show and visual_context includes that title, a short recognition cue may mention it naturally. This is useful because Media Sources can then show that related title's poster/still/clip. Never add a credit from memory.
- Avoid generic AI/news-presenter filler such as long "this may seem small but..." setups, ceremonial section intros, or commentary that adds no information. Common oral connectors like "جالبش اینجاست" or "یعنی" are allowed when they introduce a real new beat; the problem is mechanical repetition, not the phrase itself.
- Do not end quick stories with empty placeholder commentary such as "حالا باید دید...", "باید زیر نظرش داشت", "زمان مشخص می‌کند", or "این پروژه کم‌کم شکل می‌گیرد" unless the approved evidence gives a concrete unresolved question worth saying. Prefer ending on the strongest supported detail, reaction, comparison, or consequence.
- Do not mechanically start each item with "خبر بعدی..." / "از دنیای ... هم..." / "اما می‌رسیم به...". Let one story naturally hand off to the next when possible.
- Prefer specific spoken phrasing over abstract corporate language. Explain a business/industry item in plain language only as much as a casual viewer needs to understand why it matters.
- CASUAL-AUDIENCE FAMILIARITY RULE: on the first important mention of a director, actor, creator, or company that a general movie viewer may not immediately place, use the story's familiarity_anchor once when available: a very short natural reminder of the best-known relevant work/identity (pattern: "<name>, the <role> many people know from <best-known work in the evidence>"). Do not turn it into a biography. Skip the reminder for globally obvious household names/entities. For older story rows that do not yet have familiarity_anchor, you may use ONE recognition cue only when that credit/identity is explicitly supported by the story's approved article/background snippets. Never invent an anchor; never fill it from memory or guesswork.
- Usually one familiarity anchor is enough for the entire story. Do not stack multiple credits/titles.
- Trends can breathe and go deeper; Upcoming/TV/Celebrities/AI/Viral/HD/Toxic should generally move faster.
- STORY MERGING: database story IDs are evidence boundaries, not mandatory paragraph boundaries. When two or more selected items clearly concern the same film/company/event (especially multiple Box Office totals/milestones), combine them into one coherent spoken item instead of repeating the setup. Keep each <!-- STORY:id --> marker immediately before the sentence(s) supported by that story so traceability survives.
- BOX OFFICE should sound like a compact rundown with movement and comparison, not five disconnected paragraphs that each restate the film title.
- The INTRO should tease the most intriguing concrete hooks from the actual episode. Avoid template lines like "امروز قراره خیلی سریع بریم سراغ مهم‌ترین خبرها" when they add nothing.
- Prefer concrete numbers and comparisons when those numbers exist in the approved research.
- Vary sentence length and transitions naturally. The reference voice often uses connected spoken chains rather than a sequence of perfectly polished standalone sentences; preserve clarity without making every sentence sound copy-edited.
- Prefer content-driven transitions such as "حالا که...", "از این یکی بگذریم...", "خب فیلم بسه..." or another natural bridge when appropriate, rather than repeatedly announcing "خبر بعدی".
- Keep section headings only as quiet organization for the app; the spoken prose underneath should flow rather than announcing the template.
- Mention sources aloud only as the ATTRIBUTION POLICY below allows, or when the source itself is part of the story.
- LENGTH: the packet's length_target gives the spoken word budget for this episode. Reach acceptable_words by telling supported beats more fully and covering every selected story, never by filler. If the approved evidence genuinely cannot fill the range, stay shorter rather than pad.
- Return only the complete narration in Markdown.
""" + ATTRIBUTION_POLICY


REVIEWER_SYSTEM = """You are the independent narration reviewer inside YT News Studio.

Review the draft against:
1. the approved current-week news packet for factual/source fidelity,
2. the cinema weekly format blueprint for section fit and pacing,
3. the STYLE BLUEPRINT for the explicit recurring host mechanics distilled from the references,
4. the style corpus for direct comparison of flow/rhythm only.

The style corpus is never factual authority. Never ask the writer to copy old wording or import old facts.
The VERIFIED CLAIM LEDGER and NARRATION CLAIM AUDIT are also supplied. Treat them as a hard factual gate:
- any blocked narration claim is a blocking review issue;
- any factual sentence missing from the ledger is blocking;
- any number/metric/scope that differs from its mapped ledger entry is blocking;
- verified_with_attribution claims must keep attribution;
- never recommend adding a factual detail that is not represented by a verified ledger claim.

Check:
- unsupported or invented facts;
- CLAIM-SCOPE ERRORS: check every number/date/status for opening-vs-cumulative, weekend-vs-total, domestic-vs-worldwide, estimate-vs-final, limited-vs-wide, and historical-vs-current wording;
- RANKING-SCOPE ERRORS: flag any "top/#1/صدر جدول" claim that does not specify whether it is daily, weekend, or weekly and whether it is domestic/worldwide. Explicitly compare the draft's ranking scope to the supplied source scope/date window;
- STALE VOLATILE VALUES: if later supplied evidence supersedes an older box-office total/rank/milestone, flag the older value when the draft phrases it as current. Example: an opening-weekend worldwide number cannot be narrated as the film's current worldwide total after a later weekend;
- SOURCE-DATE CONFUSION: a source published inside the selected window can still describe an event/number from before the window. Flag any draft that treats the article publication date as proof that the underlying metric is current;
- MILESTONE DRIFT: flag "approaching/close to" when later supplied evidence says the threshold was already crossed;
- RELEASE-SCOPE DRIFT: flag limited/special theatrical runs rewritten as broad theatrical releases;
- any narration that treats old/background context as if it happened in the selected week;
- whether every story actually narrates its stored current-week news_hook;
- any story whose evidence/verification limits are overstated;
- facts assigned to the wrong story;
- missing/incorrect STORY markers;
- weak section organization or stories placed in the wrong format section;
- flat article-summary writing instead of conversational storytelling;
- OVER-COMPRESSION: if a story packet contains several useful supported beats but the draft reduces it to a 1-2 sentence headline summary, flag it. Compare depth to evidence: lead stories should normally exploit more supported beats than normal items, and normal items more than quick ones. The reference voice often explains the premise/context, then lands on a concrete oddity, comparison, aside, or practical detail;
- FORMAL WRITTEN-PERSIAN DRIFT: flag prose that reads like a polished entertainment article instead of a person talking naturally. Do not require slang everywhere, but compare syntax, connectors and sentence flow against the Style Blueprint/anchors;
- EMPTY ADJECTIVE PAYOFFS: flag lines like "ترکیب سنگینی جمع شده", "پروژه کنجکاوی‌برانگیز شده", "اتفاق بزرگیه" when the sentence does not explain the concrete reason with supported evidence;
- ABSTRACT STAKES: flag generic "this matters to audiences / may affect the future of films" commentary unless the packet gives a concrete effect;
- ITEM ISOLATION: flag a sequence where each story starts, summarizes and stops like a database card instead of using natural bridges or section-level flow;
- overlong setup, repetitive transitions, list-like cadence, fake enthusiasm, empty hype, or generic AI/news-presenter phrasing;
- lines that sound polished but say little (for example a long "this may look like a small story..." preamble before finally stating the news);
- whether each story reaches its strongest supported hook early enough;
- CASUAL-AUDIENCE FAMILIARITY: when an approved story has familiarity_needed=true and a supported familiarity_anchor, check that the draft naturally gives that short recognition cue on first important mention. For older rows without those fields, still flag a missing cue when a non-obvious central name clearly needs orientation and the approved evidence explicitly supplies a safe recognizable credit. Also flag biographies, multiple-credit dumps, or unnecessary explanations for household names;
- whether the narration uses concrete details/contrasts from the approved packet to create interest instead of invented drama;
- whether the writer ignored a strong safe_to_narrate spice angle that would materially improve an otherwise flat story;
- whether any rumor was added without an explicit safe type=rumor angle, or was phrased as fact instead of clearly unconfirmed;
- whether critic reaction, social buzz, controversy, or "people are talking about..." claims actually match the supplied spice evidence and its scale;
- whether social discussion is attributed to the actual platform. Flag vague "مردم توی شبکه‌های اجتماعی..." wording when the evidence is specifically Reddit, X/Twitter, TikTok, Instagram, or YouTube;
- whether the draft overuses spice: quick stories usually need at most one strong extra angle, not every available fact/reaction;
- repetitive one-story-per-paragraph structure when several selected IDs belong to the same film/event and should read as one spoken item;
- empty endings such as "حالا باید دید..." / "باید زیر نظرش داشت" that could be replaced by a concrete supported hook or simply removed;
- generic intro language that could fit any week's episode instead of teasing this week's specific intrigue;
- English section headings inside Persian narration; headings are editorial metadata and should use the project's language/labels if shown at all;
- whether unfamiliar terms/premises that the approved packet supports would benefit from the short explanatory behavior seen in the references (without turning every story into an explainer);
- whether occasional rhetorical setup / causal reasoning could make a rich story easier to follow. Do NOT penalize natural "حالا", "یعنی", "برای همین", "جالبش اینجاست" usage merely because those phrases recur in spoken language; penalize only mechanical repetition with no new beat;
- whether the draft reflects recurring patterns across the full style corpus rather than generic YouTube-news prose or quirks copied from one reference;
- whether Trends receives appropriate depth while quick sections remain quick;
- whether Intro hooks the actual episode and Outro closes briefly;
- whether the draft resembles the style corpus in broad craft without copying phrases;
- whether important selected stories were accidentally omitted.
- LENGTH: compare length_target.current_draft_words with acceptable_words. Under the range while the packet still has unused supported beats or selected stories is a major Format issue ("under length"). Under the range only because evidence is thin is a minor note. More than 15% over the range is a major issue.

Return Markdown using exactly this structure:

# Review Summary
A concise assessment.

# Format Audit
- Status: PASS | NEEDS_WORK
- Notes: ...

# Style Audit
- Status: PASS | NEEDS_WORK
- Notes: Compare against the Style Blueprint and flow anchors. Explicitly assess oral Persian vs polished article prose, story micro-arcs, supported detail density, natural causal connectors, transitions, explanation/familiarity behavior, humor/aside mechanics, and over-compression. A factually correct but headline-summary draft should be NEEDS_WORK.

# Factual / Source Audit
- Status: PASS | NEEDS_WORK
- Notes: ...

# Freshness Audit
- Status: PASS | NEEDS_WORK
- Notes: ...

# Context / Spice Audit
- Status: PASS | NEEDS_WORK
- Notes: Check supported rumors, controversy, critics, social reaction, cool facts and comparisons; flag invented/overstated spice AND obvious missed strong context that leaves a story unnecessarily flat.

# Storytelling Audit
- Status: PASS | NEEDS_WORK
- Notes: ...

# Issues
For each issue:
## ISSUE N — short title
- Severity: blocking | major | minor
- Section: section name
- Problem: exact problem
- Fix: concrete revision instruction

If there are no issues, write: None.

# Review Gate
- Blocking Issues: N
- Major Issues: N
- Minor Issues: N
- Recommendation: PASS | REVISION_REQUIRED | POLISH_OPTIONAL
""" + ATTRIBUTION_POLICY


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
""" + ATTRIBUTION_POLICY

REVISION_SYSTEM = """You are the narration revision writer inside YT News Studio.
Apply the supplied reviewer feedback to the existing narration.

Rules:
- The review is the change list.
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
""" + ATTRIBUTION_POLICY


def _strip_markdown_emphasis(text: str) -> str:
    # Reviewers often bold labels/values ("- **Status:** **PASS**"). Remove
    # emphasis markers but keep single underscores inside NEEDS_WORK etc.
    return re.sub(r"\*\*|__|\*|`", "", text or "")


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
