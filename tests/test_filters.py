from datetime import date

import pytest

from scanner import filters, scoring
from scanner.config import load_config
from scanner.dedupe import dedupe
from scanner.parsing import parse_duration, parse_pay, parse_start
from scanner.run import process
from scanner.models import Offer

CFG = load_config()
REF = date(2026, 11, 13)


# ------------------------------------------------------------- location
@pytest.mark.parametrize("loc", [
    "Paris, France", "Paris 75009", "La Défense", "Puteaux (92)",
    "Issy-les-Moulineaux, Île-de-France", "Saint-Ouen-sur-Seine",
    "Montreuil 93100", "Ivry-sur-Seine", "Paris (Hybrid)", "London; Paris",
    "Clichy",
])
def test_location_kept(loc):
    assert filters.check_location(loc, "", CFG)[0]


@pytest.mark.parametrize("loc", [
    "Lyon, France", "Bordeaux", "Remote", "Remote - France", "Berlin, Germany",
    "Versailles 78000", "Lille", "",
])
def test_location_excluded(loc):
    assert not filters.check_location(loc, "", CFG)[0]


def test_location_generic_idf_is_kept_but_tagged():
    ok, _, tags = filters.check_location("Île-de-France", "", CFG)
    assert ok and "Check location" in tags


# ------------------------------------------------------------- contract
@pytest.mark.parametrize("title,etype", [
    ("Stage - Business Developer (H/F)", ""),
    ("Sales Intern", ""),
    ("Business Analyst", "Internship"),
    ("Stagiaire Contrôle de gestion", ""),
    ("Summer Analyst 2027 - M&A", ""),
    ("Stage / Alternance - Growth Marketing", ""),     # internship offered too
    ("Stage - Assurance Vie", ""),                    # "vie" = life, not V.I.E
])
def test_contract_internship(title, etype):
    assert filters.check_contract(title, etype, CFG)[0]


@pytest.mark.parametrize("title,etype", [
    ("Alternance - Business Developer", ""),
    ("Apprentissage Contrôleur de gestion", ""),
    ("Account Executive", "Full-time"),
    ("CDI - Sales Manager", ""),
    ("CDD 6 mois - Assistant", ""),
    ("V.I.E - Business Analyst - Singapore", ""),
    ("VIE Finance Analyst", ""),
    ("Freelance Growth Marketer", ""),
])
def test_contract_excluded(title, etype):
    assert not filters.check_contract(title, etype, CFG)[0]


# ------------------------------------------------------------- dates
def _dates(text, title=""):
    return filters.check_dates(parse_duration(title + " " + text),
                               parse_start(text, title, REF), CFG)


def test_dates_hide_long():
    assert not _dates("Stage de 6 mois")[0]
    assert not _dates("6-month internship")[0]
    assert not _dates("Stage de 4 à 6 mois")[0]
    assert not _dates("Stage de césure")[0]
    assert not _dates("Stage de fin d'études")[0]


def test_dates_keep_short_or_unstated():
    ok, _, tags = _dates("Stage de 3 mois, début mai 2027")
    assert ok and not tags
    ok, _, tags = _dates("Great internship in our sales team")
    assert ok and "Duration not stated" in tags
    assert _dates("Stage de fin d'études de 3 mois")[0]       # short -> kept
    assert _dates("Internship of 3 to 6 months")[0]           # negotiable -> kept


def test_dates_hide_incompatible_start():
    assert not _dates("Début : janvier 2027")[0]
    assert not _dates("Starting September 2027")[0]
    assert not _dates("Start ASAP")[0]
    assert _dates("Starting date: May 2027")[0]


# ------------------------------------------------------------- pay
def test_pay_filter():
    assert not filters.check_pay(parse_pay("Gratification : 800 € / mois"), CFG)[0]
    assert not filters.check_pay(parse_pay("Gratification légale"), CFG)[0]
    assert filters.check_pay(parse_pay("Gratification : 1 200 € / mois"), CFG)[0]
    ok, _, tags = filters.check_pay(parse_pay("Nice team"), CFG)
    assert ok and tags == ["Pay not stated"]


