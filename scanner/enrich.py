"""Mission summary, required skills and the one-line "Why I fit".

- With ANTHROPIC_API_KEY set: Claude (cheapest Haiku, configurable) with a
  JSON-schema structured output. Each offer is processed once; results are
  cached inside the (encrypted) dashboard data and reused on later runs.
- Without a key, or if a call fails/refuses: rule-based extraction.
"""
from __future__ import annotations

import json
import os
import re

from .text import contains_any, norm

# ================================================================ rules
_MISSION_HDR = re.compile(
    r"^(vos missions|tes missions|missions?|tes responsabilites|responsabilites|"
    r"responsibilities|key responsibilities|your role|your mission|role|"
    r"what you('| wi)ll do|what you will be doing|ce que (vous ferez|tu feras)|"
    r"au quotidien|day[- ]to[- ]day|le poste|descriptif du poste|job description|"
    r"your responsibilities|in this role|the role)\b", re.I)
_SKILL_HDR = re.compile(
    r"^(profil( recherche)?|ton profil|votre profil|requirements|qualifications|"
    r"basic qualifications|preferred qualifications|who you are|about you|"
    r"what we('| a)re looking for|ce que nous recherchons|competences|skills|"
    r"must[- ]haves?|nice to have|you have|vous avez|tu as)\b", re.I)
_ANY_HDR = re.compile(r"^[^•\-\*].{0,60}:?\s*$")
_BUL = re.compile(r"^\s*(•|-|\*|–|\d+[.)])\s+")
SKILL_WORDS = ["excel", "powerpoint", "financial modeling", "modelisation financiere",
               "sql", "python", "salesforce", "hubspot", "crm", "english", "anglais",
               "french", "francais", "german", "allemand", "spanish", "espagnol",
               "communication", "analytical", "analytique", "negotiation",
               "negociation", "project management", "gestion de projet", "tableau",
               "power bi", "google sheets", "vba", "accounting", "comptabilite",
               "valuation", "valorisation", "storytelling", "prospection",
               "cold calling", "b2b", "data analysis"]


def _section_bullets(lines, hdr_re, limit):
    out, active = [], False
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        plain = norm(_BUL.sub("", s)).strip(" :")
        if not _BUL.match(s) and hdr_re.match(plain):
            active = True
            continue
        if active:
            if _BUL.match(s):
                out.append(_BUL.sub("", s).strip())
                if len(out) >= limit:
                    break
            elif _ANY_HDR.match(s) and out:
                break                      # next section heading
    return out


def _clip(s, n=160):
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1].rsplit(" ", 1)[0] + "…"


def rule_based(offer: dict, description: str, profile: dict) -> dict:
    lines = description.splitlines()
    missions = _section_bullets(lines, _MISSION_HDR, 5)
    if len(missions) < 3:
        missions = [_BUL.sub("", l).strip() for l in lines if _BUL.match(l)][:5]
    if len(missions) < 3:
        sents = re.split(r"(?<=[.!?])\s+", description.replace("\n", " "))
        missions = [s for s in sents if 40 < len(s) < 250][:4]
    skills = _section_bullets(lines, _SKILL_HDR, 6)
    if not skills:
        found = contains_any(norm(description), SKILL_WORDS)
        skills = found[:8]
    return {
        "mission": [_clip(m) for m in missions[:5]],
        "skills": [_clip(s, 110) for s in skills[:6]],
        "why_fit": why_fit_rules(offer, description, profile),
        "method": "rules",
    }


def why_fit_rules(offer: dict, description: str, profile: dict) -> str:
    d = norm(f"{offer.get('title', '')} {description}")
    hits = []
    for h in profile.get("highlights", []):
        if contains_any(d, h.get("keywords", [])):
            hits.append(h["phrase"])
        if len(hits) == 2:
            break
    lang = offer.get("language")
    if lang == "de" or contains_any(d, ["german", "allemand", "deutsch", "dach"]):
        hits.append("native German")
    if not hits:
        hits = profile.get("default_fit", ["business-school background with finance "
                                           "internship experience"])[:1]
    labels = offer.get("category_labels") or []
    lead = f"{labels[0]} role" if labels else "Business role"
    return f"{lead} — draws on " + " and ".join(dict.fromkeys(hits)) + "."


# ================================================================ Claude
SCHEMA = {
    "type": "object",
    "properties": {
        "mission": {"type": "array", "items": {"type": "string"},
                    "description": "3-5 short bullets: concrete tasks of the internship"},
        "skills": {"type": "array", "items": {"type": "string"},
                   "description": "up to 6 required skills / qualifications, short"},
        "why_fit": {"type": "string",
                    "description": "ONE sentence (max 30 words) linking this offer to "
                                   "the candidate profile; concrete, no flattery"},
    },
    "required": ["mission", "skills", "why_fit"],
    "additionalProperties": False,
}


class ClaudeEnricher:
    def __init__(self, cfg: dict, profile: dict):
        import anthropic
        self.anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = cfg["enrichment"]["model"]
        self.max_chars = cfg["enrichment"]["max_description_chars"]
        prof = profile.get("summary") or json.dumps(profile, ensure_ascii=False)
        self.system = (
            "You summarise internship offers for one student. Write in English, "
            "even when the offer is in French or German. Be factual: only use "
            "what the offer says. Mission bullets start with a verb and are under "
            "18 words. 'why_fit' must cite one or two specific items from the "
            "candidate profile that match the offer (experience, skills, "
            "languages or interests); never use the candidate's name or school "
            "name.\n\nCandidate profile:\n" + prof)
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def enrich(self, offer: dict, description: str) -> dict | None:
        desc = description
        note = ""
        if len(desc) > self.max_chars:
            desc = desc[:self.max_chars]
            note = "\n[Description shortened for length.]"
        user = (f"Title: {offer['title']}\nCompany: {offer['company']}\n"
                f"Location: {offer['location']}\n\nOffer text:\n{desc}{note}")
        try:
            r = self.client.messages.create(
                model=self.model, max_tokens=4000,
                system=self.system,
                output_config={"effort": "low",
                               "format": {"type": "json_schema", "schema": SCHEMA}},
                messages=[{"role": "user", "content": user}],
            )
        except self.anthropic.APIError as e:
            print(f"    ! Claude error for {offer['title'][:50]}: {e.__class__.__name__}")
            return None
        self.calls += 1
        self.input_tokens += r.usage.input_tokens
        self.output_tokens += r.usage.output_tokens
        if r.stop_reason != "end_turn":
            return None                       # refusal / max_tokens -> rules
        text = next((b.text for b in r.content if b.type == "text"), None)
        if not text:
            return None
        d = json.loads(text)
        return {"mission": d["mission"][:5], "skills": d["skills"][:6],
                "why_fit": d["why_fit"], "method": "ai"}

    def cost_usd(self) -> float:
        # Claude Haiku 5.5: $0.10 / MTok input, $0.50 / MTok output
        return self.input_tokens * 0.10 / 1e6 + self.output_tokens * 0.50 / 1e6


def make_enricher(cfg, profile):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return ClaudeEnricher(cfg, profile)
    except Exception as e:  # noqa: BLE001
        print(f"Claude enrichment disabled: {e}")
        return None
