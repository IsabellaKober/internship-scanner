"""Hard filters. Each returns (keep: bool, reason: str, tags: list[str]).
An offer must pass all of them to be shown."""
from __future__ import annotations

import re
from datetime import date

from .parsing import DurationInfo, PayInfo, StartInfo, start_compatible
from .text import contains_any, norm


def _d(x) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x))


# ---------------------------------------------------------------- location
def check_location(location: str, description: str, cfg: dict):
    lc = cfg["location"]
    loc = norm(location)
    tags = []
    # postal codes 75xxx / 92xxx / ...
    pc_ok = any(re.search(rf"(?<!\d){p}\d{{3}}(?!\d)", loc) for p in lc["postal_prefixes"])
    # "San Francisco 94105 United States" is not Val-de-Marne
    if pc_ok and re.search(r"united states|\busa?\b|united kingdom|canada|australia|"
                           r"\bindia\b|germany|spain|italy", loc):
        pc_ok = False
    place_ok = bool(contains_any(loc, lc["places"]))
    unclear = bool(contains_any(loc, lc["unclear_places"]))
    remote_only = bool(re.search(r"\b(remote|teletravail|full remote|100% remote|"
                                 r"fully remote)\b", loc)) and not (pc_ok or place_ok)
    if pc_ok or place_ok:
        return True, "", tags
    if remote_only and lc.get("exclude_remote_only", True):
        return False, "remote-only", tags
    if unclear:
        return True, "", ["Check location"]
    if not loc.strip() or loc.strip() in ("france", "fr", "europe", "emea"):
        # location missing/generic: look in the description
        d = norm(description[:3000])
        if contains_any(d, ["paris", "la defense"]) or any(
                re.search(rf"(?<!\d){p}\d{{3}}(?!\d)", d) for p in lc["postal_prefixes"]):
            return True, "", ["Check location"]
    return False, f"location: {location or 'not stated'}", tags


# ---------------------------------------------------------------- contract
def check_contract(title: str, employment_type: str, cfg: dict):
    cc = cfg["contract"]
    t = norm(title)
    et = norm(employment_type)
    is_intern = bool(contains_any(t, cc["internship_terms"]) or
                     contains_any(et, cc["internship_terms"] + ["intern", "internship"]))
    # V.I.E is matched case-sensitively ("vie" is also French for "life")
    excl = contains_any(t, cc["exclude_terms"]) + \
        (["VIE"] if re.search(r"\bV\.?I\.?E\b", title) else [])
    if excl and not contains_any(t, cc["internship_terms"]):
        return False, f"contract: {excl[0]}", []
    if not is_intern:
        return False, "not an internship", []
    return True, "", []


# ---------------------------------------------------------------- dates
def check_dates(dur: DurationInfo, start: StartInfo, cfg: dict, top_role: bool = False):
    """top_role: a core role with a high role score may last up to
    `top_role_max_months` (4) instead of `max_months` (3); it is tagged."""
    dc = cfg["dates"]
    tags = []
    max_m = dc["max_months"]
    if dur.stated and dur.min_months > max_m + 0.25:   # 13 weeks = 3.0 months
        top_m = dc.get("top_role_max_months", max_m)
        if not (top_role and dur.min_months <= top_m + 0.25):
            return False, f"duration {dur.label()}", tags
        tags.append(f"⚠ {dur.label()} — longer than 3 months")
    if not dur.stated and dur.long_flags:
        return False, f"long internship ({dur.long_flags[0]})", tags
    if not (dur.stated and dur.min_months <= max_m) and dur.end_of_studies and \
            dc.get("hide_end_of_studies", True):
        return False, "stage de fin d'etudes", tags
    comp = start_compatible(start, _d(dc["earliest_start"]), _d(dc["latest_start"]))
    if comp is False:
        return False, f"start {start.label()}", tags
    if not dur.stated:
        tags.append("Duration not stated")
    return True, "", tags


# ---------------------------------------------------------------- pay
def check_pay(pay: PayInfo, cfg: dict):
    pc = cfg["pay"]
    if not pay.stated:
        return True, "", ["Pay not stated"]
    if pay.legal_minimum and not pc.get("legal_minimum_counts_as_low", True):
        return True, "", ["Pay: legal minimum"]
    top = pay.monthly_max or pay.monthly_min
    if top < pc["min_monthly_eur"]:
        return False, f"pay {pay.label()}", []
    return True, "", []


# ---------------------------------------------------------------- roles
# Role + company relevance (sector gate, excluded functions) lives in
# relevance.py; check_role is kept as a thin wrapper for tests / callers.
def check_role(title: str, description: str, company_type: str, cfg: dict,
               company: str = ""):
    from .relevance import evaluate
    res, reason = evaluate(title, description, company, company_type, cfg)
    return (True, "", []) if res else (False, reason, [])


# ---------------------------------------------------------------- workplace
def _negated(text: str, start: int, negs: list[str]) -> bool:
    before = text[max(0, start - 30):start]
    return any(re.search(rf"(^|\W){re.escape(n)}(\W|$)", before) for n in negs)


def check_workplace(location: str, description: str, cfg: dict):
    """Hide hybrid / remote offers: the internship must be fully on-site."""
    wc = cfg.get("workplace", {})
    if not wc.get("exclude_hybrid", True):
        return True, "", []
    loc, d = norm(location), norm(description)
    hit = contains_any(loc, wc.get("location_terms", []))
    if hit:
        return False, f"not fully on-site ({hit[0]})", []
    onsite = contains_any(d, wc.get("onsite_phrases", []))
    for kw in wc.get("hybrid_phrases", []):
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(norm(kw)) + r"(?![a-z0-9])", d):
            if not _negated(d, m.start(), wc.get("negations", [])):
                if onsite:      # e.g. "no hybrid: 100% on-site" handled above; mixed -> check
                    return True, "", ["Check: on-site vs hybrid"]
                return False, f"not fully on-site ({kw})", []
    return True, "", (["On-site"] if onsite else [])


# ---------------------------------------------------------------- eligibility
def check_eligibility(description: str, cfg: dict):
    """Hide offers reserved for final-year / Master's students."""
    ec = cfg.get("eligibility", {})
    if not ec.get("hide_final_year_or_masters_only", True):
        return True, "", []
    d = norm(description)
    year_open = contains_any(d, ec.get("year_open_phrases", []))
    level_open = contains_any(d, ec.get("bachelor_open_phrases", []))
    final = contains_any(d, ec.get("final_year_phrases", []))
    if final and not year_open:
        return False, f"final-year students only ({final[0]})", []
    masters = contains_any(d, ec.get("masters_phrases", []))
    if masters and not (year_open or level_open):
        return False, f"Master's students only ({masters[0]})", []
    return True, "", []
