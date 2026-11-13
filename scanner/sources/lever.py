"""Lever Postings API (public, documented):
https://github.com/lever/postings-api  (global and EU instances)"""
from __future__ import annotations

from ..models import Offer
from .base import iso_from_ms, looks_french

NAME = "lever"
HOSTS = ["https://api.lever.co", "https://api.eu.lever.co"]


def _url(host, slug):
    return f"{host}/v0/postings/{slug}?mode=json"


def probe(session, slug):
    for host in HOSTS:
        r = session.get(_url(host, slug))
        if r.status_code == 200 and isinstance(r.json(), list):
            jobs = r.json()
            # Lever answers [] for unknown boards too; treat an empty list as
            # "not found" (we can't tell it apart from a real empty board).
            if not jobs:
                continue
            return {"jobs": len(jobs), "name": None, "host": host,
                    "france": any(looks_french(
                        " ".join((j.get("categories") or {}).get("allLocations") or
                                 [(j.get("categories") or {}).get("location", "")]))
                        for j in jobs)}
    return None


def fetch(session, company):
    host = company.get("ats_host") or HOSTS[0]
    jobs = session.get_json(_url(host, company["ats_id"]))
    out = []
    for j in jobs:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        html = (j.get("description") or "") + "".join(
            f"<h3>{l.get('text', '')}</h3><ul>{l.get('content', '')}</ul>"
            for l in j.get("lists") or []) + (j.get("additional") or "")
        pay = ""
        sr = j.get("salaryRange")
        if sr and sr.get("min"):
            pay = f"{sr.get('min')} - {sr.get('max')} {sr.get('currency', '')} " \
                  f"per {str(sr.get('interval', '')).replace('per-', '')}"
        out.append(Offer(
            source=NAME, source_id=j["id"], company=company["name"],
            title=j.get("text", ""), url=j.get("hostedUrl", ""),
            location=", ".join(x for x in locs if x) +
                     (f" ({j['workplaceType']})" if j.get("workplaceType") else ""),
            description_html=html, posted=iso_from_ms(j.get("createdAt")),
            employment_type=cat.get("commitment", ""), pay_text=pay,
        ))
    return out
