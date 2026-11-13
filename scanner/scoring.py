"""0-100 score = weighted mix of role priority, mission clarity, date fit,
language and company-type fit (weights in config.yaml)."""
from __future__ import annotations

import re
from datetime import date

from .parsing import DurationInfo, StartInfo
from .text import contains_any, detect_language, norm


# ---------------------------------------------------------------- role
def role_score(title: str, description: str, company_type: str, clarity: int,
               cfg: dict):
    """Returns (score, matched category keys in priority order)."""
    t, d = norm(title), norm(description)
    matched, best = [], 20      # unmatched business role -> 20
    for cat in cfg["categories"]:
        key = cat["key"]
        title_hit = contains_any(t, cat["keywords"])
        desc_hits = contains_any(d, cat["keywords"])
        hit = False
        if key == "fintech":
            hit = company_type == "fintech" or (
                company_type in ("bank", "insurance", "asset_management") and
                (title_hit or len(desc_hits) >= 2))
        else:
            hit = bool(title_hit) or len(desc_hits) >= 3
        if not hit:
            continue
        matched.append(key)
        s = cat["score"]
        if key == "finance":
            concrete = contains_any(d + " " + t, cat.get("concrete_keywords", []))
            if len(concrete) >= cat.get("concrete_min_hits", 2) and clarity >= 50:
                s = cat.get("concrete_score", s)
        # a title match is stronger evidence than description words
        if not title_hit and key != "fintech":
            s -= 25
        best = max(best, s)
    if company_type == "pharma":
        matched.append("pharma")
    return best, matched


# ---------------------------------------------------------------- clarity
_BULLET = re.compile(r"^\s*(•|-|\*|–|\d+[.)])\s+\S", re.M)


def clarity_score(description: str, cfg: dict) -> tuple[int, list[str]]:
    c = cfg["clarity"]
    d = norm(description)
    why = []
    s = 0
    bullets = len(_BULLET.findall(description))
    if bullets >= 8:
        s += 25
        why.append(f"{bullets} listed tasks/requirements")
    elif bullets >= 4:
        s += 15
    verbs = contains_any(d, c["action_verbs"])
    s += min(len(verbs), 10) * 2                   # up to 20
    if contains_any(d, c["team_markers"]):
        s += 15
        why.append("named team/manager")
    tools = contains_any(d, c["tools"])
    if tools:
        s += min(len(tools), 3) * 5                # up to 15
        why.append("tools: " + ", ".join(tools[:3]))
    kpis = contains_any(d, c["kpi_markers"])
    if kpis:
        s += min(len(kpis), 3) * 5                 # up to 15
        why.append("KPIs/objectives")
    n = len(description)
    s += 10 if n > 2500 else 5 if n > 1200 else 0
    vague = contains_any(d, c["vague_phrases"])
    if vague:
        s -= 10 * min(len(vague), 2)
        why.append("vague wording")
    if n < 500:
        s -= 15
        why.append("very short description")
    return max(0, min(100, s)), why


# ---------------------------------------------------------------- dates
def date_score(dur: DurationInfo, start: StartInfo, cfg: dict) -> int:
    dc = cfg["dates"]
    s = 50                                          # nothing stated -> neutral
    if dur.stated:
        if dur.max_months <= 3 and dur.min_months >= 2:
            s += 30
        elif dur.min_months <= 3:
            s += 10                                 # e.g. "3-6 months": negotiable
    if start.stated and not start.asap:
        if any(d.month in dc["boost_start_months"] and d.year ==
               date.fromisoformat(str(dc["ideal_start"])).year for d in start.candidates):
            s += 20
        else:
            s += 5
    return max(0, min(100, s))


# ---------------------------------------------------------------- language
def language_info(title: str, description: str, cfg: dict) -> tuple[str, int]:
    lang = detect_language(description) if description else "unknown"
    if lang == "unknown":
        lang = detect_language(title + " " + description)
    lc = cfg["language"]
    english_env = bool(contains_any(norm(description), lc["english_markers"]))
    key = {"en": "english", "fr": "french", "de": "german"}.get(lang, "unknown")
    score = lc["scores"].get(key, 60)
    if english_env:
        score = max(score, lc["scores"]["english"] - 10 if key != "english" else 100)
    return lang, score


# ---------------------------------------------------------------- total
def total_score(parts: dict, cfg: dict) -> int:
    w = cfg["weights"]
    s = sum(parts[k] * w[k] for k in w)
    return int(round(s))
