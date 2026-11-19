"""Relevance = two gates, then a learning score.

1. SECTOR gate: the company must be in a target sector (start-up / fintech,
   venture capital, private equity, asset management, banking / M&A advisory,
   insurance / risk, consulting). Known companies get their sector and fame
   tier from config.yaml (`companies:` and `known_firms:`); unknown companies
   (Adzuna, France Travail) are classified from the offer text.
   Large corporates outside these sectors are kept only for core strategy /
   corporate-development / M&A / corporate-finance roles.
2. ROLE gate: engineering, quant and marketing roles (and support, HR,
   legal...) are hidden everywhere. The role must name a target function:
   investment, strategy, consulting, business development, corporate finance,
   risk... "Adjacent" roles (pure sales, operations, accounting) are kept but
   can never rank high.
3. LEARNING score: what the intern actually DOES. High-value tasks (models,
   valuation, due diligence, market studies, investment memos...) and direct
   exposure to founders / partners / C-level raise it. Repetitive tasks
   (data entry, cold calling, CRM updates, invoicing, admin, "assistant"
   roles) and buzzword-heavy descriptions with no concrete tasks lower it.

All keyword lists live in config.yaml under `relevance:`.
"""
from __future__ import annotations

import re

from .dedupe import company_key
from .text import contains_any, norm


# ---------------------------------------------------------------- company
def _firm_index(cfg: dict) -> dict:
    """company_key -> {"sector", "tier", "name"} from companies + known_firms."""
    idx = cfg.get("_firm_index")
    if idx is not None:
        return idx
    idx = {}
    rc = cfg["relevance"]
    entries = [(f, f["sector"]) for f in rc.get("known_firms", [])] + \
              [(c, c.get("type", "other")) for c in cfg.get("companies", [])]
    for f, sector in entries:
        for n in [f["name"], *f.get("aliases", [])]:
            n = re.sub(r"\(.*?\)", "", n)          # "Sumeria (ex-Lydia)" -> "Sumeria"
            idx[company_key(n)] = {"sector": sector, "tier": f.get("tier", 2),
                                   "name": f["name"], "words": _words(n)}
    cfg["_firm_index"] = idx
    return idx


_LEGAL = {"sas", "sa", "sasu", "sarl", "inc", "ltd", "llc", "gmbh", "plc", "se", "ag",
          "group", "groupe", "france", "&", "and", "et", "co"}


