from __future__ import annotations

import json
import math
import re
import uuid
from typing import Iterable

from .ai import generate_text


CLAIM_TYPES = {
    "box_office", "ranking", "budget", "revenue", "release", "deal_value",
    "title_identity", "person_credit", "cast", "quote", "award", "production",
    "company", "other",
}
VERIFY_STATUSES = {"verified", "verified_with_attribution", "blocked"}

CLAIM_LEDGER_SYSTEM = """You build a source-locked atomic claim ledger for a weekly cinema-news narration.

You receive approved story packets, their dated sources, fresh verification results, and the project window.

Return ONLY JSON:
{"claims":[{"story_id":"...","claim_type":"box_office|ranking|budget|revenue|release|deal_value|title_identity|person_credit|cast|quote|award|production|company|other","subject":"...","predicate":"...","canonical_text":"one atomic fact","value_text":"","numeric_value":null,"currency":"","unit":"","metric":"","market":"","region":"","chart_type":"","rank":null,"period_type":"","date_start":"","date_end":"","as_of_date":"","release_scope":"","title_identity":"","estimate_status":"confirmed|reported_estimate|projection|approximate|conflicting|","attribution_required":false,"attribution_label":"","source_urls":["exact supplied URL"],"evidence_summary":"what the cited evidence actually supports","conflict_note":"","verification_status":"verified|verified_with_attribution|blocked"}]}

HARD RULES:
- Every claim is atomic. Split different numbers/scopes into separate claims.
- Use only supplied evidence. Never use memory.
- Read each article's title, snippet, description and excerpt. Extract every useful checkable fact the excerpts support (premise, credits, dates, formats, figures, context), not only the headline fact.
- source_urls must be exact supplied URLs for that same story. No source means blocked.
- Numeric meaning is inseparable from scope.
- BOX OFFICE: distinguish daily/weekend/weekly; opening weekend vs cumulative; domestic/international/worldwide; estimate vs actual; and exact date range/as-of date.
- RANKING: rank, chart_type, market/region, date_start and date_end are mandatory.
- BUDGET: distinguish production budget from marketing/total spend. Public budgets are usually reported estimates unless authoritative evidence explicitly confirms them.
- REVENUE: distinguish theatrical gross, company revenue, streaming/licensing revenue, operating revenue, net income/profit and other metrics.
- DEAL VALUE: distinguish equity value, enterprise value, transaction value and other valuation conventions.
- RELEASE: distinguish limited/special-format/event/wide theatrical, streaming, PVOD/VOD and announcement vs actual availability.
- TITLE IDENTITY: distinguish new film/sequel/prequel/remake/reboot/re-release/extended cut/new version when supported.
- Conflicting figures/definitions require attribution; never flatten them into one unqualified fact.
- attribution_required=true ONLY for estimates, projections, conflicting figures, money/ranking claims, quotes, and claims that are still unconfirmed reports. Confirmed facts (cast, trailers released, titles, official announcements, release dates announced by the studio) are attribution_required=false even when one outlet reported them.
- Prefer fresh preferred evidence for volatile current values. Older values may stay only as explicitly historical claims.
- Do not create a current cumulative value from an opening-weekend figure.
- Do not create a weekly #1 claim from weekend evidence, or vice versa.
"""

NARRATION_CLAIM_EXTRACT_SYSTEM = """Audit a completed cinema-news narration against the supplied verified claim ledger.

Extract EVERY externally checkable factual statement. Do not extract opinions, jokes, rhetorical questions, transitions, or calls to action.

Return ONLY JSON:
{"claims":[{"story_id":"...","sentence":"exact narration sentence","claim_type":"box_office|ranking|budget|revenue|release|deal_value|title_identity|person_credit|cast|quote|award|production|company|other","subject":"...","predicate":"...","value_text":"","numeric_value":null,"currency":"","unit":"","metric":"","market":"","region":"","chart_type":"","rank":null,"period_type":"","date_start":"","date_end":"","as_of_date":"","release_scope":"","title_identity":"","estimate_status":"","attribution_present":false,"ledger_claim_ids":["C001"],"semantic_match":"exact|equivalent|partial|unsupported","notes":""}]}

HARD RULES:
- STORY markers define story_id boundaries.
- Extract every number, ranking, date, budget, revenue/gross, deal value, release-status claim, title-identity claim, person credit, cast claim, quote attribution, production fact and other checkable assertion.
- Split multiple atomic claims in one sentence.
- ledger_claim_ids may reference only supplied ledger IDs for the same story.
- Match meaning, not just the same number.
- "opened to <amount> <market>" does not match "has reached <amount> <market>" (opening period vs cumulative total).
- weekend rank does not match weekly rank; domestic does not match worldwide.
- limited theatrical does not match wide theatrical.
- production budget does not match marketing spend.
- company revenue does not match box-office gross.
- If no ledger claim supports the exact meaning, use semantic_match=unsupported and no ledger IDs.
"""