# ------------------------------------------------------------- roles
@pytest.mark.parametrize("title,ctype", [
    ("Customer Success Intern", "fintech"),
    ("Stage Customer Support", "other"),
    ("Talent Acquisition Intern", "fintech"),
    ("Stage Chargé(e) de recrutement", "other"),
    ("Stage RH", "bank"),
    ("Software Engineer Intern", "fintech"),
    ("Data Scientist Intern", "ecommerce"),
    ("Stage Affaires Réglementaires", "pharma"),
    ("Stage Pharmacovigilance", "pharma"),
    ("Stage Communication interne", "pharma"),        # not commercial/BD/finance
])
def test_roles_excluded(title, ctype):
    assert not filters.check_role(title, "", ctype, CFG)[0]


@pytest.mark.parametrize("title,ctype", [
    ("Stage Business Developer", "fintech"),
    ("Stage Contrôle de gestion", "pharma"),
    ("Market Access & Commercial Strategy Intern", "pharma"),
    ("Strategy Intern", "other"),
    ("Ingénieur commercial - stage", "other"),
])
def test_roles_kept(title, ctype):
    assert filters.check_role(title, "", ctype, CFG)[0]


# ------------------------------------------------------------- scoring
def test_role_priority_order():
    fin = scoring.role_score("Stage Finance", "", "fintech", 50, CFG)
    sales = scoring.role_score("Sales Intern", "", "other", 50, CFG)
    strat = scoring.role_score("Strategy Intern", "", "other", 50, CFG)
    ecom = scoring.role_score("E-commerce Intern", "", "other", 50, CFG)
    corpfin = scoring.role_score("Corporate Finance Intern", "", "other", 20, CFG)
    assert fin[0] > sales[0] > strat[0] > ecom[0] > corpfin[0]
    assert "fintech" in fin[1]


def test_concrete_finance_boost():
    vague = scoring.role_score("M&A Intern", "Assist the team", "other", 30, CFG)[0]
    concrete = scoring.role_score(
        "M&A Intern", "You will build financial models (DCF, LBO), prepare "
        "investment memos and support due diligence on live deals", "other", 70, CFG)[0]
    assert concrete > vague and concrete >= 80


def test_clarity_vague_vs_concrete():
    vague = "Missions variées. Vous assisterez l'équipe sur divers projets."
    concrete = ("Vos missions :\n• Analyser le pipeline commercial et suivre les KPIs\n"
                "• Construire des dashboards sous Excel et Salesforce\n"
                "• Préparer les business reviews mensuelles\n"
                "• Identifier les comptes prioritaires\n"
                "Rattaché(e) au Head of Sales, au sein de l'équipe Sales Ops.\n") * 3
    assert scoring.clarity_score(concrete, CFG)[0] > scoring.clarity_score(vague, CFG)[0] + 30


# ------------------------------------------------------------- end-to-end
def _offer(**kw):
    base = dict(source="test", source_id="1", company="Qonto", title="Sales Intern",
                url="https://x", location="Paris", company_type="fintech",
                description_html="<p>Internship of 3 months starting May 2027.</p>")
    base.update(kw)
    return Offer(**base)


def test_process_pipeline():
    d, reason = process(_offer(), CFG, REF)
    assert d and reason is None and d["score"] > 50 and "Fintech" in d["category_labels"]
    assert process(_offer(location="Lyon"), CFG, REF)[0] is None
    assert process(_offer(title="Sales Intern (6 mois)"), CFG, REF)[0] is None
    assert process(_offer(title="Alternance Sales"), CFG, REF)[0] is None


def test_dedupe_merges_sources():
    a = {"company": "Qonto", "title": "Stage - Business Developer (H/F)",
         "url": "u1", "sources": ["ashby"], "description": "short"}
    b = {"company": "QONTO SAS", "title": "Business Developer Intern",
         "url": "u2", "sources": ["francetravail"], "description": "longer text"}
    c = {"company": "Qonto", "title": "Finance Intern", "url": "u3",
         "sources": ["ashby"], "description": ""}
    out = dedupe([a, b, c])
    assert len(out) == 2
    assert out[0]["sources"] == ["ashby", "francetravail"]


def test_pharma_regulatory_strategy_excluded():
    assert not filters.check_role("Stagiaire CMC Regulatory Strategy", "", "pharma", CFG)[0]
    assert not filters.check_role("Associate Solutions Architect Internship", "", "ecommerce", CFG)[0]


