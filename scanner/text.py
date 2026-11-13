"""Text helpers: HTML -> plain text (keeping bullet structure), normalisation,
and a tiny stop-word language detector (en / fr / de)."""
from __future__ import annotations

import html
import re
import unicodedata

_BLOCK = re.compile(r"</?(p|div|br|h[1-6]|ul|ol|section|article|tr|table)[^>]*>", re.I)
_LI = re.compile(r"<li[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")


def html_to_text(s: str) -> str:
    if not s:
        return ""
    s = html.unescape(s)            # some APIs double-escape their HTML
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = _LI.sub("\n• ", s)
    s = _BLOCK.sub("\n", s)
    s = _TAG.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    out, blank = [], False
    for ln in lines:
        if not ln:
            if not blank and out:
                out.append("")
            blank = True
            continue
        out.append(ln)
        blank = False
    return "\n".join(out).strip()


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s)
                   if not unicodedata.combining(c))


def norm(s: str) -> str:
    """lowercase, no accents, single spaces — used for keyword matching."""
    s = strip_accents(s or "").lower()
    s = s.replace("’", "'")
    return re.sub(r"\s+", " ", s)


_STOP = {
    "en": "the and to of for with you your we our will in is are on as this that be "
          "team work an or from have who about".split(),
    "fr": "le la les et des du de un une vous nous pour avec dans est sont sur au aux "
          "votre notre qui ce cette par".split(),
    "de": "der die das und mit für wir sie ist sind ein eine zu von im den dem auf "
          "unser ihre bei".split(),
}


def detect_language(text: str) -> str:
    words = re.findall(r"[a-zäöüßàâçéèêëîïôûùüÿœ]+", (text or "").lower())
    if len(words) < 15:
        return "unknown"
    counts = {lang: sum(1 for w in words if w in sw) for lang, sw in
              ((k, set(v)) for k, v in _STOP.items())}
    best = max(counts, key=counts.get)
    return best if counts[best] >= 5 else "unknown"


def contains_any(text_norm: str, keywords) -> list[str]:
    """Return keywords (normalised) found as whole words / phrases."""
    hits = []
    for kw in keywords:
        k = norm(kw)
        if not k:
            continue
        pat = r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])"
        if re.search(pat, text_norm):
            hits.append(kw)
    return hits
