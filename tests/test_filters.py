from datetime import date

import pytest

from scanner import filters, relevance, scoring
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
    ("Stage Customer Support", "startup"),
    ("Talent Acquisition Intern", "fintech"),
    ("Stage Chargé(e) de recrutement", "startup"),
    ("Stage RH", "bank"),
    ("Software Engineer Intern", "fintech"),
    ("Data Scientist Intern", "startup"),
    ("Stage Affaires Réglementaires", "corporate"),
    ("Stage Pharmacovigilance", "corporate"),
    ("Stage Communication interne", "corporate"),
    ("Stagiaire CMC Regulatory Strategy", "corporate"),
    # never shown, whatever the company: engineering, quant, marketing
    ("Experimental Quantum Physics Intern", "startup"),
    ("Marketing Intern Assistant", "fintech"),
    ("Stage Ingénieur Mécanique", "startup"),
    ("Quantitative Research Intern", "asset_management"),
    ("Markets | Algo Trader | Intern", "fintech"),
    ("Stage Actuariat", "insurance"),
    ("Growth Marketing Intern", "startup"),
    ("Brand Partnerships Intern", "startup"),          # marketing wins over bizdev
    ("Stage Chef de Produit", "corporate"),
    ("Scriptwriter intern", "fintech"),
    ("Stage - Social Media Manager", "fintech"),
    ("Privacy Legal Intern", "fintech"),
    ("AML/CFT & Fraud Analyst - Internship", "fintech"),
    ("Regulatory Compliance Intern", "fintech"),
    ("Associate Solutions Architect Internship", "startup"),
])
def test_roles_excluded(title, ctype):
    assert not filters.check_role(title, "", ctype, CFG)[0]


@pytest.mark.parametrize("title,ctype", [
    ("Stage Business Developer", "fintech"),
    ("Private Equity Intern", "private_equity"),
    ("Stage Analyste M&A", "investment_bank"),
    ("Strategy Intern", "startup"),
    ("Founder's Associate Intern", "startup"),
    ("Stage Corporate Development", "corporate"),       # corporates: strategy roles only
    ("Risk Management Intern", "bank"),
    ("Infrastructure Investment Intern", "private_equity"),
    ("Strategy & Growth Intern", "startup"),            # "growth" + a target function
])
def test_roles_kept(title, ctype):
    assert filters.check_role(title, "", ctype, CFG)[0]


def test_corporate_only_strategy_or_finance():
    assert not filters.check_role("Sales Development Intern", "", "corporate", CFG)[0]
    assert not filters.check_role("Operations Intern", "", "corporate", CFG)[0]
    assert filters.check_role("M&A Intern", "", "corporate", CFG)[0]


def test_engineering_hidden_even_with_business_words():
    assert not filters.check_role("Analytics & Process Engineer - Intern",
                                  "payments fintech strategy", "fintech", CFG)[0]


def test_unknown_company_needs_target_sector():
    # Adzuna / France Travail: company not listed -> sector from the offer text
    ok = relevance.evaluate("Stage Business Developer", "Start-up fintech de paiement "
                            "(série A) basée à Paris.", "Payzen Labs", "other", CFG)[0]
    assert ok and ok["sector"] in ("fintech", "startup")
    assert relevance.evaluate("Stage Business Developer", "Agence de voyage familiale.",
                              "Voyages Martin", "other", CFG)[0] is None
    assert relevance.evaluate("Stage Strategy", "Laboratoire de recherche.",
                              "Labo XYZ", "other", CFG)[1] == "company not in a target sector"


def test_known_firm_by_name_and_subsidiary():
    sec, tier, how = relevance.classify_company("BNP Paribas Asset Management", "other", "", CFG)
    assert sec == "bank" and tier == 1 and how == "listed"
    sec, tier, _ = relevance.classify_company("Ardian", "other", "", CFG)
    assert sec == "private_equity" and tier == 1
    # whole words only: "Alan" (listed) must not match "Alanya Hotels"
    assert relevance.classify_company("Alanya Hotels", "other", "", CFG)[0] is None


def test_override_accounting_beats_fund():
    lvl, key, *_ = relevance.classify_role("Fund Accounting Intern", "", "", CFG)
    assert lvl == "adjacent" and key == "accounting"


def test_generic_programme_judged_on_description():
    lvl, key, _, base, _ = relevance.classify_role(
        "Summer Intern 2027 - Alan Summer Internship Program",
        "Join our strategy, business development and partnerships teams; strategic "
        "projects, go-to-market", "Alan", CFG)
    assert lvl == "core" and 60 <= base < 90


# ------------------------------------------------------------- scoring
def test_function_priority():
    def base(t):
        return relevance.classify_role(t, "", "", CFG)[3]
    assert base("Private Equity Intern") > base("Business Development Intern") > \
        base("Sales Intern") > base("Stage Comptabilité")


def test_learning_rewards_real_tasks_and_penalises_grunt_work():
    rich = ("You will build financial models (DCF, LBO), prepare investment memos, "
            "support due diligence and present to the investment committee, working "
            "directly with the partners and founders of portfolio companies. ") * 4
    grunt = ("Missions: cold calling, lead generation, mise à jour du CRM, "
             "saisie de données and administrative tasks to support the team. ") * 4
    buzz = ("Join a fast-paced, dynamic, ambitious hypergrowth start-up! Make an "
            "impact, ownership and a unique opportunity in a fun team. ") * 4
    r = relevance.learning_adjustment("Investment Intern", rich, CFG)[0]
    g = relevance.learning_adjustment("Business Developer Intern", grunt, CFG)[0]
    b = relevance.learning_adjustment("Strategy Intern", buzz, CFG)[0]
    assert r >= 20 and g <= -20 and b <= -10


