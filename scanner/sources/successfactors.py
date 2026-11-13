"""SAP SuccessFactors career sites: public RSS job feed, when the company's
site exposes one and its robots.txt allows it.

Config: `successfactors_rss: https://<careers-site>/services/rss/job/?locale=fr_FR&keywords=stage`
(several URLs allowed as a list)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from ..models import Offer

NAME = "successfactors"


def probe(session, url):
    r = session.get(url)
    if r.status_code != 200 or "<rss" not in r.text[:500]:
        return None
    items = ET.fromstring(r.text).find("channel").findall("item")
    return {"jobs": len(items), "name": None, "france": True}


def fetch(session, company):
    urls = company["ats_id"]
    urls = urls if isinstance(urls, list) else [urls]
    out = []
    for url in urls:
        r = session.get(url)
        r.raise_for_status()
        ch = ET.fromstring(r.text).find("channel")
        for it in ch.findall("item"):
            title = it.findtext("title") or ""
            posted = None
            try:
                posted = parsedate_to_datetime(it.findtext("pubDate")).date().isoformat()
            except (TypeError, ValueError):
                pass
            loc = ""
            if "(" in title and title.endswith(")"):
                loc = title[title.rfind("(") + 1:-1]
            out.append(Offer(
                source=NAME, source_id=it.findtext("guid") or it.findtext("link") or title,
                company=company["name"], title=title, url=it.findtext("link") or "",
                location=loc, description_html=it.findtext("description") or "",
                posted=posted,
            ))
    return out
