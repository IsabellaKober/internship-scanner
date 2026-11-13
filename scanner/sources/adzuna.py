"""Adzuna job-search API (official, free developer key: developer.adzuna.com).
Aggregates listings from thousands of employers and job boards across France,
so it finds companies that are not in config.yaml.

Secrets: ADZUNA_APP_ID, ADZUNA_APP_KEY. Without them the source is skipped
("not configured"). Adzuna's terms ask for attribution: the dashboard shows
"Jobs by Adzuna" next to these offers.

Note: Adzuna returns a description *snippet* (a few hundred characters), so
duration/pay are often "not stated" for these offers — open the link to check.
"""
from __future__ import annotations

import os

from ..models import Offer
from .base import iso_date

NAME = "adzuna"
API = "https://api.adzuna.com/v1/api/jobs/fr/search/{page}"


def configured() -> bool:
    return bool(os.environ.get("ADZUNA_APP_ID") and os.environ.get("ADZUNA_APP_KEY"))


def fetch(session, cfg):
    out, seen = [], set()
    for what in cfg.get("queries", ["stage", "stagiaire", "internship"]):
        for page in range(1, cfg.get("max_pages", 4) + 1):
            r = session.get(API.format(page=page), check_robots=False, params={
                "app_id": os.environ["ADZUNA_APP_ID"],
                "app_key": os.environ["ADZUNA_APP_KEY"],
                "results_per_page": 50, "what": what, "where": "Paris",
                "distance": cfg.get("distance_km", 15),
                "max_days_old": cfg.get("max_days_old", 30),
                "sort_by": "date", "content-type": "application/json",
            })
            r.raise_for_status()
            res = r.json().get("results", [])
            for j in res:
                jid = str(j.get("id"))
                if jid in seen:
                    continue
                seen.add(jid)
                pay = ""
                if j.get("salary_min") and str(j.get("salary_is_predicted")) != "1":
                    pay = f"{j['salary_min']} - {j.get('salary_max') or j['salary_min']} EUR per year" \
                        if float(j["salary_min"]) > 6000 else f"{j['salary_min']} EUR per month"
                loc = j.get("location") or {}
                out.append(Offer(
                    source=NAME, source_id=jid,
                    company=(j.get("company") or {}).get("display_name") or "Unknown company",
                    title=j.get("title", ""), url=j.get("redirect_url", ""),
                    location=", ".join([loc.get("display_name", "")] + (loc.get("area") or [])[-2:]),
                    description_html=j.get("description", ""),
                    posted=iso_date(j.get("created")),
                    employment_type=" ".join(filter(None, [j.get("contract_type"),
                                                           j.get("contract_time")])),
                    pay_text=pay,
                ))
            if len(res) < 50:
                break
    return out