# Whole-word matching. Persian terms may carry common attached suffixes
# (گیشهٔ، فروشش، اکرانِ...) but must not match inside other words:
# «بازاکران» is not «اکران», «فروشگاه» is not «فروش», «هزاران» is not «هزار».
_FA_SUFFIX = r"(?:‌?(?:های|ها|اش|شون|تون|مون|ش|ی|ه))?ٔ?"
_FA_RISK_TERMS = (
    r"میلیون|میلیارد|هزار|درصد|بودجه|درآمد|فروش|گیشه|رتبه|صدر\s*جدول|"
    r"اکران|معامله|ارزش\s+(?:معامله|خرید|بازار|قرارداد)|دلار"
)
_EN_RISK_TERMS = (
    r"million|billion|percent|budget|revenue|gross(?:ed|es)?|box\s*office|"
    r"rank(?:ed|ing|s)?|number\s+one|top(?:ped|s)?\s+the\s+chart|"
    r"release[sd]?|streaming|theatrical|valuation|enterprise\s+value|equity\s+value"
)
HIGH_RISK_RE = re.compile(
    r"(?:[0-9۰-۹٠-٩]+(?:[.,٬٫][0-9۰-۹٠-٩]+)*|[$€£¥%]|#\s*[0-9۰-۹]|"
    rf"(?<![\w‌])(?:{_FA_RISK_TERMS}){_FA_SUFFIX}(?!\w)|"
    rf"\b(?:{_EN_RISK_TERMS})\b)",
    re.IGNORECASE,
)

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫٬", "01234567890123456789.,")

FINANCIAL_CLAIM_TYPES = {"budget", "revenue", "box_office", "deal_value"}

ATTRIBUTABLE_CLAIM_TYPES = {"box_office", "ranking", "budget", "revenue", "deal_value", "quote"}
UNCONFIRMED_REPORT_RE = re.compile(
    r"\b(report(?:ed|edly|s)?|sources?|insiders?|exclusive(?:ly)?|allegedly|rumou?r(?:ed|s)?|"
    r"according\s+to|people\s+familiar|in\s+talks|expected\s+to|plans?\s+to)\b",
    re.IGNORECASE,
)

MONEY_OR_PERCENT_RE = re.compile(
    r"([$€£¥]|\b(?:usd|eur|gbp|dollars?|million|billion|percent)\b|%|"
    r"دلار|یورو|پوند|میلیون|میلیارد|درصد)",
    re.IGNORECASE,
)


def _has_money_or_percent(text: str) -> bool:
    return bool(MONEY_OR_PERCENT_RE.search(str(text or "")))


def _numbers_in_text(text: str) -> list[float]:
    plain = str(text or "").translate(PERSIAN_DIGITS)
    values = []
    for raw in re.findall(r"\d+(?:[.,]\d+)*", plain):
        cleaned = raw.replace(",", "") if re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw) else raw.replace(",", ".")
        try:
            values.append(float(cleaned))
        except ValueError:
            continue
    return values


