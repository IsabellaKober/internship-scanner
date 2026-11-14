"""0-100 score = weighted mix of role priority, mission clarity, date fit,
language and company-type fit (weights in config.yaml)."""
from __future__ import annotations

import re
from datetime import date

from .parsing import DurationInfo, StartInfo
from .text import contains_any, detect_language, norm


# ---------------------------------------------------------------- role
_GENERIC_WORDS = set("""stage stagiaire intern interns internship internships program programme
summer winter spring off cycle general generalist business graduate f h m w x d e
de du des la le les et and the of in for a an h/f f/h paris france""".split())


def _generic_title(t_norm: str, company: str = "") -> bool:
    """True for titles that name no function, e.g. 'Summer Intern 2027 - Alan
    Summer Internship Program'. Those are judged on the description."""
    skip = _GENERIC_WORDS | set(norm(company).split())
    words = [w for w in re.findall(r"[a-z&]+", t_norm) if w not in skip]
    return not words


def role_score(title: str, description: str, company_type: str, clarity: int,
               cfg: dict, company: str = ""):
    """Returns (score, matched category keys in priority order).

    The ROLE (title) decides: a fintech company only boosts roles that are
    themselves sales / strategy / e-commerce / bizdev / finance. Off-path roles
    (content, legal, compliance, engineering...) score low wherever they are."""
    t, d = norm(title), norm(description)
    rc = cfg.get("role_rules", {})
    generic = _generic_title(t, company)
    cats = {c["key"]: c for c in cfg["categories"]}
    matched, best = [], rc.get("no_function_score", 10)

    for cat in cfg["categories"]:
        key = cat["key"]
        if key == "fintech":
            continue
        title_hit = contains_any(t, cat["keywords"])
        desc_hits = contains_any(d, cat["keywords"])
        if title_hit:
            s = cat["score"]
        elif generic and len(desc_hits) >= 2:
            s = cat["score"] - rc.get("generic_title_penalty", 20)
        else:
            continue
        if key == "finance":
            concrete = contains_any(d + " " + t, cat.get("concrete_keywords", []))
            if len(concrete) >= cat.get("concrete_min_hits", 2) and clarity >= 50:
                s = cat.get("concrete_score", s) - (0 if title_hit else rc.get("generic_title_penalty", 20))
        matched.append(key)
        best = max(best, s)

    # fintech = a target function (or a generic programme) in a fintech context
    fc = cats.get("fintech")
    if fc and matched:
        ft_title = contains_any(t, fc["keywords"])
        ft_desc = contains_any(d, fc["keywords"])
        fintech_ctx = (company_type == "fintech" or bool(ft_title) or
                       (company_type in ("bank", "insurance", "asset_management") and len(ft_desc) >= 2) or
                       (company_type == "other" and len(ft_desc) >= 3))
        if fintech_ctx:
            # a target role in fintech = top priority (a bit less when only
            # the description, not the title, says what the role is)
            best = max(best, fc["score"] - (0 if not generic else rc.get("generic_title_penalty", 20)))
            matched.insert(0, "fintech")
    if company_type == "pharma":
        matched.append("pharma")
    return best, matched


# ---------------------------------------------------------------- clarity
_BULLET = re.compile(r"^\s*(â€¢|-|\*|â€“|\d+[.)])\s+\S", re.M)


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
    (ideal_start..ideal_end, e.g. 1 May - 31 July 2027). Nothing stated scores
    low, so clear offers rank first."""
    dc = cfg["dates"]
    ideal_start = date.fromisoformat(str(dc["ideal_start"]))
    ideal_end = date.fromisoformat(str(dc["ideal_end"]))
    s = 0
    # duration: 3 months (or 2-3) is exactly what is wanted
    if dur.stated:
        if dur.max_months <= 3 and dur.min_months >= 2:
            s += 35
        elif dur.min_months <= 3:
            s += 15                                 # e.g. "3-6 months": negotiable
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
    # a role outside the target functions can never rank high
    gate = cfg.get("role_rules", {})
    if parts["role"] < gate.get("min_role_for_full_score", 40):
        s = min(s, gate.get("off_path_cap", 30))
    return int(round(s))
