"""Shared helpers for source adapters.

Every ATS adapter module exposes:
    NAME: str
    probe(session, slug) -> dict | None
        Returns {"jobs": n, "name": <board name or None>, "france": bool}
        if a public board exists for `slug`, else None.
    fetch(session, company: dict) -> list[Offer]
        `company` is the config entry merged with the detected
        {"ats": ..., "ats_id": ...}.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ..text import norm

# Cheap pre-filters so adapters that need one request per job (Workday,
# SuccessFactors) only fetch details for plausible internships in Paris.
_INTERN_HINT = re.compile(
    r"(stage|stagiaire|intern|internship|praktikum|summer analyst|"
    r"summer associate|off-cycle|trainee)")
_FR_HINT = re.compile(r"(paris|france|ile-de-france|idf|la defense|puteaux|"
                      r"courbevoie|boulogne|issy|neuilly|levallois|nanterre|"
                      r"saint-denis|saint-ouen|montreuil|\b9[234]\d{3}\b|\b75\d{3}\b|"
                      r"\b(92|93|94|75)\b|hauts-de-seine|val-de-marne|seine-saint-denis)")


def looks_like_internship(title: str, employment_type: str = "") -> bool:
    return bool(_INTERN_HINT.search(norm(f"{title} {employment_type}")))


def looks_french(location: str) -> bool:
    return bool(_FR_HINT.search(norm(location)))


def iso_from_ms(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return None


def iso_date(s) -> str | None:
    if not s:
        return None
    s = str(s)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    return m.group(1) if m else None


def slug_candidates(name: str, extra=None) -> list[str]:
    base = norm(name)
    base = re.sub(r"\(.*?\)", "", base).strip()
    words = re.findall(r"[a-z0-9]+", base)
    cands = list(extra or [])
    if words:
        cands += ["".join(words), "-".join(words), words[0]]
        if len(words) > 1:
            cands.append("".join(words[:2]))
    seen, out = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out
