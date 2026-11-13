"""Workable public careers widget API (used by Workable's own embeddable
job widget): https://apply.workable.com/api/v1/widget/accounts/<sub>"""
from __future__ import annotations

from ..models import Offer
from .base import iso_date, looks_french

NAME = "workable"
API = "https://apply.workable.com/api/v1/widget/accounts/{id}?details=true"


def _loc(j):
    parts = [j.get("city"), j.get("state"), j.get("country")]
    for l in j.get("locations") or []:
        parts += [l.get("city"), l.get("region"), l.get("country")]
    s = ", ".join(dict.fromkeys(p for p in parts if p))
    if j.get("telecommuting"):
        s += " (remote)"
    return s


def probe(session, slug):
    r = session.get(API.format(id=slug).replace("?details=true", ""))
    if r.status_code != 200:
        return None
    d = r.json()
    jobs = d.get("jobs", [])
    return {"jobs": len(jobs), "name": d.get("name"),
            "france": any(looks_french(_loc(j)) for j in jobs)}


def fetch(session, company):
    d = session.get_json(API.format(id=company["ats_id"]))
    out = []
    for j in d.get("jobs", []):
        out.append(Offer(
            source=NAME, source_id=j.get("shortcode") or j.get("id", ""),
            company=company["name"], title=j.get("title", ""),
            url=j.get("url") or j.get("application_url") or j.get("shortlink", ""),
            location=_loc(j), description_html=j.get("description", ""),
            posted=iso_date(j.get("published_on") or j.get("created_at")),
            employment_type=j.get("employment_type", ""),
        ))
    return out
