"""SmartRecruiters Posting API (public, documented).

NOTE: api.smartrecruiters.com/robots.txt disallows all bots except
LinkedInBot. Because this scanner respects robots.txt, every request here is
refused by PoliteSession and the source is reported as "blocked by
robots.txt" unless you explicitly enable `sources.smartrecruiters.ignore_robots`
in config.yaml (your call — the API itself is documented as public)."""
from __future__ import annotations

from ..models import Offer
from .base import iso_date, looks_french, looks_like_internship

NAME = "smartrecruiters"
API = "https://api.smartrecruiters.com/v1/companies/{id}/postings"


def _loc(p):
    l = p.get("location") or {}
    s = ", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x)
    return s + (" (remote)" if l.get("remote") else "")


def probe(session, slug, check_robots=True):
    r = session.get(API.format(id=slug) + "?limit=100", check_robots=check_robots)
    if r.status_code != 200:
        return None
    d = r.json()
    jobs = d.get("content", [])
    if not jobs:
        return None
    return {"jobs": d.get("totalFound", len(jobs)), "name": None,
            "france": any(looks_french(_loc(p)) for p in jobs)}


def fetch(session, company, check_robots=True):
    out, offset = [], 0
    while offset < 1000:
        d = session.get_json(API.format(id=company["ats_id"]) +
                             f"?limit=100&offset={offset}", check_robots=check_robots)
        posts = d.get("content", [])
        for p in posts:
            title = p.get("name", "")
            etype = (p.get("typeOfEmployment") or {}).get("label", "")
            if not looks_like_internship(title, etype) or not looks_french(_loc(p)):
                continue
            det = session.get_json(API.format(id=company["ats_id"]) + f"/{p['id']}",
                                   check_robots=check_robots)
            sections = ((det.get("jobAd") or {}).get("sections") or {})
            html = "".join(f"<h3>{s.get('title', '')}</h3>{s.get('text', '')}"
                           for s in sections.values() if isinstance(s, dict))
            out.append(Offer(
                source=NAME, source_id=p["id"], company=company["name"], title=title,
                url=det.get("postingUrl") or det.get("applyUrl") or "",
                location=_loc(p), description_html=html,
                posted=iso_date(p.get("releasedDate")), employment_type=etype,
            ))
        if len(posts) < 100:
            break
        offset += 100
    return out
