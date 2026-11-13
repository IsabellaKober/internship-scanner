"""Greenhouse Job Board API (public, documented):
https://developers.greenhouse.io/job-board.html"""
from __future__ import annotations

from ..models import Offer
from .base import iso_date, looks_french

NAME = "greenhouse"
API = "https://boards-api.greenhouse.io/v1/boards/{id}"


def probe(session, slug):
    r = session.get(API.format(id=slug))
    if r.status_code != 200:
        return None
    name = r.json().get("name")
    jobs = session.get_json(API.format(id=slug) + "/jobs").get("jobs", [])
    return {"jobs": len(jobs), "name": name,
            "france": any(looks_french((j.get("location") or {}).get("name", ""))
                          for j in jobs)}


def fetch(session, company):
    data = session.get_json(API.format(id=company["ats_id"]) + "/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        offices = ", ".join(o.get("name", "") for o in j.get("offices") or [])
        out.append(Offer(
            source=NAME, source_id=str(j["id"]), company=company["name"],
            title=j.get("title", ""), url=j.get("absolute_url", ""),
            location=", ".join(x for x in (loc, offices) if x),
            description_html=j.get("content", ""),
            posted=iso_date(j.get("first_published") or j.get("updated_at")),
            employment_type=" ".join(
                str(m.get("value")) for m in j.get("metadata") or []
                if m.get("value") and "type" in str(m.get("name", "")).lower()),
        ))
    return out