def test_unknown_company_fintech_by_content():
    # e.g. an Adzuna offer from a company that is not in config.yaml
    s, cats = scoring.role_score("Stage Business Developer - Paiements",
                                 "Fintech spécialisée dans les paiements et l'open banking, API",
                                 "other", 50, CFG)
    assert "fintech" in cats and s == 100
    s, cats = scoring.role_score("Stage Business Developer", "Agence de voyage", "other", 50, CFG)
    assert "fintech" not in cats


# ------------------------------------------------------------- role must match (Nov 2026)
@pytest.mark.parametrize("title", [
    "Scriptwriter intern", "Stage - Social Media Manager", "Privacy Legal Intern",
    "AML/CFT & Fraud Analyst - Internship", "Content Creator Intern",
    "Regulatory Compliance Intern",
])
def test_off_path_roles_hidden_even_at_fintech(title):
    assert not filters.check_role(title, "", "fintech", CFG)[0]


def test_fintech_company_alone_is_not_enough():
    s, cats = scoring.role_score("Analytics & Process Engineer - Intern",
                                 "payments fintech sales strategy", "fintech", 60, CFG)
    assert s <= 20 and "fintech" not in cats
    s, cats = scoring.role_score("Sales Development Intern", "", "fintech", 60, CFG)
    assert s == 100 and cats[0] == "fintech"


def test_off_path_total_is_capped():
    parts = {"role": 10, "clarity": 100, "dates": 100, "language": 100, "company": 100}
    assert scoring.total_score(parts, CFG) <= 30


def test_generic_programme_judged_on_description():
    s, _ = scoring.role_score("Summer Intern 2027 - Alan Summer Internship Program",
                              "Join our sales, business development and strategy teams; "
                              "sales pipeline, strategic projects, partnerships", "insurance", 60, CFG, "Alan")
    assert 40 <= s < 100


def test_dates_clear_window_beats_unstated():
    from scanner.parsing import parse_duration, parse_start
    ref = REF
    clear = scoring.date_score(parse_duration("Stage de 3 mois"),
                               parse_start("Début : 2 mai 2027", "", ref), CFG)
    vague = scoring.date_score(parse_duration(""), parse_start("", "", ref), CFG)
    june = scoring.date_score(parse_duration("3 months"),
                              parse_start("Start date: June 2027", "", ref), CFG)
    assert clear == 100 and vague == 0 and clear > june > vague


# ------------------------------------------------------------- on-site only / 2nd-year eligibility
@pytest.mark.parametrize("loc,desc", [
    ("Paris (Hybrid)", ""),
    ("Paris, France (hybrid)", ""),
    ("Paris", "We work in a hybrid model with 2 days of remote work per week."),
    ("Paris", "Télétravail possible 2 jours par semaine."),
    ("Paris", "Remote-friendly culture and flexible hours."),
])
def test_hybrid_hidden(loc, desc):
    assert not filters.check_workplace(loc, desc, CFG)[0]


@pytest.mark.parametrize("loc,desc", [
    ("Paris (OnSite)", "You will join our office in Paris."),
    ("Paris", "Pas de télétravail : le stage est 100% présentiel."),
    ("Paris", "This is a full on-site role, no remote work."),
])
def test_onsite_kept(loc, desc):
    assert filters.check_workplace(loc, desc, CFG)[0]


@pytest.mark.parametrize("desc", [
    "You are in the final year of your Bachelor's degree or currently doing a Master's.",
    "Étudiant(e) en dernière année d'école de commerce.",
    "Vous êtes étudiant(e) en Master 2 (Bac+5) en école de commerce.",
    "You are currently enrolled in a Master's program in finance.",
])
def test_final_year_or_masters_only_hidden(desc):
    assert not filters.check_eligibility(desc, CFG)[0]


@pytest.mark.parametrize("desc", [
    "Open to Bachelor or Master students in business or economics.",
    "Étudiant(e) en école de commerce (Bac+3 à Bac+5).",
    "We welcome 2nd year students and Master's students alike.",
    "You master Excel and PowerPoint.",
])
def test_open_to_second_years_kept(desc):
    assert filters.check_eligibility(desc, CFG)[0]
