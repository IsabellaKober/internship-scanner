"""0-100 score = weighted mix of role (function + learning, see relevance.py),
company (sector + fame tier), mission clarity, date fit and language
(weights in config.yaml)."""
from __future__ import annotations

import re
from datetime import date

from .parsing import DurationInfo, StartInfo
from .text import contains_any, detect_language, norm


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
    """Rewards offers that STATE dates matching the ideal window
    (ideal_start..ideal_end, e.g. 1 May - 31 July 2027). Nothing stated is
    neutral (50): many good offers simply don't say."""
    dc = cfg["dates"]
    ideal_start = date.fromisoformat(str(dc["ideal_start"]))
    ideal_end = date.fromisoformat(str(dc["ideal_end"]))
    s = 0
    # duration: 3 months (or 2-3) is exactly what is wanted; not stated = neutral
    if dur.stated:
        if dur.max_months <= 3 and dur.min_months >= 2:
            s += 35
        elif dur.min_months <= 3:
            s += 15                                 # e.g. "3-6 months": negotiable
    else:
        s += 17
    # start date
    real = list(start.candidates)       # "ASAP" = today -> far from May -> few points
    if real:
        def gap(d: date) -> int:                    # days away from the ideal start
            if d.day == 1 and d.month == ideal_start.month and d.year == ideal_start.year:
                return 0                            # "May 2027"
            return abs((d - ideal_start).days)
        g = min(gap(d) for d in real)
        s += 40 if g <= 10 else 30 if g <= 31 else 15 if g <= 62 else 5
        # end inside the window: start + duration (3 months if not stated)
        months = dur.max_months if dur.stated else 3
        first = min(real, key=gap)
        end_ord = first.toordinal() + int(round(months * 30.44))
        if end_ord <= ideal_end.toordinal() + 7:
            s += 25 if dur.stated else 10
    else:
        s += 33                                     # start not stated = neutral
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
def total_score(parts: dict, cfg: dict, level: str = "core") -> int:
    w = cfg["weights"]
    s = sum(parts[k] * w[k] for k in w)
    # adjacent roles (pure sales, operations, accounting) never rank high
    if level == "adjacent":
        s = min(s, cfg["relevance"].get("adjacent_cap", 55))
    return int(round(s))