def _json_object(value: str) -> dict:
    raw = str(value or "").strip()
    fence = chr(96) * 3
    if raw.startswith(fence):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit(fence, 1)[0]
    first, last = raw.find("{"), raw.rfind("}")
    if first < 0 or last < first:
        raise ValueError("Claim AI response did not contain a JSON object.")
    parsed = json.loads(raw[first:last + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Claim AI response JSON was not an object.")
    return parsed


def _clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _float(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value):
    number = _float(value)
    return int(number) if number is not None and float(number).is_integer() else None


def _normalize_unit(value: str) -> str:
    text = _clean(value).casefold()
    aliases = {
        "m": "million", "mn": "million", "million": "million", "میلیون": "million",
        "b": "billion", "bn": "billion", "billion": "billion", "میلیارد": "billion",
        "k": "thousand", "thousand": "thousand", "هزار": "thousand",
        "%": "percent", "percent": "percent", "percentage": "percent", "درصد": "percent",
    }
    return aliases.get(text, text)


def _scaled_number(value, unit: str):
    number = _float(value)
    if number is None:
        return None
    scale = {"thousand": 1e3, "million": 1e6, "billion": 1e9}.get(_normalize_unit(unit), 1.0)
    return number * scale


def _decimal_places(value: float) -> int:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return len(text.split(".")[1]) if "." in text else 0


def _same_number(a: dict, b: dict) -> bool:
    """a = spoken claim, b = ledger claim.

    Exact matches pass. A spoken figure may also be the ledger figure rounded
    (half-up) or truncated to the precision the narrator actually used, in the
    narrator's own unit: 42.7 million may be spoken as 43 million, 1,234
    million as 1.2 billion. A different figure (45 for 42.7) still fails.
    """
    av = _scaled_number(a.get("numeric_value"), a.get("unit") or "")
    bv = _scaled_number(b.get("numeric_value"), b.get("unit") or "")
    if av is None or bv is None:
        return av is None and bv is None
    if abs(av - bv) <= max(1e-6, abs(bv) * 0.0005):
        return True
    spoken = _float(a.get("numeric_value"))
    scale = {"thousand": 1e3, "million": 1e6, "billion": 1e9}.get(_normalize_unit(a.get("unit") or ""), 1.0)
    if spoken is None or not scale:
        return False
    ledger_in_spoken_unit = bv / scale
    places = _decimal_places(spoken)
    factor = 10 ** places
    rounded = math.floor(abs(ledger_in_spoken_unit) * factor + 0.5) / factor
    truncated = math.floor(abs(ledger_in_spoken_unit) * factor) / factor
    return any(abs(abs(spoken) - candidate) < 1e-9 for candidate in (rounded, truncated))


def _number_supported(spoken: dict, ledger: dict) -> bool:
    """A spoken number is supported by a ledger claim.

    Financial ledger claims carry a structured value and are compared by value.
    Plain facts (dates, counts, years) often have no structured value; then the
    spoken number must literally appear in the ledger claim's own text.
    """
    if _float(ledger.get("numeric_value")) is not None:
        return _same_number(spoken, ledger)
    target = _float(spoken.get("numeric_value"))
    if target is None:
        return True
    ledger_text = " ".join(str(ledger.get(key) or "") for key in ("canonical_text", "value_text", "date_start", "date_end", "as_of_date"))
    return any(abs(value - target) < 1e-9 for value in _numbers_in_text(ledger_text))


def _source_index(stories: list[dict], fresh_sources: dict[str, list[dict]]) -> dict[str, dict[str, dict]]:
    output = {}
    for story in stories:
        sid = str(story.get("id") or "")
        bucket = {}
        for source in [*(story.get("articles") or []), *(story.get("spice_sources") or []), *(fresh_sources.get(sid) or [])]:
            url = _clean(source.get("url"))
            if url:
                bucket[url] = dict(source)
        output[sid] = bucket
    return output


def _sibling_source_index(stories: list[dict], sources: dict[str, dict[str, dict]]) -> dict[str, dict[str, dict]]:
    from .research import story_subject_key

    def key_for(story: dict) -> str:
        subject = str(story.get("search_subject") or "").strip()
        if not subject:
            subject = re.sub(r"\s+-\s+[^-]{2,80}$", "", str(story.get("canonical_title") or ""))
        return story_subject_key(subject)

    by_key: dict[str, list[str]] = {}
    keys: dict[str, str] = {}
    for story in stories:
        sid = str(story.get("id") or "")
        key = key_for(story) if str(story.get("search_subject") or "").strip() else ""
        keys[sid] = key
        if key:
            by_key.setdefault(key, []).append(sid)
    output: dict[str, dict[str, dict]] = {}
    for sid, own in sources.items():
        merged = dict(own)
        for sibling in by_key.get(keys.get(sid, ""), []) if keys.get(sid) else []:
            for url, source in sources.get(sibling, {}).items():
                merged.setdefault(url, source)
        output[sid] = merged
    return output


def _ledger_input(stories: list[dict], fresh_sources: dict[str, list[dict]], project: dict) -> dict:
    return {
        "project_window": {
            "date_start": project.get("date_start"),
            "date_end_exclusive": project.get("date_end"),
            "language": project.get("language"),
        },
        "stories": [{
            "id": story.get("id"),
            "category": story.get("category"),
            "canonical_title": story.get("canonical_title"),
            "summary": story.get("summary"),
            "news_hook": story.get("news_hook"),
            "news_hook_date": story.get("news_hook_date"),
            "verification_status": story.get("verification_status"),
            "articles": [{
                "title": source.get("title"), "url": source.get("url"), "source": source.get("source"),
                "published_at": source.get("published_at"), "temporal_role": source.get("temporal_role"),
                "snippet": source.get("snippet"),
                "description": source.get("description") or "",
                "excerpt": source.get("excerpt") or "",
            } for source in story.get("articles") or []],
            "context_sources": [{
                "title": source.get("title"), "url": source.get("url"), "source": source.get("source"),
                "published_at": source.get("published_at"), "temporal_role": source.get("temporal_role"),
                "snippet": source.get("snippet"),
            } for source in story.get("spice_sources") or []],
            "fresh_verification_sources": fresh_sources.get(str(story.get("id") or ""), []),
        } for story in stories],
    }


def normalize_ledger_claims(raw_claims: object, stories: list[dict], fresh_sources: dict[str, list[dict]]) -> list[dict]:
    if not isinstance(raw_claims, list):
        return []
    story_ids = {str(story.get("id") or "") for story in stories}
    sources = _source_index(stories, fresh_sources)
    sibling_sources = _sibling_source_index(stories, sources)
    output = []
    for index, raw in enumerate(raw_claims):
        if not isinstance(raw, dict):
            continue
        story_id = _clean(raw.get("story_id"))
        if story_id not in story_ids:
            continue
        claim_type = _clean(raw.get("claim_type")).lower()
        if claim_type not in CLAIM_TYPES:
            claim_type = "other"
        # A story's own sources plus those of other approved stories about the
        # same subject (duplicate coverage of one event), so a fact is not
        # blocked just because its article was filed under the sibling story.
        allowed_urls = sibling_sources.get(story_id, {})
        source_urls = []
        for url in raw.get("source_urls") or []:
            url = _clean(url)
            if url and url in allowed_urls and url not in source_urls:
                source_urls.append(url)
        status = _clean(raw.get("verification_status")).lower()
        if status not in VERIFY_STATUSES:
            status = "blocked"
        numeric_value = _float(raw.get("numeric_value"))
        rank = _int(raw.get("rank"))
        canonical_text = _clean(raw.get("canonical_text"))
        source_names = list(dict.fromkeys(
            _clean(allowed_urls[url].get("source") or "") for url in source_urls
            if _clean(allowed_urls[url].get("source") or "")
        ))
        trust_tiers = [_clean(allowed_urls[url].get("trust_tier") or "") for url in source_urls]
        source_tier = "preferred" if "preferred" in trust_tiers else ("supplemental" if any(trust_tiers) else "")
        reasons = []
        if not source_urls:
            status = "blocked"
            reasons.append("No supplied source URL supports this claim.")
        # Only money/percentage figures need a structured numeric value. Dates,
        # years, counts ("12 states"), episode/season numbers and formats are
        # ordinary facts; blocking them stripped release dates from scripts.
        needs_structured_number = (
            claim_type in FINANCIAL_CLAIM_TYPES
            or (claim_type != "ranking" and _has_money_or_percent(canonical_text))
        )
        if needs_structured_number and numeric_value is None:
            status = "blocked"
            reasons.append("Financial/percentage claim is missing a structured numeric value.")
        market = _clean(raw.get("market"))
        chart_type = _clean(raw.get("chart_type")).lower()
        period_type = _clean(raw.get("period_type")).lower()
        date_start = _clean(raw.get("date_start"))
        date_end = _clean(raw.get("date_end"))
        all_time_chart = bool(re.search(r"all[\s-]?time|lifetime|highest[\s-]grossing|record", chart_type))
        if claim_type == "ranking" and (
            rank is None or not chart_type or not market
            or (not all_time_chart and (not date_start or not date_end))
        ):
            status = "blocked"
            reasons.append("Ranking requires rank, chart type, market, and an exact date range (all-time charts excepted).")
        if claim_type == "box_office" and numeric_value is not None and (not market or not period_type):
            status = "blocked"
            reasons.append("Box-office number requires market and period type.")
        if claim_type == "budget" and not _clean(raw.get("metric")):
            status = "blocked"
            reasons.append("Budget claim must identify production/marketing/other budget metric.")
        if claim_type in {"revenue", "deal_value"} and not _clean(raw.get("metric")):
            status = "blocked"
            reasons.append("Financial claim must identify its exact metric/valuation definition.")
        estimate_status = _clean(raw.get("estimate_status")).lower()
        conflict_note = _clean(raw.get("conflict_note"))
        # Attribution is spoken aloud, so it is kept only where it informs the
        # viewer: estimates/projections/conflicts, money/ranking/quote claims,
        # and claims worded as unconfirmed reports. Routine confirmed facts
        # (cast, trailers, titles, official announcements) need no spoken source.
        attribution_required = bool(raw.get("attribution_required")) and (
            claim_type in ATTRIBUTABLE_CLAIM_TYPES or bool(UNCONFIRMED_REPORT_RE.search(canonical_text))
        )
        if estimate_status in {"reported_estimate", "projection", "approximate", "conflicting"} or conflict_note:
            attribution_required = True
        if status in {"verified", "verified_with_attribution"}:
            status = "verified_with_attribution" if attribution_required else "verified"
        output.append({
            "id": f"C{index + 1:03d}",
            "story_id": story_id, "claim_type": claim_type, "subject": _clean(raw.get("subject")),
            "predicate": _clean(raw.get("predicate")), "canonical_text": canonical_text,
            "value_text": _clean(raw.get("value_text")), "numeric_value": numeric_value,
            "currency": _clean(raw.get("currency")).upper(), "unit": _normalize_unit(raw.get("unit") or ""),
            "metric": _clean(raw.get("metric")).lower(), "market": market.lower(),
            "region": _clean(raw.get("region")), "chart_type": chart_type, "rank": rank,
            "period_type": period_type, "date_start": date_start, "date_end": date_end,
            "as_of_date": _clean(raw.get("as_of_date")), "release_scope": _clean(raw.get("release_scope")).lower(),
            "title_identity": _clean(raw.get("title_identity")).lower(), "estimate_status": estimate_status,
            "attribution_required": attribution_required, "attribution_label": _clean(raw.get("attribution_label")),
            "source_urls": source_urls, "source_names": source_names, "source_tier": source_tier,
            "evidence_summary": _clean(raw.get("evidence_summary")), "conflict_note": conflict_note,
            "verification_status": status, "validation_notes": reasons,
        })
    return output


def build_claim_ledger(stories, project, fresh_sources, provider, model):
    raw, actual_provider, actual_model = generate_text(
        provider, model, CLAIM_LEDGER_SYSTEM,
        json.dumps(_ledger_input(stories, fresh_sources, project), ensure_ascii=False),
    )
    parsed = _json_object(raw)
    return normalize_ledger_claims(parsed.get("claims"), stories, fresh_sources), actual_provider, actual_model


def ledger_for_writer(claims: list[dict]) -> list[dict]:
    keys = (
        "id", "story_id", "claim_type", "subject", "predicate", "canonical_text", "value_text",
        "numeric_value", "currency", "unit", "metric", "market", "region", "chart_type", "rank",
        "period_type", "date_start", "date_end", "as_of_date", "release_scope", "title_identity",
        "estimate_status", "attribution_required", "attribution_label", "source_names",
        "verification_status", "conflict_note",
    )
    return [{key: claim.get(key) for key in keys} for claim in claims
            if claim.get("verification_status") in {"verified", "verified_with_attribution"}]


_SCOPE_CANON = {
    # field -> ordered (canonical, pattern) pairs; first match wins.
    "market": (
        ("worldwide", r"worldwide|global|world|جهانی"),
        ("international", r"international|overseas|foreign|outside\s+(?:the\s+)?(?:us|u\.s\.|north\s+america)|بین\s*[‌ ]?المللی|خارج"),
        ("domestic", r"domestic|north\s+america|us\s*(?:/|&|and)\s*canada|\bu\.?s\.?\b|united\s+states|داخلی|آمریکای\s+شمالی|آمریکا"),
    ),
    "period_type": (
        ("cumulative", r"cumulative|running\s+total|to[\s-]date|lifetime|تجمعی"),
        ("weekend", r"weekend|fri(?:day)?\s*[-–]\s*sun(?:day)?|آخر\s*[‌ ]?هفته"),
        ("weekly", r"weekly|\bweek\b|7[\s-]day|هفتگی"),
        ("daily", r"daily|\bday\b|روزانه"),
    ),
    "chart_type": (
        ("weekend", r"weekend|آخر\s*[‌ ]?هفته"),
        ("weekly", r"weekly|\bweek\b|هفتگی"),
        ("daily", r"daily|\bday\b|روزانه"),
    ),
    "release_scope": (
        ("re_release", r"re-?release|re-?issue|بازاکران|اکران\s+مجدد"),
        ("limited_theatrical", r"limited|select|special|event|festival|imax|محدود|انتخابی|ویژه"),
        ("wide_theatrical", r"wide|nationwide|general|سراسری|عمومی"),
        ("streaming", r"stream|svod|platform|استریم"),
        ("vod", r"pvod|vod|digital|rental|premium|دیجیتال"),
        ("theatrical", r"theat(?:er|re|rical)|cinema|سینما|اکران"),
    ),
    "metric": (
        ("marketing_spend", r"marketing|p&a|promotion|advertis|تبلیغ"),
        ("enterprise_value", r"enterprise"),
        ("equity_value", r"equity"),
        ("net_income", r"net\s+income|profit|سود"),
        ("operating_income", r"operating|ebitda"),
        ("production_budget", r"production\s+budget|budget|بودجه"),
        ("transaction_value", r"transaction|deal|purchase|acquisition|takeover|merger|خرید|معامله|ادغام"),
        ("box_office_gross", r"gross|box\s*office|ticket|گیشه|فروش\s+(?:بلیت|سینمایی)"),
        ("revenue", r"revenue|sales|درآمد"),
    ),
    "title_identity": (
        ("re_release", r"re-?release|re-?issue|remaster|anniversary|بازاکران|اکران\s+مجدد"),
        ("extended_cut", r"extended|director'?s\s+cut|new\s+cut|نسخه\s+کامل"),
        ("sequel", r"sequel|دنباله"),
        ("prequel", r"prequel|پیش\s*[‌ ]?درآمد"),
        ("remake", r"remake|بازسازی"),
        ("reboot", r"reboot|ریبوت"),
        ("new_film", r"new\s+(?:film|movie)|original|فیلم\s+(?:جدید|تازه)"),
    ),
}


def _canonical_scope(field: str, value) -> str:
    text = _clean(value).casefold()
    if not text:
        return ""
    for canonical, pattern in _SCOPE_CANON.get(field, ()):
        if re.search(pattern, text, flags=re.IGNORECASE):
            return canonical
    return text


def _field_equal(spoken, ledger, field: str = "") -> bool:
    a, b = _clean(spoken), _clean(ledger)
    if not a:
        return True
    if not b:
        return False
    if field in _SCOPE_CANON:
        return _canonical_scope(field, a) == _canonical_scope(field, b)
    return a.casefold() == b.casefold()


def _attribution_present(sentence: str, claim: dict, extractor_value: bool) -> bool:
    if not claim.get("attribution_required"):
        return True
    if not extractor_value:
        return False
    return bool(re.search(
        r"(طبق|بر\s+اساس|گزارش|به\s+گفته|گفته|می[\u200c ]?گ(?:ه|ن|ید)|اعلام|according|reported|reports?|says?|"
        r"estimat(?:e|ed)|حدود|تقریباً|برآورد)",
        _clean(sentence).casefold(), flags=re.IGNORECASE,
    ))


def _validate_spoken_claim(raw: dict, ledger_by_id: dict[str, dict]) -> dict:
    ids = [str(value) for value in raw.get("ledger_claim_ids") or [] if str(value) in ledger_by_id]
    sentence = _clean(raw.get("sentence"))
    story_id = _clean(raw.get("story_id"))
    semantic_match = _clean(raw.get("semantic_match")).lower()
    matched = [ledger_by_id[value] for value in ids if ledger_by_id[value].get("story_id") == story_id]
    reasons = []
    if semantic_match not in {"exact", "equivalent"}:
        reasons.append("Narration claim is not an exact/equivalent ledger match.")
    if not matched:
        reasons.append("No verified ledger claim supports this narration claim.")
    if any(claim.get("verification_status") == "blocked" for claim in matched):
        reasons.append("Mapped ledger claim is blocked.")
    numeric_value = _float(raw.get("numeric_value"))
    if numeric_value is not None and matched and not any(_number_supported(raw, claim) for claim in matched):
        reasons.append("Numeric value/unit does not match the supporting ledger claim.")
    claim_type = _clean(raw.get("claim_type")).lower() or "other"
    if matched and claim_type == "ranking":
        compatible = [claim for claim in matched if claim.get("claim_type") == "ranking"
                      and (_int(raw.get("rank")) is None or _int(raw.get("rank")) == claim.get("rank"))
                      and _field_equal(raw.get("chart_type"), claim.get("chart_type"), "chart_type")
                      and _field_equal(raw.get("market"), claim.get("market"), "market")
                      and _field_equal(raw.get("date_start"), claim.get("date_start"))
                      and _field_equal(raw.get("date_end"), claim.get("date_end"))]
        if not compatible:
            reasons.append("Ranking scope/date does not match the ledger.")
    if matched and claim_type == "box_office":
        if not any(claim.get("claim_type") in {"box_office", "ranking"}
                   and _field_equal(raw.get("market"), claim.get("market"), "market")
                   and _field_equal(raw.get("period_type"), claim.get("period_type"), "period_type") for claim in matched):
            reasons.append("Box-office market/period scope does not match the ledger.")
    if matched and claim_type in {"budget", "revenue", "deal_value"}:
        if not any(claim.get("claim_type") == claim_type
                   and _field_equal(raw.get("metric"), claim.get("metric"), "metric") for claim in matched):
            reasons.append("Financial metric/valuation definition does not match the ledger.")
    if matched and claim_type == "release":
        if not any(claim.get("claim_type") == "release"
                   and _field_equal(raw.get("release_scope"), claim.get("release_scope"), "release_scope") for claim in matched):
            reasons.append("Release scope does not match the ledger.")
    if matched and claim_type == "title_identity":
        if not any(claim.get("claim_type") == "title_identity"
                   and _field_equal(raw.get("title_identity"), claim.get("title_identity"), "title_identity") for claim in matched):
            reasons.append("Title identity does not match the ledger.")
    attribution_needed = any(claim.get("attribution_required") for claim in matched)
    if attribution_needed and not any(
        _attribution_present(sentence, claim, bool(raw.get("attribution_present")))
        for claim in matched if claim.get("attribution_required")
    ):
        reasons.append("Claim requires explicit attribution/estimate framing.")
    status = "blocked" if reasons else ("verified_with_attribution" if attribution_needed else "verified")
    return {
        "id": str(uuid.uuid4()), "story_id": story_id, "sentence": sentence,
        "claim_type": claim_type if claim_type in CLAIM_TYPES else "other",
        "subject": _clean(raw.get("subject")), "predicate": _clean(raw.get("predicate")),
        "value_text": _clean(raw.get("value_text")), "numeric_value": numeric_value,
        "currency": _clean(raw.get("currency")).upper(), "unit": _normalize_unit(raw.get("unit") or ""),
        "metric": _clean(raw.get("metric")).lower(), "market": _clean(raw.get("market")).lower(),
        "region": _clean(raw.get("region")), "chart_type": _clean(raw.get("chart_type")).lower(),
        "rank": _int(raw.get("rank")), "period_type": _clean(raw.get("period_type")).lower(),
        "date_start": _clean(raw.get("date_start")), "date_end": _clean(raw.get("date_end")),
        "as_of_date": _clean(raw.get("as_of_date")), "release_scope": _clean(raw.get("release_scope")).lower(),
        "title_identity": _clean(raw.get("title_identity")).lower(),
        "estimate_status": _clean(raw.get("estimate_status")).lower(),
        "attribution_present": bool(raw.get("attribution_present")),
        "ledger_claim_ids": [claim["id"] for claim in matched], "status": status,
        "issue": " ".join(reasons),
    }


def _plain_sentence(value: str) -> str:
    value = _clean(value).translate(PERSIAN_DIGITS)
    value = re.sub(r"[\s\u200c]+", " ", value)
    return re.sub(r"[^\w\u0600-\u06FF$€£¥%#.,:/ -]+", "", value).casefold().strip()


def _story_sentences(draft_text: str) -> list[dict]:
    current_story = ""
    output = []
    chunks = re.split(r"(<!--\s*STORY:[^>]+-->)", draft_text or "")
    for chunk in chunks:
        marker = re.match(r"<!--\s*STORY:([^>\s]+)\s*-->", chunk.strip())
        if marker:
            current_story = marker.group(1).strip()
            continue
        if not current_story:
            continue
        cleaned = re.sub(r"^\s*#+\s+.*$", " ", chunk, flags=re.MULTILINE)
        for sentence in re.split(r"(?<=[.!?؟])\s+|\n+", cleaned):
            sentence = _clean(sentence)
            if sentence:
                output.append({"story_id": current_story, "sentence": sentence})
    return output


def high_risk_sentences(draft_text: str) -> list[dict]:
    return [item for item in _story_sentences(draft_text) if HIGH_RISK_RE.search(item["sentence"])]


def _covered_by_extraction(high_risk: dict, claims: list[dict]) -> bool:
    target = _plain_sentence(high_risk["sentence"])
    for claim in claims:
        if claim.get("story_id") != high_risk.get("story_id"):
            continue
        sentence = _plain_sentence(claim.get("sentence") or "")
        if sentence and (sentence in target or target in sentence):
            return True
    return False


def audit_narration_claims(draft_text, ledger, provider, model):
    packet = {"claim_ledger": ledger_for_writer(ledger), "draft": draft_text}
    try:
        raw, actual_provider, actual_model = generate_text(
            provider, model, NARRATION_CLAIM_EXTRACT_SYSTEM, json.dumps(packet, ensure_ascii=False)
        )
        parsed = _json_object(raw)
        raw_claims = parsed.get("claims") if isinstance(parsed.get("claims"), list) else []
    except Exception as exc:
        return {
            "status": "blocked", "claim_count": 0, "verified_count": 0,
            "attributed_count": 0, "blocked_count": 1,
            "uncovered_high_risk_count": len(high_risk_sentences(draft_text)),
            "claims": [], "system_issues": [f"Claim extraction failed: {exc}"],
        }, provider, model
    ledger_by_id = {str(claim.get("id")): claim for claim in ledger}
    claims = [_validate_spoken_claim(item, ledger_by_id) for item in raw_claims if isinstance(item, dict)]
    uncovered = [item for item in high_risk_sentences(draft_text) if not _covered_by_extraction(item, claims)]
    system_issues = [
        f"High-risk sentence was not extracted into the claim audit: {item['sentence']}" for item in uncovered
    ]
    verified = sum(1 for claim in claims if claim["status"] == "verified")
    attributed = sum(1 for claim in claims if claim["status"] == "verified_with_attribution")
    blocked = sum(1 for claim in claims if claim["status"] == "blocked") + len(uncovered)
    return {
        "status": "pass" if blocked == 0 else "blocked", "claim_count": len(claims),
        "verified_count": verified, "attributed_count": attributed, "blocked_count": blocked,
        "uncovered_high_risk_count": len(uncovered), "claims": claims,
        "system_issues": system_issues,
    }, actual_provider, actual_model


def ledger_summary(claims: Iterable[dict]) -> dict:
    claims = list(claims)
    return {
        "total": len(claims),
        "verified": sum(1 for claim in claims if claim.get("verification_status") == "verified"),
        "attributed": sum(1 for claim in claims if claim.get("verification_status") == "verified_with_attribution"),
        "blocked": sum(1 for claim in claims if claim.get("verification_status") == "blocked"),
    }
