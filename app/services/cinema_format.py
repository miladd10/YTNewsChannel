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

for _section in CINEMA_WEEKLY_FORMAT:
    _section.update(SECTION_CONTRACTS.get(_section["key"], {}))

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
        }
        for item in CINEMA_WEEKLY_FORMAT
    ]


def build_style_packet(transcripts: Iterable[dict], max_chars: int = 80000) -> str:
    enabled = [dict(item) for item in transcripts if int(item.get("enabled", 1) or 0)]
    if not enabled:
        return "<style_corpus>No style transcripts have been imported yet.</style_corpus>"

    per_item = max(2500, max_chars // max(1, len(enabled)))
    chunks = [
        "<style_corpus>",
        "These transcripts are STYLE REFERENCES ONLY. Learn tone, pacing, section rhythm, transitions, density, and how the host tells news as a story.",
        "Never treat facts, dates, names, numbers, claims, or opinions inside these old transcripts as facts for the current episode.",
        "Do not imitate distinctive sentences verbatim. Reproduce the general craft, not copied wording.",
    ]
    used = 0
    for item in enabled:
        if used >= max_chars:
            break
        text = str(item.get("content") or "").strip()
        if not text:
            continue
        allowance = min(per_item, max_chars - used)
        if len(text) <= allowance:
            excerpt = text
        else:
            # Sample beginning/middle/end so recurring section rhythm is visible,
            # rather than sending only the opening of every old episode.
            part = max(700, allowance // 3)
            mid = max(0, (len(text) // 2) - (part // 2))
            excerpt = "\n... [middle sample] ...\n".join([
                text[:part],
                text[mid:mid + part],
                text[-part:],
            ])[:allowance]
        used += len(excerpt)
        chunks.extend([
            f'<style_transcript name={json.dumps(item.get("name") or "Transcript")}>' ,
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
- Do not invent missing facts to make a section feel complete.
- If a format section has no approved current-week material, omit it except Intro/Outro.
- Preserve uncertainty labels from the current research.
- Keep every factual news paragraph traceable with <!-- STORY:<id> -->.
- Intro and Outro must NOT have a STORY id.

Writing rules:
- Write in the project's requested language.
- Sound like one conversational host telling the week to a friend, not like a list of article summaries.
- Use the style corpus to learn how much context the host gives before the new fact, how numbers/comparisons are delivered, how transitions work, and how lighter items are paced.
- Trends can breathe and go deeper; Upcoming/TV/Celebrities/AI/Viral/HD/Toxic should generally move faster.
- Explain why a business/industry item matters rather than repeating legal/corporate wording.
- Prefer concrete numbers and comparisons when those numbers exist in the approved research.
- Avoid repetitive section intros and generic AI prose.
- Keep transitions natural and short.
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
- facts assigned to the wrong story;
- missing/incorrect STORY markers;
- weak section organization or stories placed in the wrong format section;
- flat article-summary writing instead of conversational storytelling;
- overlong setup, repetitive transitions, list-like cadence, or generic AI phrasing;
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
- Notes: ...

# Factual / Source Audit
- Status: PASS | NEEDS_WORK
- Notes: ...

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
