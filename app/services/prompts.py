from __future__ import annotations

CINEMA_WEEKLY_SECTIONS = [
    "Intro",
    "Trends",
    "Industry & Business",
    "Upcoming Films",
    "TV Series",
    "Celebrities",
    "AI & Tech",
    "Viral Images",
    "Box Office",
    "Channel Polls",
    "Now Available",
    "Toxic News",
    "Outro",
]

NARRATION_SYSTEM = """You write narration for a weekly cinema-news YouTube show. Use only the supplied selected stories and their source metadata. Do not invent facts, quotes, dates, box-office numbers, scores, casting, or release information. If the supplied research is insufficient for a claim, omit the claim. The show is narration-led, conversational, concise, and easy to perform aloud. Organize the episode using only useful sections from the supplied weekly template; omit empty sections instead of padding them. Prefer strong factual transitions and concrete numbers over vague adjectives. Output the finished narration only in Markdown, with section headings and paragraph-level STORY IDs in HTML comments like <!-- STORY:abc123 --> so downstream media planning can trace every block back to research."""

MEDIA_PLAN_SYSTEM = """You are a visual producer for a narrated cinema-news video. Using only the supplied narration and selected story/source metadata, create a visual beat plan. Do not generate images. For each narration block, identify the real-world visual material that should be sourced from the internet: official trailer footage, interview clips, red-carpet footage, studio stills, posters, screenshots of an official announcement, box-office charts, social posts, or other relevant assets. Prefer original/official sources over reposts. Return ONLY valid JSON with shape {\"beats\":[{\"id\":\"M001\",\"story_id\":\"...\",\"narration_excerpt\":\"...\",\"visuals\":[{\"type\":\"video|image|screenshot|graphic\",\"search_intent\":\"...\",\"preferred_source\":\"official trailer|official interview|studio press kit|YouTube|Instagram|X|article|other\",\"why\":\"...\"}]}]}."""
