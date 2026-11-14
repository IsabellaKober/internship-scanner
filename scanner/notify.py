"""Push notifications through ntfy.sh (topic in the NTFY_TOPIC secret).
One notification per high-scoring NEW offer."""
from __future__ import annotations

import os

import requests


def notify(offers: list[dict], cfg: dict, dashboard_url: str | None = None) -> int:
    topic = (os.environ.get("NTFY_TOPIC") or "").strip()
    if not topic:
        print("NTFY_TOPIC not set - skipping notifications")
        return 0
    nc = cfg["notifications"]
    picks = [o for o in offers if o["score"] >= nc["min_score"]]
    picks.sort(key=lambda o: -o["score"])
    sent = 0
    for o in picks[:nc["max_per_run"]]:
        title = f"{o['score']}/100 Â· {o['company']}"
        body = f"{o['title']}\n{o['location']}"
        if o.get("why_fit"):
            body += f"\n{o['why_fit']}"
        headers = {
            "Title": title.encode("utf-8"),
            "Click": o["url"],
            "Tags": "briefcase",
            "Priority": "high" if o["score"] >= 85 else "default",
        }
        if dashboard_url:
            headers["Actions"] = f"view, Dashboard, {dashboard_url}"
        try:
            r = requests.post(f"https://ntfy.sh/{topic}", data=body.encode("utf-8"),
                              headers=headers, timeout=15)
            r.raise_for_status()
            sent += 1
        except requests.RequestException as e:
            print(f"ntfy error: {e}")
    if len(picks) > nc["max_per_run"]:
        try:
            requests.post(f"https://ntfy.sh/{topic}", timeout=15,
                          data=f"+{len(picks) - nc['max_per_run']} more strong matches "
                               f"on the dashboard".encode("utf-8"),
                          headers={"Title": "More matches", "Tags": "briefcase",
                                   **({"Click": dashboard_url} if dashboard_url else {})})
        except requests.RequestException:
            pass
    return sent
