from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field


@dataclass
class Offer:
    source: str              # e.g. "greenhouse", "lever", "francetravail"
    source_id: str           # id inside that source
    company: str
    title: str
    url: str
    location: str = ""
    description_html: str = ""
    description: str = ""    # plain text (filled by text.html_to_text)
    posted: str | None = None          # ISO date
    employment_type: str = ""          # as given by the ATS, if any
    pay_text: str = ""                 # structured compensation from ATS
    company_type: str = "other"        # fintech / bank / ecommerce / pharma / other
    company_tags: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        raw = f"{self.source}:{self.company}:{self.source_id}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("description_html", None)
        d["id"] = self.id
        return d