def _words(name: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", norm(name)) if w not in _LEGAL]


def _lookup(company: str, cfg: dict):
    idx = _firm_index(cfg)
    k = company_key(company)
    if not k:
        return None
    if k in idx:
        return idx[k]
    # "BNP Paribas Asset Management", "Société Générale CIB" ... -> parent firm
    # (whole leading words only, so "Alan" does not match "Alanya Hotels")
    words = _words(company)
    best = None
    for v in idx.values():
        fw = v["words"]
        if len(fw) and words[:len(fw)] == fw and len("".join(fw)) >= 3 and \
                (best is None or len(fw) > len(best["words"])):
            best = v
    return best


def classify_company(company: str, company_type: str, description: str, cfg: dict):
    """Returns (sector, tier, how) where how is 'listed' or 'content'.
    sector is None when the company is not in a target sector."""
    rc = cfg["relevance"]
    hit = _lookup(company, cfg)
    if hit:
        return hit["sector"], hit["tier"], "listed"
    if company_type and company_type not in ("other", ""):
        return company_type, 3, "listed"
    # unknown company: classify from what the offer says about it
    d = norm(description[:4000])
    best = None
    for sector, kws in rc["sector_keywords"].items():
        n = len(contains_any(d, kws))
        if n and (best is None or n > best[1]):
            best = (sector, n)
    if best:
        return best[0], 4, "content"
    return None, None, "content"


def company_score(sector: str | None, tier: int | None, cfg: dict) -> int:
    if not sector:
        return 0
    return cfg["relevance"]["tier_scores"].get(tier, 55)


# ---------------------------------------------------------------- role
def _generic(t: str, company: str) -> bool:
    words = set(re.findall(r"[a-z&']+", t)) - set(norm(company).split())
    noise = set("""stage stagiaire stagiaires intern interns internship internships
    program programme summer winter spring off cycle general generalist business
    graduate f h m w x d e de du des la le les et and the of in for a an h/f f/h
    paris france team equipe 2026 2027 mois months month""".split())
    return not (words - noise)


def classify_role(title: str, description: str, company: str, cfg: dict):
    """Returns (level, function_key, label, base_score, reason).

    level: 'excluded' | 'core' | 'adjacent' | 'none'"""
    rc = cfg["relevance"]
    t = norm(title)
    # target-function phrases are blanked before the exclusion check, so
    # "Business Developer" is not caught by "developer" (but "Brand
    # Partnerships" is still caught by "brand")
    t_rest = t
    for fn in rc["functions"]:
        for kw in sorted(contains_any(t, fn["keywords"]), key=len, reverse=True):
            if " " in norm(kw):
                t_rest = re.sub(r"(?<![a-z0-9])" + re.escape(norm(kw)) + r"(?![a-z0-9])",
                                " ", t_rest)
    # 1. never shown: engineering, quant, marketing, support, HR, legal...
    for group, kws in rc["excluded_roles"].items():
        hit = contains_any(t_rest, kws)
        if hit:
            # "growth" alone is usually growth marketing, unless the title also
            # names a target function ("Strategy & Growth")
            if group == "marketing" and hit == ["growth"] and _function(t, rc):
                continue
            return "excluded", None, None, 0, f"{group}: {hit[0]}"
    f = _function(t, rc)
    if f:
        return (*f, "")
    # 2. generic title ("Summer Internship Program") -> judged on the description
    if _generic(t, company):
        d = norm(description)
        best = None
        for fn in rc["functions"]:
            n = len(contains_any(d, fn["keywords"]))
            if n >= 2 and (best is None or fn["score"] > best["score"]):
                best = fn
        if best:
            return (best["level"], best["key"], best["label"],
                    best["score"] - rc.get("generic_title_penalty", 15), "generic title")
    return "none", None, None, 0, "no target function in the title"


def _function(t: str, rc: dict):
    """Best-scoring target function named in the (normalised) title."""
    best = None
    for fn in rc["functions"]:
        if not contains_any(t, fn["keywords"]):
            continue
        if fn.get("override"):          # e.g. "Fund Accounting": accounting, not investment
            best = fn
            break
        if best is None or fn["score"] > best["score"]:
            best = fn
    if not best:
        return None
    return best["level"], best["key"], best["label"], best["score"]


# ---------------------------------------------------------------- learning
def learning_adjustment(title: str, description: str, cfg: dict):
    """(points, notes): how much the intern learns, judged on the tasks."""
    lc = cfg["relevance"]["learning"]
    t, d = norm(title), norm(description)
    pts, notes = 0, []

    high = contains_any(d, lc["high_value_tasks"])
    if high:
        pts += min(len(high) * lc.get("high_value_points", 4), lc.get("high_value_max", 20))
        notes.append("hands-on: " + ", ".join(high[:3]))

    expo = contains_any(d, lc["exposure"])
    if expo:
        pts += min(len(expo) * 5, 10)
        notes.append("exposure: " + expo[0])

    rep = contains_any(d + " " + t, lc["repetitive_tasks"])
    if rep:
        pts -= min(len(rep) * lc.get("repetitive_points", 6), lc.get("repetitive_max", 30))
        notes.append("repetitive: " + ", ".join(rep[:3]))

    asst = contains_any(t, lc["assistant_titles"])
    if asst:
        pts -= lc.get("assistant_penalty", 15)
        notes.append("assistant role")

    buzz = contains_any(d, lc["buzzwords"])
    if len(buzz) >= lc.get("buzz_min", 4) and len(high) <= 1:
        pts -= lc.get("buzz_penalty", 12)
        notes.append("buzzwords, few concrete tasks")

    vague = contains_any(d, cfg["clarity"]["vague_phrases"])
    if vague:
        pts -= 5 * min(len(vague), 2)

    if len(description) < lc.get("short_description_chars", 600):
        pts -= lc.get("short_description_penalty", 10)
        notes.append("too little detail to judge the tasks")
    return pts, notes


# ---------------------------------------------------------------- all-in-one
def evaluate(title: str, description: str, company: str, company_type: str, cfg: dict):
    """Returns a dict, or (None, reason) when the offer must be hidden."""
    rc = cfg["relevance"]
    level, fkey, flabel, base, why = classify_role(title, description, company, cfg)
    if level == "excluded":
        return None, f"role excluded ({why})"
    if level == "none":
        return None, "role not in target functions"
    if level == "adjacent" and fkey == "sales":
        shop = contains_any(norm(description), rc.get("in_store_phrases", []))
        if shop:
            return None, f"role excluded (retail_sales: {shop[0]})"
    sector, tier, how = classify_company(company, company_type, description, cfg)
    if not sector:
        return None, "company not in a target sector"
    sec = rc["sectors"].get(sector, {})
    if not sec.get("target", False):
        # corporates (pharma, luxury, big tech...): only core strategy/finance roles
        allowed = set(sec.get("allowed_functions", []))
        if level != "core" or fkey not in allowed:
            return None, f"company sector {sector}: role not strategy/finance"
    learn, notes = learning_adjustment(title, description, cfg)
    role = max(0, min(100, base + learn))
    return {
        "level": level, "function": fkey, "function_label": flabel,
        "sector": sector, "sector_label": sec.get("label", sector), "tier": tier,
        "sector_how": how, "role_score": role, "learning": learn,
        "learning_notes": notes,
        "company_score": company_score(sector, tier, cfg),
    }, None
