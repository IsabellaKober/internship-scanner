"""amazon.jobs public search JSON (the endpoint the amazon.jobs website uses;
allowed by its robots.txt). Config: `ats: amazonjobs, id: FRA`."""
from __future__ import annotations

from datetime import datetime

from ..models import Offer

NAME = "amazonjobs"
API = "https://www.amazon.jobs/en/search.json"


def probe(session, country):
    return {"jobs": 1, "name": "Amazon", "france": True}


def fetch(session, company):
    out, seen = [], set()
    for q in company.get("queries") or ["intern", "stage", "internship"]:
        d = session.get_json(API, params={
            "base_query": q, "loc_query": "Paris, France",
            "country": company.get("ats_id") or "FRA", "result_limit": 100,
            "sort": "recent"})
        for j in d.get("jobs", []):
            jid = str(j.get("id_icims") or j.get("id"))
            if jid in seen:
                continue
            seen.add(jid)
            posted = None
            try:
                posted = datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").date().isoformat()
            except ValueError:
                pass
            html = (f"{j.get('description', '')}<h3>Basic qualifications</h3>"
                    f"{j.get('basic_qualifications', '')}<h3>Preferred qualifications</h3>"
                    f"{j.get('preferred_qualifications', '')}")
            out.append(Offer(
                source=NAME, source_id=jid, company=company["name"],
                title=j.get("title", ""),
                url="https://www.amazon.jobs" + j.get("job_path", ""),
                location=j.get("normalized_location") or j.get("location", ""),
                description_html=html, posted=posted,
                employment_type=j.get("job_schedule_type", ""),
            ))
    return out