def test_assistant_titles_penalised():
    a = relevance.learning_adjustment("Stage Assistant(e) Chargé d'affaires", "x" * 800, CFG)[0]
    b = relevance.learning_adjustment("Stage Chargé d'affaires", "x" * 800, CFG)[0]
    assert a <= b - 15


def test_adjacent_roles_are_capped():
    parts = {"role": 100, "clarity": 100, "dates": 100, "language": 100, "company": 100}
    assert scoring.total_score(parts, CFG, "adjacent") <= 55
    assert scoring.total_score(parts, CFG, "core") == 100


def test_clarity_vague_vs_concrete():
    vague = "Missions variées. Vous assisterez l'équipe sur divers projets."
    concrete = ("Vos missions :\n• Analyser le pipeline commercial et suivre les KPIs\n"
                "• Construire des dashboards sous Excel et Salesforce\n"
                "• Préparer les business reviews mensuelles\n"
                "• Identifier les comptes prioritaires\n"
                "Rattaché(e) au Head of Sales, au sein de l'équipe Sales Ops.\n") * 3
    assert scoring.clarity_score(concrete, CFG)[0] > scoring.clarity_score(vague, CFG)[0] + 30


def test_dates_clear_window_beats_unstated():
    from scanner.parsing import parse_duration, parse_start
    ref = REF
    clear = scoring.date_score(parse_duration("Stage de 3 mois"),
                               parse_start("Début : 2 mai 2027", "", ref), CFG)
    vague = scoring.date_score(parse_duration(""), parse_start("", "", ref), CFG)
    june = scoring.date_score(parse_duration("3 months"),
                              parse_start("Start date: June 2027", "", ref), CFG)
    assert clear == 100 and 45 <= vague <= 55 and clear > june > vague


# ------------------------------------------------------------- end-to-end
def _offer(**kw):
    base = dict(source="test", source_id="1", company="Qonto", title="Business Developer Intern",
                url="https://x", location="Paris", company_type="fintech",
                description_html="<p>Internship of 3 months starting May 2027.</p>")
    base.update(kw)
    return Offer(**base)


def test_process_pipeline():
    d, reason = process(_offer(), CFG, REF)
    assert d and reason is None and d["score"] > 50
    assert d["category_labels"] == ["Business development", "Fintech"]
    assert process(_offer(location="Lyon"), CFG, REF)[0] is None
    assert process(_offer(title="Business Developer Intern (6 mois)"), CFG, REF)[0] is None
    assert process(_offer(title="Alternance Business Developer"), CFG, REF)[0] is None
    assert process(_offer(title="Marketing Intern"), CFG, REF)[1].startswith("role excluded")


def test_top_firm_core_role_scores_high():
    desc = ("<p>Au sein de l'équipe d'investissement, vous participerez à l'analyse "
            "d'opportunités : modélisation financière, valorisation (DCF, comparables), "
            "due diligence, rédaction de notes d'investissement pour le comité "
            "d'investissement, suivi des participations. Rattaché(e) aux associés. "
            "Stage de 3 mois à partir de mai 2027.</p>") * 3
    d, why = process(_offer(company="Ardian", title="Stage Analyste Private Equity",
                            company_type="other", description_html=desc), CFG, REF)
    assert d and d["score"] >= 80, why
    assert "Private equity" in d["category_labels"]


def test_us_zip_code_is_not_paris_suburb():
    assert not filters.check_location(
        "US - San Francisco, San Francisco 94105 United States (Hybrid)", "", CFG)[0]


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


def test_penultimate_year_counts_as_open():
    assert filters.check_eligibility(
        "Être actuellement en avant-dernière ou dernière année de licence ou master.", CFG)[0]


# ------------------------------------------------------------- retail / 4-month top roles
@pytest.mark.parametrize("title,desc", [
    ("Stage Vendeur(se) - Boutique Paris", ""),
    ("Sales Associate Intern - Store Champs-Elysées", ""),
    ("Stage Conseiller de vente", ""),
    ("Stage Commercial", "Vous accueillerez les clients en magasin et réaliserez les ventes."),
])
def test_retail_store_sales_hidden(title, desc):
    assert not filters.check_role(title, desc, "startup", CFG)[0]


def test_boutique_m_and_a_is_not_retail():
    assert filters.check_role("Stage Analyste M&A - Boutique", "", "investment_bank", CFG)[0]


def test_four_month_top_role_shown_and_tagged():
    desc = ("<p>Stage de 4 mois à partir de mai 2027. Modélisation financière, "
            "valorisation, due diligence, notes d'investissement pour le comité "
            "d'investissement, aux côtés des associés.</p>") * 3
    d, why = process(_offer(company="Ardian", title="Stage Analyste Private Equity",
                            company_type="other", description_html=desc), CFG, REF)
    assert d, why
    assert any("4 months" in t and "longer than 3" in t for t in d["tags"])


def test_four_month_ordinary_role_still_hidden():
    d, why = process(_offer(title="Sales Intern",
                            description_html="<p>Stage de 4 mois à partir de mai 2027.</p>"),
                     CFG, REF)
    assert d is None and why.startswith("duration")


def test_six_month_top_role_still_hidden():
    desc = "<p>Stage de 6 mois. Modélisation financière, valorisation, due diligence.</p>" * 3
    d, why = process(_offer(company="Ardian", title="Stage Private Equity",
                            company_type="other", description_html=desc), CFG, REF)
    assert d is None and why.startswith("duration")
