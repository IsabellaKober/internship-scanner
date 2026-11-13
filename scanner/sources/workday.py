"""Workday public career-site JSON ("cxs") endpoints — the same endpoints the
company's own public Workday careers page calls in your browser.

Config: `workday_url: https://<tenant>.wd3.myworkdayjobs.com/<Site>`
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urlparse

from ..models import Offer
from .base import looks_french, looks_like_internship

NAME = "workday"
URL_RE = re.compile(r"https?://([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/"
                    r"(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")
DEFAULT_QUERIES = ["stage", "stagiaire", "intern", "internship"]
PAGE = 20
MAX_PAGES = 3


def parse_url(url: str):
    m = URL_RE.search(url)
    if not m:
        return None
    tenant, wd, site = m.groups()
    return {"host": f"{tenant}.{wd}.myworkdayjobs.com", "tenant": tenant, "site": site}


def _api(w):
    return f"https://{w['host']}/wday/cxs/{w['tenant']}/{w['site']}"


def _posted(s: str) -> str | None:
    s = (s or "").lower()
    today = date.today()
    if "today" in s or "aujourd" in s:
        return today.isoformat()
    if "yesterday" in s or "hier" in s:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*(days|jours)", s)
    if m:
        return (today - timedelta(days=int(m.group(1)))).isoformat()
    return None


def _search(session, w, text, offset):
    r = session.post(_api(w) + "/jobs", json={
        "appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": text})
    r.raise_for_status()
    return r.json()


def probe(session, url):
    w = parse_url(url)
    if not w:
        return None
    d = _search(session, w, "", 0)
    return {"jobs": d.get("total", 0), "name": w["tenant"], "france": True}


def fetch(session, company):
    w = parse_url(company["ats_id"])
    seen, out = set(), []
    for q in company.get("workday_queries") or DEFAULT_QUERIES:
        for page in range(MAX_PAGES):
            d = _search(session, w, q, page * PAGE)
            posts = d.get("jobPostings") or []
            for p in posts:
                path = p.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                title, loc = p.get("title", ""), p.get("locationsText", "")
                if not looks_like_internship(title):
                    continue
                if not (looks_french(loc) or re.search(r"\d+ (locations|sites)", loc.lower())):
                    continue
                det = session.get_json(_api(w) + path).get("jobPostingInfo", {})
                locs = [det.get("location", loc)] + list(det.get("additionalLocations") or [])
                out.append(Offer(
                    source=NAME, source_id=det.get("jobReqId") or path,
                    company=company["name"], title=det.get("title", title),
                    url=det.get("externalUrl") or f"https://{w['host']}/{w['site']}{path}",
                    location=", ".join(x for x in locs if x),
                    description_html=det.get("jobDescription", ""),
                    posted=(det.get("startDate") or "")[:10] or _posted(p.get("postedOn")),
                    employment_type=det.get("timeType", ""),
                ))
            if len(posts) < PAGE:
                break
    return out
