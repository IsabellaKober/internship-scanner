"""France Travail "Offres d'emploi v2" API (official, free, needs an
application registered on francetravail.io).

Secrets: FT_CLIENT_ID, FT_CLIENT_SECRET. If they are not set the source is
skipped (reported as "not configured", not as a failure)."""
from __future__ import annotations

import os

from ..models import Offer
from .base import iso_date

NAME = "francetravail"
TOKEN_URL = ("https://entreprise.francetravail.fr/connexion/oauth2/access_token"
             "?realm=%2Fpartenaire")
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
SCOPE = "api_offresdemploiv2 o2dsoffre"


def configured() -> bool:
    return bool(os.environ.get("FT_CLIENT_ID") and os.environ.get("FT_CLIENT_SECRET"))


def _token(session):
    r = session.post(TOKEN_URL, check_robots=False, data={
        "grant_type": "client_credentials",
        "client_id": os.environ["FT_CLIENT_ID"],
        "client_secret": os.environ["FT_CLIENT_SECRET"],
        "scope": SCOPE,
    })
    r.raise_for_status()
    return r.json()["access_token"]


def fetch(session, cfg):
    tok = _token(session)
    headers = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    out, seen = [], set()
    for kw in cfg.get("keywords", ["stage", "stagiaire", "internship"]):
        for start in range(0, 450, 150):
            r = session.get(SEARCH_URL, check_robots=False, headers=headers, params={
                "motsCles": kw, "departement": ",".join(cfg.get("departements",
                                                               ["75", "92", "93", "94"])),
                "range": f"{start}-{start + 149}", "publieeDepuis": 31,
            })
            if r.status_code == 204:
                break
            r.raise_for_status()
            res = r.json().get("resultats", [])
            for o in res:
                if o["id"] in seen:
                    continue
                seen.add(o["id"])
                lieu = o.get("lieuTravail") or {}
                out.append(Offer(
                    source=NAME, source_id=o["id"],
                    company=(o.get("entreprise") or {}).get("nom") or "Unknown company",
                    title=o.get("intitule", ""),
                    url=(o.get("origineOffre") or {}).get("urlOrigine") or
                        f"https://candidat.francetravail.fr/offres/recherche/detail/{o['id']}",
                    location=f"{lieu.get('libelle', '')} {lieu.get('codePostal', '')}".strip(),
                    description_html=(o.get("description") or "").replace("\n", "<br>"),
                    posted=iso_date(o.get("dateCreation")),
                    employment_type=" ".join(filter(None, [
                        o.get("typeContrat"), o.get("typeContratLibelle"),
                        o.get("natureContrat")])),
                    pay_text=(o.get("salaire") or {}).get("libelle", ""),
                ))
            if len(res) < 150:
                break
    return out
