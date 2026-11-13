"""Teamtailor public career-site RSS feed: https://<sub>.teamtailor.com/jobs.rss
(also works on custom career domains: <domain>/jobs.rss)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..models import Offer
from .base import looks_french

NAME = "teamtailor"
TT_NS = "{https://teamtailor.com/locations}"


def _feed_url(slug_or_url: str) -> str:
    if slug_or_url.startswith("http"):
        return slug_or_url.rstrip("/") + "/jobs.rss"
    return f"https://{slug_or_url}.teamtailor.com/jobs.rss"


def _parse(xml_text):
    root = ET.fromstring(xml_text)
    ch = root.find("channel")
    items = []
    for it in ch.findall("item"):
        locs = []
        for loc in it.iter():
            if loc.tag.startswith(TT_NS) and loc.tag.endswith(("city", "name")):
                if loc.text:
                    locs.append(loc.text)
        remote = (it.findtext(f"{TT_NS}remoteStatus") or "")
        items.append({
            "title": it.findtext("title") or "",
            "description": it.findtext("description") or "",
            "link": it.findtext("link") or "",
            "guid": it.findtext("guid") or it.findtext("link") or "",
            "pubDate": it.findtext("pubDate"),
            "location": ", ".join(dict.fromkeys(locs)) +
                        (f" ({remote})" if remote and remote != "none" else ""),
        })
    return ch.findtext("title"), items


def probe(session, slug):
    r = session.get(_feed_url(slug), allow_redirects=False)
    if r.status_code != 200 or "<rss" not in r.text[:300]:
        return None
    name, items = _parse(r.text)
    return {"jobs": len(items), "name": name,
            "france": any(looks_french(i["location"]) for i in items)}


def fetch(session, company):
    r = session.get(_feed_url(company["ats_id"]))
    r.raise_for_status()
    _, items = _parse(r.text)
    out = []
    for i in items:
        posted = None
        if i["pubDate"]:
            try:
                posted = parsedate_to_datetime(i["pubDate"]).date().isoformat()
            except (TypeError, ValueError):
                pass
        out.append(Offer(
            source=NAME, source_id=i["guid"], company=company["name"],
            title=i["title"], url=i["link"], location=i["location"],
            description_html=i["description"], posted=posted,
        ))
    return out
