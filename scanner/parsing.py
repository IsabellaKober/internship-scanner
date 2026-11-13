"""Parse internship duration, start date, application deadline and pay from
free text, in French and English (German month names are understood too).

All matching is done on `text.norm()` output: lowercase, accents stripped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from .text import norm

# ---------------------------------------------------------------- numbers
_NUMWORDS = {
    "un": 1, "une": 1, "one": 1, "a": 1, "an": 1, "deux": 2, "two": 2,
    "trois": 3, "three": 3, "quatre": 4, "four": 4, "cinq": 5, "five": 5,
    "six": 6, "sept": 7, "seven": 7, "huit": 8, "eight": 8, "neuf": 9,
    "nine": 9, "dix": 10, "ten": 10, "onze": 11, "eleven": 11, "douze": 12,
    "twelve": 12, "zwei": 2, "drei": 3, "vier": 4, "sechs": 6,
}
_NUM = (r"(\d{1,2}(?:[.,]5)?|un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|"
        r"onze|douze|one|two|three|four|five|seven|eight|nine|ten|eleven|"
        r"twelve|zwei|drei|vier|sechs)")


def _num(s: str) -> float:
    s = s.strip()
    if s in _NUMWORDS:
        return float(_NUMWORDS[s])
    return float(s.replace(",", "."))


# ---------------------------------------------------------------- months
MONTHS = {
    "janvier": 1, "janv": 1, "january": 1, "jan": 1, "januar": 1,
    "fevrier": 2, "fevr": 2, "fev": 2, "february": 2, "feb": 2, "februar": 2,
    "mars": 3, "march": 3, "mar": 3, "marz": 3,
    "avril": 4, "avr": 4, "april": 4, "apr": 4,
    "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6, "juni": 6,
    "juillet": 7, "juil": 7, "july": 7, "jul": 7, "juli": 7,
    "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "september": 9, "sept": 9, "sep": 9,
    "octobre": 10, "october": 10, "oct": 10, "oktober": 10,
    "novembre": 11, "november": 11, "nov": 11,
    "decembre": 12, "december": 12, "dec": 12, "dezember": 12,
}
_MONTH_RE = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
# season -> (month, day) used as an approximate start
SEASONS = {
    "printemps": (4, 20), "spring": (4, 20), "fruhling": (4, 20),
    "ete": (6, 15), "summer": (6, 15), "sommer": (6, 15),
    "automne": (9, 15), "fall": (9, 15), "autumn": (9, 15), "herbst": (9, 15),
    "hiver": (1, 15), "winter": (1, 15),
    "rentree": (9, 1),
}
_SEASON_RE = "(" + "|".join(SEASONS) + ")"


# ================================================================ DURATION
@dataclass
class DurationInfo:
    min_months: float | None = None
    max_months: float | None = None
    mentions: list[str] = field(default_factory=list)
    long_flags: list[str] = field(default_factory=list)   # cesure, gap year...
    end_of_studies: bool = False

    @property
    def stated(self) -> bool:
        return self.min_months is not None

    def label(self) -> str:
        if not self.stated:
            return "Duration not stated"
        a, b = self.min_months, self.max_months

        def f(x):
            return str(int(x)) if float(x).is_integer() else f"{x:.1f}"
        return f"{f(a)} months" if a == b else f"{f(a)}–{f(b)} months"


_UNIT_M = r"(?:mois|months?|monate?n?)"
_UNIT_W = r"(?:semaines?|weeks?|wochen?)"
_DUR_RE = re.compile(
    r"(?<![\w\d])" + _NUM + r"(?:\s*(?:-|–|a|to|ou|or|/|bis)\s*" + _NUM + r")?"
    r"\s*-?\s*(" + _UNIT_M + "|" + _UNIT_W + r")(?![a-z])")
_YEAR_INTERN_RE = re.compile(
    r"(stage|internship|praktikum)\s+(?:d'|de\s+|of\s+)?(un|une|1|one)\s*-?\s*(an|annee|year)\b"
    r"|(one|1)\s*-?\s*year\s+(internship|stage)")
# context that means the number is NOT the internship length
_BAD_AFTER = re.compile(
    r"^[^.;\n]{0,15}?(d'experience|de experience|experience|d'anciennete|of exp|exp\b|"
    r"ago|before|after|apres|plus tard|later|of onboarding|d'onboarding|"
    r"de periode d'essai|probation|minimum dans|in a similar|dans un poste|"
    r"in a (similar|previous|comparable)|in (sales|finance|a))")
_BAD_BEFORE = re.compile(
    r"(experience|experiences|within|au bout d[eu]|dans les|after|apres|first|"
    r"premiers|period|essai|depuis|over the (last|past)|il y a|for the (first|next)|"
    r"every|tous les|chaque|since|last|derniers|past|up to|jusqu'a|less than|"
    r"moins de|onboarding|en|in)\s*(\w+\s*){0,1}$")
_LONG_PHRASES = ["cesure", "gap year", "annee de cesure", "stage de cesure",
                 "cesure internship"]
_END_OF_STUDIES = ["fin d'etudes", "fin d etudes", "end of studies",
                   "end-of-studies", "final year internship", "pfe",
                   "projet de fin d'etudes", "final-year internship"]


def parse_duration(text: str) -> DurationInfo:
    t = norm(text)
    info = DurationInfo()
    mins, maxs = [], []
    for m in _DUR_RE.finditer(t):
        before = t[max(0, m.start() - 30):m.start()]
        after = t[m.end():m.end() + 40]
        if _BAD_AFTER.search(after) or _BAD_BEFORE.search(before):
            continue
        a = _num(m.group(1))
        b = _num(m.group(2)) if m.group(2) else a
        unit = m.group(3)
        if re.match(_UNIT_W, unit):
            a, b = a / 4.345, b / 4.345
        if a > b:
            a, b = b, a
        if a <= 0 or b > 24:
            continue
        mins.append(round(a, 1))
        maxs.append(round(b, 1))
        info.mentions.append(m.group(0))
    for m in _YEAR_INTERN_RE.finditer(t):
        mins.append(12.0)
        maxs.append(12.0)
        info.mentions.append(m.group(0))
    if mins:
        info.min_months = min(mins)
        info.max_months = max(maxs)
    for p in _LONG_PHRASES:
        if p in t:
            info.long_flags.append(p)
    info.end_of_studies = any(p in t for p in _END_OF_STUDIES)
    return info


# ================================================================ DATES
@dataclass
class StartInfo:
    candidates: list[date] = field(default_factory=list)
    raw: list[str] = field(default_factory=list)
    asap: bool = False

    @property
    def stated(self) -> bool:
        return bool(self.candidates)

    def label(self) -> str:
        if not self.candidates:
            return "Start date not stated"
        if self.asap and len(self.candidates) == 1:
            return "ASAP"
        labels = [d.strftime("%b %Y") if d.day in (1, 15, 20) else
                  d.strftime("%d %b %Y") for d in sorted(set(self.candidates))]
        return ", ".join(dict.fromkeys(labels))


_DMY = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](20\d{2}|\d{2})\b")
_YMD = re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b")
_MY = re.compile(r"\b(\d{1,2})[/.](20\d{2})\b")
_DAY_MONTH = re.compile(r"\b(1er|\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RE +
                        r"(?:\s*,?\s*(20\d{2}))?")
_MONTH_DAY = re.compile(r"\b" + _MONTH_RE + r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})")
_MONTH_YEAR = re.compile(r"\b" + _MONTH_RE + r"\s*,?\s*(20\d{2})")
_TWO_MONTHS_YEAR = re.compile(r"\b" + _MONTH_RE + r"\s*(?:ou|or|/|et|and|-)\s*" + _MONTH_RE +
                              r"\s*,?\s*(20\d{2})")
_MONTH_ONLY = re.compile(r"\b" + _MONTH_RE + r"(?![a-z])")
_SEASON_YEAR = re.compile(r"\b" + _SEASON_RE + r"\s*(?:internship\s*|intern\s*|"
                          r"stage\s*)?(20\d{2})\b|\b(20\d{2})\s+" + _SEASON_RE + r"\b")
_ASAP = re.compile(r"\b(asap|as soon as possible|des que possible|immediat(e|ement)?|"
                   r"immediately|au plus tot|au plus vite|right away|ab sofort)\b")
_START_KW = re.compile(
    r"(date de debut|debut|demarrage|commencement|a partir d[eu]|a compter d[eu]|"
    r"des le|des\b|start date|starting date|starting|start|beginning|begin|"
    r"from|prise de poste|disponibilite|available from|starts|ab dem|ab\b|beginn|"
    r"date d'arrivee|arrivee)")


def _safe_date(y, m, d=1):
    try:
        return date(int(y), int(m), int(d))
    except ValueError:
        return None


def _infer_year(month: int, ref: date) -> int:
    # first occurrence of `month` on or after the reference month
    return ref.year if month >= ref.month else ref.year + 1


def _dates_in(chunk: str, ref: date, allow_bare_month: bool) -> list[date]:
    out = []
    for m in _YMD.finditer(chunk):
        d = _safe_date(m.group(1), m.group(2), m.group(3))
        if d:
            out.append(d)
    for m in _DMY.finditer(chunk):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        d = _safe_date(y, m.group(2), m.group(1))      # French order d/m/y
        if d:
            out.append(d)
    if out:
        return out
    for m in _MONTH_DAY.finditer(chunk):
        d = _safe_date(m.group(3), MONTHS[m.group(1)], m.group(2))
        if d:
            out.append(d)
    for m in _DAY_MONTH.finditer(chunk):
        day = 1 if m.group(1) == "1er" else int(m.group(1))
        mon = MONTHS[m.group(2)]
        y = m.group(3) or _infer_year(mon, ref)
        d = _safe_date(y, mon, day)
        if d:
            out.append(d)
    if out:
        return out
    for m in _TWO_MONTHS_YEAR.finditer(chunk):
        for g in (1, 2):
            d = _safe_date(m.group(3), MONTHS[m.group(g)], 1)
            if d:
                out.append(d)
    if out:
        return out
    for m in _MONTH_YEAR.finditer(chunk):
        d = _safe_date(m.group(2), MONTHS[m.group(1)], 1)
        if d:
            out.append(d)
    for m in _MY.finditer(chunk):
        d = _safe_date(m.group(2), m.group(1), 1)
        if d:
            out.append(d)
    for m in _SEASON_YEAR.finditer(chunk):
        season = m.group(1) or m.group(4)
        year = m.group(2) or m.group(3)
        mon, day = SEASONS[season]
        d = _safe_date(year, mon, day)
        if d:
            out.append(d)
    if out or not allow_bare_month:
        return out
    for m in _MONTH_ONLY.finditer(chunk):
        word = m.group(1)
        if word in ("may", "mar", "jan", "sep", "dec", "oct", "nov", "aug", "jun",
                    "jul", "apr", "feb", "fev", "mars"):
            # ambiguous short words / English modal "may" need a year
            continue
        mon = MONTHS[word]
        d = _safe_date(_infer_year(mon, ref), mon, 1)
        if d:
            out.append(d)
    return out


def parse_start(text: str, title: str = "", ref: date | None = None) -> StartInfo:
    ref = ref or date.today()
    info = StartInfo()
    t = norm(text)
    tt = norm(title)

    # 1) title: "Stage - Juin 2027", "Summer Internship 2027", "Stage avril 2027"
    for d in _dates_in(tt, ref, allow_bare_month=True):
        info.candidates.append(d)
        info.raw.append(title)

    # 2) text windows after a start keyword
    for m in _START_KW.finditer(t):
        window = t[m.end():m.end() + 45]
        if _ASAP.search(window[:25]):
            info.asap = True
            info.candidates.append(ref)
            info.raw.append(t[m.start():m.end() + 25])
            continue
        ds = _dates_in(window, ref, allow_bare_month=True)
        if ds:
            info.candidates.append(ds[0])
            # "from May to July 2027" / "janvier ou juillet 2027"
            info.candidates.extend(ds[1:2])   # "janvier ou juillet 2027"
            info.raw.append(t[m.start():m.end() + 45].strip())

    # 3) anywhere: "summer 2027" / "ete 2027"
    for m in _SEASON_YEAR.finditer(t):
        season = m.group(1) or m.group(4)
        year = m.group(2) or m.group(3)
        mon, day = SEASONS[season]
        d = _safe_date(year, mon, day)
        if d and d not in info.candidates:
            info.candidates.append(d)
            info.raw.append(m.group(0))

    if not info.candidates and _ASAP.search(t):
        info.asap = True
        info.candidates.append(ref)
        info.raw.append("asap")
    # de-dup, keep order
    seen, uniq = set(), []
    for d in info.candidates:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    info.candidates = uniq
    return info


_DEADLINE_KW = re.compile(
    r"(date limite( de candidature)?|deadline|apply by|apply before|application deadline|"
    r"postul(er|ez) avant( le)?|candidater avant( le)?|candidatures? (jusqu'au|avant le)|"
    r"closing date|cloture des candidatures|bewerbungsschluss|until)")


def parse_deadline(text: str, ref: date | None = None) -> date | None:
    ref = ref or date.today()
    t = norm(text)
    for m in _DEADLINE_KW.finditer(t):
        window = t[m.end():m.end() + 40]
        ds = _dates_in(window, ref, allow_bare_month=False)
        # only accept specific days for deadlines
        ds = [d for d in ds if d >= ref - timedelta(days=30)]
        if ds:
            return ds[0]
    return None


def start_compatible(info: StartInfo, earliest: date, latest: date) -> bool | None:
    """True/False if a start date is stated, None if not stated."""
    if not info.candidates:
        return None

    def ok(d: date) -> bool:
        if earliest <= d <= latest:
            return True
        # month-level dates ("avril 2027" -> 1 Apr): compatible if any day of
        # that month is inside the window
        if d.day == 1 and d < earliest:
            nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
            return nxt > earliest
        return False
    return any(ok(d) for d in info.candidates)


# ================================================================ PAY
@dataclass
class PayInfo:
    monthly_min: float | None = None
    monthly_max: float | None = None
    raw: str = ""
    legal_minimum: bool = False

    @property
    def stated(self) -> bool:
        return self.monthly_min is not None

    def label(self) -> str:
        if not self.stated:
            return "Pay not stated"
        if self.legal_minimum and self.raw == "legal minimum":
            return f"Legal minimum (~€{self.monthly_min:,.0f}/month)"
        a, b = self.monthly_min, self.monthly_max
        if a == b:
            return f"€{a:,.0f}/month"
        return f"€{a:,.0f}–{b:,.0f}/month"


_AMOUNT = r"(\d{1,3}(?:[ ., ]\d{3})+|\d+(?:[.,]\d{1,2})?)\s*(k)?"
_CUR = r"(?:€|eur\b|euros?\b)"
_PAY_AMT = re.compile(
    r"(?:" + _CUR + r"\s*" + _AMOUNT + r"(?:\s*(?:-|–|a|to|et)\s*" + _CUR + r"?\s*" +
    _AMOUNT + r")?)"
    r"|(?:" + _AMOUNT + r"\s*" + _CUR + r"?\s*(?:-|–|a|to|et)\s*" + _AMOUNT + r"\s*" +
    _CUR + r")"
    r"|(?:" + _AMOUNT + r"\s*" + _CUR + r")")
_PAY_KW = re.compile(r"(gratification|remuneration|salaire|salary|stipend|\bpay\b|paid|"
                     r"compensation|indemnite|allowance|brut|gross|verguetung|gehalt|"
                     r"package)")
_LEGAL_MIN = re.compile(r"(gratification (legale|minimale|minimum|conventionnelle)|"
                        r"minimum legal|legal minimum|selon (la )?(grille|reglementation) "
                        r"legale|montant legal|taux legal|statutory (minimum|rate))")
_NOT_PAY = re.compile(r"^\s*(m\b|mn|md|million|milliard|bn|billion|mds?\b)")
LEGAL_MONTHLY = 4.35 * 154   # 2026 hourly floor x 154h (≈ 22 days x 7h)


def _amount(s: str, k: str | None) -> float:
    s = s.replace(" ", " ")
    # "1 200" / "1.200" / "1,200" thousands separators vs "4,35" decimals
    if re.fullmatch(r"\d{1,3}([ .,]\d{3})+", s):
        v = float(re.sub(r"[ .,]", "", s))
    else:
        v = float(s.replace(",", ".").replace(" ", ""))
    return v * 1000 if k else v


def parse_pay(text: str, structured: str = "") -> PayInfo:
    info = PayInfo()
    sources = []
    if structured:
        sources.append((norm(structured), True))
    sources.append((norm(text), False))
    for t, is_structured in sources:
        for m in _PAY_AMT.finditer(t):
            if _NOT_PAY.match(t[m.end():m.end() + 10]):
                continue
            ctx_before = t[max(0, m.start() - 90):m.start()]
            ctx_after = t[m.end():m.end() + 40]
            if not is_structured and not (_PAY_KW.search(ctx_before) or
                                          _PAY_KW.search(ctx_after[:20])):
                continue
            g = [x for x in m.groups()]
            nums = []
            for i in range(0, len(g), 2):
                if g[i]:
                    nums.append(_amount(g[i], g[i + 1]))
            if not nums:
                continue
            period_ctx = ctx_after[:25] + " " + m.group(0)
            lo, hi = min(nums), max(nums)
            if re.search(r"(/\s*h\b|heure|hour|horaire|stunde)", period_ctx):
                lo, hi = lo * 154, hi * 154
            elif re.search(r"(/\s*an\b|annuel|par an|year|annual|yearly|\bpa\b|/\s*y)",
                           period_ctx) or lo > 6000:
                lo, hi = lo / 12, hi / 12
            elif lo < 30:          # bare small number => hourly
                lo, hi = lo * 154, hi * 154
            if lo < 100:           # still implausible
                continue
            info.monthly_min, info.monthly_max = round(lo), round(hi)
            info.raw = m.group(0).strip()
            return info
    t = norm(text)
    if _LEGAL_MIN.search(t):
        info.legal_minimum = True
        info.monthly_min = info.monthly_max = round(LEGAL_MONTHLY)
        info.raw = "legal minimum"
    return info
