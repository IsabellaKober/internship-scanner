"""Polite HTTP client shared by every source.

- A clear, non-personal User-Agent.
- robots.txt is checked (and cached) for every host before fetching.
  Per RFC 9309 a missing robots.txt (4xx) means "allowed". A 5xx / network
  failure means the site is down (e.g. Workday's weekend maintenance): we
  don't crawl it, report it as "temporarily unavailable" and retry later -
  it is NOT a robots block.
- Per-host rate limiting (default 1 request / second, or the robots.txt
  Crawl-delay if larger).
- Timeouts and a small retry on 429/5xx.
"""
from __future__ import annotations

import time
import urllib.robotparser
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "internship-scanner/1.0 (personal, non-commercial job search; "
    "low-frequency, once per day)"
)
ROBOTS_AGENT = "internship-scanner"
# hosts that rate-limit aggressively get a longer gap between requests
HOST_DELAYS = {"apply.workable.com": 4.0}


class RobotsDisallowed(Exception):
    pass


class SiteUnavailable(Exception):
    """robots.txt could not be read (site down / maintenance) - retry later."""


class PoliteSession:
    def __init__(self, min_delay: float = 1.0, timeout: float = 20.0,
                 respect_robots: bool = True):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT,
                               "Accept-Language": "en,fr;q=0.8"})
        self.min_delay = min_delay
        self.timeout = timeout
        self.respect_robots = respect_robots
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self.request_count = 0

    # ---- robots -------------------------------------------------------
    def _robots_for(self, url: str):
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base in self._robots:
            return self._robots[base]
        rp = urllib.robotparser.RobotFileParser()
        for attempt in range(3):
            try:
                r = self.s.get(base + "/robots.txt", timeout=15,
                               headers={"User-Agent": USER_AGENT})
            except requests.RequestException:
                r = None
            if r is not None and r.status_code < 500:
                break
            if attempt < 2:
                time.sleep(10 * (attempt + 1))
        if r is None or r.status_code >= 500:
            return None                      # down: not cached, retried later
        if r.status_code >= 400:
            rp.allow_all = True
        else:
            rp.parse(r.text.splitlines())
        self._robots[base] = rp
        return rp

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp = self._robots_for(url)
        if rp is None:
            raise SiteUnavailable(urlparse(url).netloc)
        return rp.can_fetch(ROBOTS_AGENT, url)

    def _throttle(self, url: str):
        host = urlparse(url).netloc
        delay = max(self.min_delay, HOST_DELAYS.get(host, 0))
        rp = self._robots.get(f"{urlparse(url).scheme}://{host}")
        if rp is not None:
            cd = rp.crawl_delay(ROBOTS_AGENT)
            if cd:
                delay = max(delay, float(cd))
        wait = self._last.get(host, 0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    # ---- requests -----------------------------------------------------
    def request(self, method: str, url: str, *, check_robots: bool = True,
                **kw) -> requests.Response:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(url)
        kw.setdefault("timeout", self.timeout)
        for attempt in range(3):
            self._throttle(url)
            self.request_count += 1
            r = self.s.request(method, url, **kw)
            if r.status_code in (429, 502, 503, 504) and attempt < 2:
                time.sleep(20 * (attempt + 1))
                continue
            return r
        return r

    def get(self, url, **kw):
        return self.request("GET", url, **kw)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def get_json(self, url, **kw):
        r = self.get(url, **kw)
        r.raise_for_status()
        return r.json()
