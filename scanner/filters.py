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
def check_dates(dur: DurationInfo, start: StartInfo, cfg: dict):
    dc = cfg["dates"]
    tags = []
    max_m = dc["max_months"]
    if dur.stated and dur.min_months > max_m + 0.25:   # 13 weeks = 3.0 months
        return False, f"duration {dur.label()}", tags
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
def check_role(title: str, description: str, company_type: str, cfg: dict):
    t = norm(title)
    for group, kws in cfg["exclude_roles"].items():
        hit = contains_any(t, kws)
        if hit:
            return False, f"role excluded ({group}: {hit[0]})", []
    if company_type == "pharma":
        bad = contains_any(t, cfg.get("pharma_excluded_keywords", []))
        if bad:
            return False, f"pharma: {bad[0]} role", []
        if not contains_any(t, cfg["pharma_allowed_keywords"]):
            return False, "pharma: not a commercial/BD/finance role", []
    return True, "", []
