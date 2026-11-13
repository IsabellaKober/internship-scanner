"""Auto-detect which ATS (job platform) each company uses.

Order:
 1. explicit `ats:` + `id:` in config.yaml  -> used as-is
 2. cached detection in data/ats_cache.json (refreshed every 30 days)
 3. the company's `careers_url` page is fetched (robots.txt respected) and
    scanned for ATS links/embeds
 4. slug guessing on the public APIs (greenhouse, ashby, lever, workable,
    teamtailor), preferring boards that have French jobs and whose board
    name matches the company name.

CLI:  python -m scanner.detect_ats [--force] [company names...]
"""
from __future__ import annotations

import difflib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

from .http import PoliteSession, RobotsDisallowed
from .sources import ashby, greenhouse, lever, teamtailor, workable, workday
from .sources.base import slug_candidates
from .text import norm

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ats_cache.json"
REFRESH_DAYS = 30

SIGNATURES = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board(?:/js)?\?for=)?([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)")),
    ("teamtailor", re.compile(r"https?://([a-z0-9-]+)\.teamtailor\.com")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("workday", workday.URL_RE),
    ("wttj", re.compile(r"welcometothejungle\.com/(?:fr|en)/companies/([a-z0-9-]+)")),
    ("successfactors", re.compile(r"(successfactors\.(?:com|eu)|sapsf\.(?:com|eu)|jobs\.sap\.com)")),
]
PROBERS = {"greenhouse": greenhouse, "ashby": ashby, "lever": lever,
           "workable": workable, "teamtailor": teamtailor}
IGNORE_SLUGS = {"embed", "js", "jobs", "api", "v1", "careers", "www", "static",
                "assets", "widget", "job_board"}


def load_cache() -> dict:
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=2, ensure_ascii=False, sort_keys=True),
                     encoding="utf-8")


def _name_ok(board_name, company) -> bool:
    if not board_name:
        return True
    a, b = norm(board_name), norm(company)
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() > 0.6


def _from_page(session, url) -> dict | None:
    try:
        r = session.get(url)
    except RobotsDisallowed:
        return {"ats": "unknown", "note": f"careers page disallowed by robots.txt: {url}"}
    except Exception as e:  # noqa: BLE001
        return {"ats": "unknown", "note": f"careers page error: {e}"}
    html = r.text
    for ats, rx in SIGNATURES:
        m = rx.search(html) or rx.search(r.url)
        if not m:
            continue
        if ats == "workday":
            return {"ats": "workday", "ats_id": m.group(0), "confidence": "high"}
        if ats == "successfactors":
            return {"ats": "successfactors", "confidence": "low",
                    "note": "SuccessFactors site found; add `successfactors_rss` manually"}
        if ats == "wttj":
            return {"ats": "wttj", "ats_id": m.group(1), "confidence": "high",
                    "note": "jobs hosted on Welcome to the Jungle (not scraped: ToS)"}
        slug = m.group(1)
        if slug.lower() in IGNORE_SLUGS:
            continue
        return {"ats": ats, "ats_id": slug, "confidence": "high"}
    return None


def detect(session, company: dict) -> dict:
    name = company["name"]
    if company.get("careers_url"):
        res = _from_page(session, company["careers_url"])
        if res and res.get("ats") not in (None, "unknown"):
            if res["ats"] == "lever":
                p = lever.probe(session, res["ats_id"])
                if p:
                    res["ats_host"] = p["host"]
            return res
    best = None
    for slug in slug_candidates(name, company.get("slugs")):
        for ats, mod in PROBERS.items():
            try:
                p = mod.probe(session, slug)
            except Exception:  # noqa: BLE001
                p = None
            if not p or not _name_ok(p.get("name"), name):
                continue
            if not p["jobs"] or not p["france"]:
                # empty / non-French boards from slug guessing are too often a
                # dormant or unrelated account -> don't trust them
                continue
            score = (2 if p["france"] else 0) + (1 if p.get("name") else 0) + \
                    min(p["jobs"], 50) / 100
            cand = {"ats": ats, "ats_id": slug, "jobs": p["jobs"],
                    "france_jobs": p["france"],
                    "confidence": "high"}
            if p.get("host"):
                cand["ats_host"] = p["host"]
            if not best or score > best[0]:
                best = (score, cand)
        if best and best[0] >= 2:
            break
    if best:
        return best[1]
    return {"ats": "unknown", "confidence": "none",
            "note": "no public ATS board found; set `careers_url` or `ats`/`id` in config.yaml"}


def resolve(session, companies: list[dict], force=False, only=None, log=print) -> dict:
    cache = load_cache()
    today = date.today()
    for c in companies:
        name = c["name"]
        if only and name not in only:
            continue
        if c.get("ats"):
            cache[name] = {"ats": c["ats"], "ats_id": c.get("id"),
                           "ats_host": c.get("ats_host"), "confidence": "config",
                           "detected": today.isoformat()}
            continue
        old = cache.get(name)
        if old and not force:
            d = date.fromisoformat(old.get("detected", "2000-01-01"))
            fresh = today - d < timedelta(days=REFRESH_DAYS)
            if fresh:
                continue
        res = detect(session, c)
        res["detected"] = today.isoformat()
        cache[name] = res
        log(f"  {name:32} -> {res.get('ats')} {res.get('ats_id', '')} "
            f"[{res.get('confidence')}] {res.get('note', '')}")
    save_cache(cache)
    return cache


if __name__ == "__main__":
    from .config import load_config
    args = sys.argv[1:]
    force = "--force" in args
    names = [a for a in args if a != "--force"] or None
    cfg = load_config()
    resolve(PoliteSession(min_delay=0.5), cfg["companies"], force=force, only=names)
