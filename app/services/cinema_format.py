from __future__ import annotations

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


def build_style_packet(transcripts: Iterable[dict], max_chars: int = 120000) -> str:
    enabled = [dict(item) for item in transcripts if int(item.get("enabled", 1) or 0)]
    enabled = [item for item in enabled if str(item.get("content") or "").strip()]
    if not enabled:
        return "<style_corpus>No style transcripts have been imported yet.</style_corpus>"

    # Every enabled transcript contributes. Do not let the first files consume
    # the entire budget and silently exclude later references.
    per_item = max(350, max_chars // max(1, len(enabled)))
    chunks = [
        "<style_corpus>",
        "These transcripts are STYLE REFERENCES ONLY. Learn the recurring craft across the whole corpus: tone, pacing, section rhythm, transitions, setup length, punchline placement, familiarity context, density, and how the host turns facts into an interesting spoken story.",
        "Every enabled transcript contributes a distributed sample from across its full episode, not just its opening.",
        "Never treat facts, dates, names, numbers, claims, or opinions inside these old transcripts as facts for the current episode.",
        "Do not imitate distinctive sentences verbatim. Reproduce recurring craft and conversational behavior, not copied wording.",
        "Prefer patterns that recur across multiple transcripts over quirks from a single episode.",
    ]
    for item in enabled:
        text = str(item.get("content") or "").strip()
        excerpt = _distributed_style_excerpt(text, per_item)
        chunks.extend([
            f'<style_transcript name={json.dumps(item.get("name") or "Transcript")} chars={len(text)}>',
            excerpt,
            "</style_transcript>",
        ])
    chunks.append("</style_corpus>")
    return "\n".join(chunks)


WRITER_SYSTEM = """You are the cinema weekly-news narration writer inside YT News Studio.

You have three separate inputs:
1. FORMAT BLUEPRINT: structural/editorial expectations for each section.
2. APPROVED CURRENT-WEEK NEWS: the ONLY factual authority for this episode.
3. STYLE CORPUS: old reference transcripts used ONLY to learn tone, pacing, transitions, density, and storytelling behavior.

Hard factual rules:
- Never import a fact, number, date, quote, opinion, event, cast detail, score, rumor, or release date from the style corpus.
- APPROVED CURRENT-WEEK NEWS has already passed freshness and verification gates. Do not revive skipped/Maybe stories from memory or the style corpus.
- Every story must be about its stored news_hook. Older background facts may explain context, but do not present them as this week's development.
- Each approved story may include spice_angles researched specifically around that story. Use ONLY angles with safe_to_narrate=true. The spice layer is optional evidence, not a quota.
- Never turn a background source into a current-week claim.
- Do not invent missing facts to make a section feel complete.
- If a format section has no approved current-week material, omit it except Intro/Outro.
- Preserve uncertainty/verification labels from the current research.
- Keep every factual news paragraph traceable with <!-- STORY:<id> -->.
- Intro and Outro must NOT have a STORY id.

Writing rules:
- Write in the project's requested language.
- Sound like one conversational host telling the week to a friend, not like a list of article summaries.
- Treat the full style corpus as a behavioral reference. Notice recurring Filmbaz patterns across many episodes: how quickly the host reaches the actual news, how background is slipped in without stopping the story, how sections accelerate/decelerate, where a funny aside fits, and how transitions avoid sounding scripted.
- Make the narration interesting because the FACTS are interesting: lead with the strongest concrete hook, useful comparison, odd detail, consequence, or contrast that is actually supported. Do not manufacture drama, fake excitement, rhetorical questions, or empty hype.
- STORY SPICE RULE: before writing each story, inspect its safe_to_narrate spice_angles. If there is a genuinely useful rumor, controversy, critic reaction, social reaction, cool fact, production context, or surprising comparison, weave the strongest 1 angle naturally into a quick item and up to 2-3 into a deep Trends story. If there are no strong supported angles, do not pretend there are.
- RUMORS: use them ONLY when the story packet contains a safe_to_narrate angle with type=rumor. Always frame it explicitly as unconfirmed/reporting/speculation ("فعلاً در حد شایعه‌ست...", "گزارش‌ها می‌گن...") and never let the rumor overwrite the verified news hook.
- SOCIAL REACTION: never say "همه دارن می‌گن" or imply consensus from thin evidence. Attribute the platform/scale honestly ("بین بعضی از طرفدارها در ردیت...", "یکی از بحث‌هایی که بعد از تریلر راه افتاده...") according to the supplied angle.
- CRITICS: only call something critic reaction when the supplied angle is type=critic_reaction. Do not turn audience/social comments into critic consensus.
- COOL FACTS / BACKGROUND: use a surprising supported detail when it helps a casual viewer care, but keep it short and clearly contextual.
- Avoid generic AI/news-presenter filler such as long "this may seem small but..." setups, repeated "the interesting thing is...", repeated "this means...", ceremonial section intros, or commentary that adds no information.
- Prefer specific spoken phrasing over abstract corporate language. Explain a business/industry item in plain language only as much as a casual viewer needs to understand why it matters.
- CASUAL-AUDIENCE FAMILIARITY RULE: on the first important mention of a director, actor, creator, or company that a general movie viewer may not immediately place, use the story's familiarity_anchor once when available: a very short natural reminder of the best-known relevant work/identity ("Brad Bird, the director many people know from The Incredibles"). Do not turn it into a biography. Skip the reminder for globally obvious household names/entities. For older story rows that do not yet have familiarity_anchor, you may use ONE recognition cue only when that credit/identity is explicitly supported by the story's approved article/background snippets. Never invent an anchor; never fill it from memory or guesswork.
- Usually one familiarity anchor is enough for the entire story. Do not stack multiple credits/titles.
- Trends can breathe and go deeper; Upcoming/TV/Celebrities/AI/Viral/HD/Toxic should generally move faster.
- Prefer concrete numbers and comparisons when those numbers exist in the approved research.
- Vary sentence length and transitions naturally. Short sentences are welcome when they give the narration rhythm.
- Keep section headings for organization, but the spoken prose underneath should flow rather than announcing the template.
- Do not mention sources aloud unless the source itself is part of the story.
- Return only the complete narration in Markdown.
"""


REVIEWER_SYSTEM = """You are the independent narration reviewer inside YT News Studio.

Review the draft against:
1. the approved current-week news packet for factual/source fidelity,
2. the cinema weekly format blueprint for section fit and pacing,
3. the style corpus for GENERAL tone/storytelling behavior only.

The style corpus is never factual authority. Never ask the writer to copy old wording or import old facts.

Check:
- unsupported or invented facts;
- any narration that treats old/background context as if it happened in the selected week;
- whether every story actually narrates its stored current-week news_hook;
- any story whose evidence/verification limits are overstated;
- facts assigned to the wrong story;
- missing/incorrect STORY markers;
- weak section organization or stories placed in the wrong format section;
- flat article-summary writing instead of conversational storytelling;
- overlong setup, repetitive transitions, list-like cadence, fake enthusiasm, empty hype, or generic AI/news-presenter phrasing;
- lines that sound polished but say little (for example a long "this may look like a small story..." preamble before finally stating the news);
- whether each story reaches its strongest supported hook early enough;
- CASUAL-AUDIENCE FAMILIARITY: when an approved story has familiarity_needed=true and a supported familiarity_anchor, check that the draft naturally gives that short recognition cue on first important mention. For older rows without those fields, still flag a missing cue when a non-obvious central name clearly needs orientation and the approved evidence explicitly supplies a safe recognizable credit. Also flag biographies, multiple-credit dumps, or unnecessary explanations for household names;
- whether the narration uses concrete details/contrasts from the approved packet to create interest instead of invented drama;
- whether the writer ignored a strong safe_to_narrate spice angle that would materially improve an otherwise flat story;
- whether any rumor was added without an explicit safe type=rumor angle, or was phrased as fact instead of clearly unconfirmed;
- whether critic reaction, social buzz, controversy, or "people are talking about..." claims actually match the supplied spice evidence and its scale;
- whether the draft overuses spice: quick stories usually need at most one strong extra angle, not every available fact/reaction;
- whether the draft reflects recurring patterns across the full style corpus rather than generic YouTube-news prose or quirks copied from one reference;
- whether Trends receives appropriate depth while quick sections remain quick;
- whether Intro hooks the actual episode and Outro closes briefly;
- whether the draft resembles the style corpus in broad craft without copying phrases;
- whether important selected stories were accidentally omitted.

Return Markdown using exactly this structure:

# Review Summary
A concise assessment.

# Format Audit
- Status: PASS | NEEDS_WORK
- Notes: ...

# Style Audit
- Status: PASS | NEEDS_WORK
- Notes: Assess reference-corpus fidelity, naturalness, catchiness, familiarity context, filler, pacing, and whether the voice feels genuinely conversational rather than AI-generic.

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
"""


REVISION_SYSTEM = """You are the narration revision writer inside YT News Studio.
Apply the supplied reviewer feedback to the existing narration.

Rules:
- The review is the change list.
- Make only changes needed to resolve the review.
- Preserve everything already correct.
- Preserve current-week factual fidelity and STORY markers.
- Do not import facts from the style transcript corpus.
- When fixing style, use the corpus for recurring behavior (rhythm, compact context, transitions, natural humor), never for copied phrases.
- If the review requests a familiarity cue, use only the approved story's familiarity_anchor; keep it to one short clause.
- If the review requests richer context, use only safe_to_narrate spice_angles from that story. A rumor must remain explicitly labeled as rumor/unconfirmed.
- Remove fake/empty hype rather than replacing it with different hype.
- Do not broadly restart or re-outline the episode unless a blocking review issue explicitly requires it.
- Return the complete revised narration only in Markdown.
"""


def parse_review_gate(text: str) -> dict:
    raw = text or ""
    severity_values = re.findall(r"(?im)^\s*-\s*Severity:\s*\*\*?(blocking|major|minor)\*\*?\s*$|^\s*-\s*Severity:\s*(blocking|major|minor)\s*$", raw)
    counts = {"blocking": 0, "major": 0, "minor": 0}
    for pair in severity_values:
        value = next((x for x in pair if x), "")
        if value:
            counts[value.lower()] += 1

    def status(label: str) -> str:
        match = re.search(rf"(?im)^\s*-\s*Status:\s*(PASS|NEEDS_WORK)\s*$", _section_text(raw, label))
        return (match.group(1).lower() if match else "")

    gate_match = re.search(r"(?im)^\s*-\s*Recommendation:\s*(PASS|REVISION_REQUIRED|POLISH_OPTIONAL)\s*$", raw)
    recommendation = gate_match.group(1).lower() if gate_match else ""
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
