"""Ashby public job posting API (documented):
https://developers.ashbyhq.com/docs/public-job-posting-api"""
from __future__ import annotations

from ..models import Offer
from .base import iso_date, looks_french

NAME = "ashby"
API = "https://api.ashbyhq.com/posting-api/job-board/{id}?includeCompensation=true"


def _locs(j):
    locs = [j.get("location") or ""]
    locs += [s.get("location", "") for s in j.get("secondaryLocations") or []]
    addr = ((j.get("address") or {}).get("postalAddress") or {})
    locs.append(" ".join(str(addr.get(k, "")) for k in
                         ("addressLocality", "postalCode", "addressCountry")))
    return ", ".join(x.strip() for x in locs if x and x.strip())


def probe(session, slug):
    r = session.get(API.format(id=slug))
    if r.status_code != 200:
        return None
    jobs = r.json().get("jobs", [])
    return {"jobs": len(jobs), "name": None,
            "france": any(looks_french(_locs(j)) for j in jobs)}


def fetch(session, company):
    data = session.get_json(API.format(id=company["ats_id"]))
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
        wp = j.get("workplaceType") or ""
        out.append(Offer(
            source=NAME, source_id=j["id"], company=company["name"],
            title=j.get("title", ""), url=j.get("jobUrl", ""),
            location=_locs(j) + (f" ({wp})" if wp else ""),
            description_html=j.get("descriptionHtml", ""),
            posted=iso_date(j.get("publishedAt")),
            employment_type=j.get("employmentType", ""), pay_text=comp,
        ))
    return out
