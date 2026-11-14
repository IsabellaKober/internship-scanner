"""Daily pipeline: fetch -> parse -> filter -> score -> dedupe -> enrich ->
encrypt dashboard data -> notify.

    python -m scanner.run                 # normal run (needs DASHBOARD_PASSWORD)
    python -m scanner.run --no-notify     # don't send push notifications
    python -m scanner.run --report        # print a summary + top 10 at the end
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, quote_plus

from . import detect_ats, filters, scoring
from .config import load_config
from .crypto import decrypt_json, encrypt_json
from .dedupe import company_key, dedupe
from .enrich import make_enricher, rule_based
from .http import PoliteSession, RobotsDisallowed
from .notify import notify
from .parsing import parse_deadline, parse_duration, parse_pay, parse_start
from .sources import (adzuna, amazonjobs, ashby, francetravail, greenhouse, lever,
                      smartrecruiters, successfactors, teamtailor, workable, workday)
from .text import html_to_text, norm

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data" / "offers.json"
SEEN = ROOT / "data" / "seen.json"
LAST_RUN = ROOT / "data" / "last_run.json"

ADAPTERS = {m.NAME: m for m in (greenhouse, lever, ashby, workable, teamtailor,
                                smartrecruiters, workday, successfactors, amazonjobs)}
CAT_LABELS = {"fintech": "Fintech", "sales": "Sales", "strategy": "Strategy",
              "ecommerce": "E-commerce", "bizdev": "BizDev", "finance": "Finance",
              "pharma": "Pharma"}


# ---------------------------------------------------------------- helpers
def _load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")


def load_previous(password: str) -> dict:
    if not OUT.exists():
        return {}
    try:
        return decrypt_json(json.loads(OUT.read_text(encoding="utf-8")), password)
    except Exception:  # noqa: BLE001  (password changed / first run)
        print("Could not decrypt previous data (new password?) - starting fresh")
        return {}


def search_links(cfg) -> dict:
    roles = cfg["search_links"]["roles"]
    li, ind, wttj = [], [], []
    for r in roles:
        q = f"{r} intern"
        li.append({"label": r.title(), "url":
                   "https://www.linkedin.com/jobs/search/?keywords=" + quote(q) +
                   "&location=" + quote("Paris, Île-de-France, France") +
                   "&f_JT=I&f_TPR=r86400&sortBy=DD"})
        ind.append({"label": r.title(), "url":
                    "https://fr.indeed.com/jobs?q=" + quote_plus(f"stage {r}") +
                    "&l=" + quote_plus("Paris (75)") + "&radius=10&fromage=1&sort=date"})
        wttj.append({"label": r.title(), "url":
                     "https://www.welcometothejungle.com/fr/jobs?query=" + quote(r) +
                     "&refinementList%5Bcontract_type%5D%5B%5D=internship"
                     "&aroundQuery=Paris%2C%20France&sortBy=mostRecent"})
    return {"LinkedIn (last 24h)": li, "Indeed (last 24h)": ind,
            "Welcome to the Jungle": wttj}


def company_links(cfg, cache) -> list[dict]:
    out = []
    for c in cfg["companies"]:
        ats = (cache.get(c["name"]) or {}).get("ats") or c.get("ats")
        if ats in ADAPTERS:
            continue
        slug = "-".join(norm(c["name"]).replace("(", " ").replace(")", " ").split())
        url = c.get("careers_url") or \
            f"https://www.welcometothejungle.com/fr/companies/{slug.split('-ex-')[0]}/jobs"
        out.append({"name": c["name"], "type": c.get("type", "other"), "url": url})
    return out


# ---------------------------------------------------------------- fetch
def fetch_all(cfg, session, log=print):
    cache = detect_ats.resolve(session, cfg["companies"], log=log)
    raw, status = [], {}
    by_name = {c["name"]: c for c in cfg["companies"]}

    def st(src):
        return status.setdefault(src, {"source": src, "companies_ok": 0,
                                       "failed": [], "offers": 0, "state": "ok"})

    for name, c in by_name.items():
        det = cache.get(name) or {}
        ats = det.get("ats")
        if ats not in ADAPTERS:
            continue
        sc = cfg["sources"].get(ats, {})
        if sc.get("enabled") is False:
            continue
        comp = {**c, "ats_id": det.get("ats_id"), "ats_host": det.get("ats_host")}
        s = st(ats)
        t0 = time.time()
        try:
            if ats == "smartrecruiters":
                offers = smartrecruiters.fetch(session, comp,
                                               check_robots=not sc.get("ignore_robots"))
            else:
                offers = ADAPTERS[ats].fetch(session, comp)
            for o in offers:
                o.company_type = c.get("type", "other")
            raw.extend(offers)
            s["companies_ok"] += 1
            s["offers"] += len(offers)
            log(f"  {ats:15} {name:30} {len(offers):4} jobs ({time.time() - t0:.1f}s)")
        except RobotsDisallowed:
            s["failed"].append({"company": name, "error": "blocked by robots.txt"})
            log(f"  {ats:15} {name:30} BLOCKED by robots.txt")
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {str(e)[:150]}"
            s["failed"].append({"company": name, "error": msg})
            log(f"  {ats:15} {name:30} FAILED {msg}")

    # Aggregators (optional, need free API keys): cover companies NOT in
    # config.yaml. Offers from known companies inherit that company's type.
    types = {company_key(c["name"]): c.get("type", "other") for c in cfg["companies"]}
    for mod, label in ((francetravail, "France Travail API"), (adzuna, "Adzuna API")):
        sc = cfg["sources"].get(mod.NAME, {})
        s = st(mod.NAME)
        if not sc.get("enabled", True):
            s["state"] = "disabled"
            continue
        if not mod.configured():
            s["state"] = "not configured"
            continue
        try:
            offers = mod.fetch(session, sc)
            for o in offers:
                o.company_type = types.get(company_key(o.company), "other")
            raw.extend(offers)
            s["companies_ok"] = 1
            s["offers"] = len(offers)
            log(f"  {mod.NAME:15} {len(offers)} offers")
        except Exception as e:  # noqa: BLE001
            s["failed"].append({"company": label,
                                "error": f"{type(e).__name__}: {str(e)[:150]}"})
            log(f"  {mod.NAME:15} FAILED {e}")

    for s in status.values():
        if s["failed"] and s["state"] == "ok":
            s["state"] = "failed" if not s["companies_ok"] else "partial"
    return raw, list(status.values()), cache


# ---------------------------------------------------------------- process
def process(o, cfg, today: date):
    text = html_to_text(o.description_html) or o.description
    o.description = text
    full = f"{o.title}\n{text}"
    ref = date.fromisoformat(o.posted) if o.posted else today
    # a duration in the title ("Stage 6 mois - ...") overrides the body text
    dur = parse_duration(o.title)
    if not dur.stated:
        dur = parse_duration(full)
    start = parse_start(text, o.title, ref)
    pay = parse_pay(text, o.pay_text)
    deadline = parse_deadline(text, today)

    tags = []
    for check in (
        lambda: filters.check_contract(o.title, o.employment_type, cfg),
        lambda: filters.check_location(o.location, text, cfg),
        lambda: filters.check_role(o.title, text, o.company_type, cfg),
        lambda: filters.check_dates(dur, start, cfg),
        lambda: filters.check_pay(pay, cfg),
    ):
        ok, reason, t = check()
        if not ok:
            return None, reason
        tags += t

    clarity, clarity_why = scoring.clarity_score(text, cfg)
    role, cats = scoring.role_score(o.title, text, o.company_type, clarity, cfg, o.company)
    dates_s = scoring.date_score(dur, start, cfg)
    lang, lang_s = scoring.language_info(o.title, text, cfg)
    comp_s = cfg["company_type_scores"].get(o.company_type, 50)
    parts = {"role": role, "clarity": clarity, "dates": dates_s,
             "language": lang_s, "company": comp_s}
    score = scoring.total_score(parts, cfg)

    d = o.to_dict()
    d.update({
        "sources": [o.source],
        "score": score, "breakdown": parts, "clarity_notes": clarity_why,
        "categories": cats,
        "category_labels": [CAT_LABELS[c] for c in cats if c in CAT_LABELS],
        "language": lang,
        "duration": dur.label(), "duration_months": [dur.min_months, dur.max_months],
        "start": start.label(),
        "start_dates": [x.isoformat() for x in start.candidates],
        "pay": pay.label(), "deadline": deadline.isoformat() if deadline else None,
        "tags": list(dict.fromkeys(tags)),
    })
    return d, None


# ---------------------------------------------------------------- main
def main(argv=None):
    argv = argv or sys.argv[1:]
    cfg = load_config()
    password = os.environ.get("DASHBOARD_PASSWORD")
    if not password:
        raise SystemExit("DASHBOARD_PASSWORD is not set - refusing to write "
                         "unencrypted dashboard data. (See README.)")
    today = date.today()
    now = datetime.now(timezone.utc)
    session = PoliteSession(min_delay=1.0)

    print("== Fetching")
    raw, src_status, cache = fetch_all(cfg, session)
    print(f"   {len(raw)} raw offers, {session.request_count} HTTP requests")

    print("== Filtering & scoring")
    kept, reasons = [], Counter()
    found_per_source, kept_per_source = Counter(), Counter()
    rejected_ids = set()
    for o in raw:
        found_per_source[o.source] += 1
        d, reason = process(o, cfg, today)
        if d is None:
            reasons[reason.split(":")[0].split(" (")[0]] += 1
            rejected_ids.add(o.id)      # still online but no longer matches the rules
            continue
        kept_per_source[o.source] += 1
        kept.append(d)
    kept = dedupe(kept)
    print(f"   kept {len(kept)} after filters + dedupe")

    prev = load_previous(password)
    prev_offers = {o["id"]: o for o in prev.get("offers", [])}
    seen = _load_json(SEEN, {})

    # enrichment (cached per offer id)
    enricher = make_enricher(cfg, cfg["profile"])
    budget = cfg["enrichment"]["max_per_run"]
    new_offers = []
    for o in kept:
        if o["id"] not in seen:
            seen[o["id"]] = today.isoformat()
            new_offers.append(o)
        o["first_seen"] = seen[o["id"]]
        cached = prev_offers.get(o["id"], {}).get("enrichment")
        enr = None
        if cached and (cached.get("method") == "ai" or not enricher):
            enr = cached
        elif enricher and budget > 0:
            enr = enricher.enrich(o, o["description"])
            budget -= 1
        if not enr:
            enr = cached or rule_based(o, o["description"], cfg["profile"])
        o["enrichment"] = enr
        o["why_fit"] = enr["why_fit"]

    # keep offers that disappeared for a while (you may have applied)
    live_ids = {o["id"] for o in kept}
    keep_days = cfg["dashboard"]["keep_unlisted_days"]
    for pid, po in prev_offers.items():
        if pid in live_ids or pid in rejected_ids:
            continue
        last = date.fromisoformat(po.get("last_seen", today.isoformat()))
        if today - last <= timedelta(days=keep_days):
            po["unlisted"] = True
            kept.append(po)
    for o in kept:
        if o["id"] in live_ids:
            o["last_seen"] = today.isoformat()
            o["unlisted"] = False
        if len(o.get("description") or "") > 8000:
            o["description"] = o["description"][:8000] + " …"

    # ranked by score, newest first within ties
    kept.sort(key=lambda o: o.get("posted") or "", reverse=True)
    kept.sort(key=lambda o: -o["score"])

    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "settings": {"notify_min_score": cfg["notifications"]["min_score"],
                     "new_badge_days": cfg["dashboard"]["new_badge_days"],
                     "state_repo": cfg.get("state_repo", "")},
        "sources": src_status,
        "offers": kept,
        "search_links": search_links(cfg),
        "company_links": company_links(cfg, cache),
        "stats": {"raw": len(raw), "kept": len(live_ids),
                  "found_per_source": found_per_source,
                  "kept_per_source": kept_per_source,
                  "rejected": dict(reasons.most_common())},
    }
    _write_json(OUT, encrypt_json(payload, password))
    _write_json(SEEN, seen)
    _write_json(LAST_RUN, {
        "generated_at": payload["generated_at"], "raw": len(raw),
        "kept": len(live_ids), "new": len(new_offers),
        "found_per_source": found_per_source, "kept_per_source": kept_per_source,
        "rejected": dict(reasons.most_common()),
        "sources": [{k: v for k, v in s.items()} for s in src_status],
        "enrichment": ({"calls": enricher.calls, "cost_usd": round(enricher.cost_usd(), 4)}
                       if enricher else "rules"),
    })
    print(f"== Wrote {OUT.relative_to(ROOT)} (encrypted): {len(live_ids)} live offers, "
          f"{len(new_offers)} new")
    if enricher:
        print(f"   Claude: {enricher.calls} calls, ~${enricher.cost_usd():.4f}")

    if "--no-notify" not in argv:
        # (first run included: max_per_run caps the initial backlog)
        n = notify(new_offers, cfg, os.environ.get("DASHBOARD_URL"))
        print(f"== Sent {n} notifications")

    if "--report" in argv:
        report(payload, found_per_source, kept_per_source, reasons, src_status)
    failed = [s for s in src_status if s["state"] in ("failed", "partial")]
    return 0 if not failed or len(failed) < len(src_status) else 1


def report(payload, found, kept, reasons, src_status):
    print("\n================ REPORT ================")
    print(f"{'source':16}{'found':>8}{'kept':>8}   status")
    for s in src_status:
        src = s["source"]
        fails = f" ({len(s['failed'])} company errors)" if s["failed"] else ""
        print(f"{src:16}{found.get(src, 0):>8}{kept.get(src, 0):>8}   {s['state']}{fails}")
    print(f"\nRejected by filter: {dict(reasons.most_common())}")
    live = [o for o in payload["offers"] if not o.get("unlisted")]
    print(f"\nTop 10 of {len(live)}:")
    for o in live[:10]:
        b = o["breakdown"]
        print(f" {o['score']:3}  {o['company'][:22]:22} {o['title'][:60]:60} "
              f"[role {b['role']} clar {b['clarity']} date {b['dates']} lang {b['language']}]"
              f"  {o['duration']} | {o['start']} | {o['pay']}")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(2)
