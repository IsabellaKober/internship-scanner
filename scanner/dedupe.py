"""Merge the same offer appearing on several sources:
same company (normalised) + similar title (ratio >= 0.85 after removing
noise like "Stage", "Intern", "H/F", dates and durations)."""
from __future__ import annotations

import difflib
import re

from .text import norm

_NOISE = re.compile(
    r"\b(stage|stagiaire|internship|intern|h/f|f/h|m/f/d|m/w/d|f/m|h-f|f-h|"
    r"\d{1,2}\s*(mois|months?)|20\d{2}|janvier|fevrier|mars|avril|mai|juin|"
    r"juillet|aout|septembre|october|january|february|march|april|may|june|"
    r"july|august|september|paris|france)\b")


def company_key(name: str) -> str:
    n = norm(name)
    n = re.sub(r"\(.*?\)", "", n)
    n = re.sub(r"\b(sas|sa|france|group|groupe|inc|ltd|gmbh)\b", "", n)
    return re.sub(r"[^a-z0-9]", "", n)


def title_key(title: str) -> str:
    t = _NOISE.sub(" ", norm(title))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def dedupe(offers: list[dict]) -> list[dict]:
    """offers are dicts with 'company', 'title', 'description', 'sources'."""
    kept: list[dict] = []
    by_company: dict[str, list[dict]] = {}
    for o in offers:
        ck = company_key(o["company"])
        tk = title_key(o["title"])
        dup = None
        for k in by_company.get(ck, []):
            if difflib.SequenceMatcher(None, tk, k["_tk"]).ratio() >= 0.85:
                dup = k
                break
        if dup:
            for s in o["sources"]:
                if s not in dup["sources"]:
                    dup["sources"].append(s)
            dup.setdefault("alt_urls", []).append(o["url"])
            # keep the richer description
            if len(o.get("description", "")) > len(dup.get("description", "")):
                for f in ("description", "url", "posted", "location"):
                    if o.get(f):
                        dup[f] = o[f]
            continue
        o["_tk"] = tk
        by_company.setdefault(ck, []).append(o)
        kept.append(o)
    for o in kept:
        o.pop("_tk", None)
    return kept
