from datetime import date

import pytest

from scanner.parsing import (parse_deadline, parse_duration, parse_pay, parse_start,
                             start_compatible)

REF = date(2026, 11, 13)


# ------------------------------------------------------------- duration
@pytest.mark.parametrize("text,lo,hi", [
    ("Stage de 6 mois à partir de janvier 2027", 6, 6),
    ("Durée : 3 mois", 3, 3),
    ("Durée du stage : trois mois", 3, 3),
    ("Stage de 4 à 6 mois", 4, 6),
    ("stage de 2 à 3 mois", 2, 3),
    ("Internship duration: 2-3 months", 2, 3),
    ("3 to 6 months internship", 3, 6),
    ("a 6-month internship", 6, 6),
    ("We offer a 12-week summer internship", 2.8, 2.8),
    ("Stage de 10 semaines", 2.3, 2.3),
    ("Six months internship", 6, 6),
    ("Praktikum für 3 Monate", 3, 3),
    ("stage d'un an", 12, 12),
    ("Durée : 3 mois. 2 ans d'expérience souhaités", 3, 3),
])
def test_duration_stated(text, lo, hi):
    d = parse_duration(text)
    assert d.min_months == pytest.approx(lo, abs=0.1)
    assert d.max_months == pytest.approx(hi, abs=0.1)


@pytest.mark.parametrize("text", [
    "Vous avez au moins 6 mois d'expérience en vente",
    "You have 6 months of experience in sales",
    "For the first 3 months you will shadow our team",
    "Chiffre d'affaires multiplié par 3 en 12 mois après le lancement",
    "We raised 20M€ two years ago",
    "",
])
def test_duration_not_stated(text):
    assert not parse_duration(text).stated


def test_cesure_and_end_of_studies_flags():
    assert parse_duration("Stage de césure").long_flags
    assert parse_duration("Gap year internship").long_flags
    assert parse_duration("Stage de fin d'études").end_of_studies
    assert parse_duration("End-of-studies internship").end_of_studies


# ------------------------------------------------------------- start date
@pytest.mark.parametrize("text,title,expected", [
    ("Début : avril 2027", "", [date(2027, 4, 1)]),
    ("Date de début : 04/05/2027", "", [date(2027, 5, 4)]),
    ("à partir du 1er mai 2027", "", [date(2027, 5, 1)]),
    ("Starting date: May 2027", "", [date(2027, 5, 1)]),
    ("Start date: June 1, 2027", "", [date(2027, 6, 1)]),
    ("starting on 2027-05-10", "", [date(2027, 5, 10)]),
    ("Disponibilité : septembre 2027", "", [date(2027, 9, 1)]),
    ("dès janvier ou juillet 2027", "", [date(2027, 1, 1), date(2027, 7, 1)]),
    ("", "Stage Business Developer - Juin 2027 (3 mois)", [date(2027, 6, 1)]),
    ("", "Summer Internship 2027 - Sales", [date(2027, 6, 15)]),
    ("Stage à pourvoir à partir de mai", "", [date(2027, 5, 1)]),   # year inferred
])
def test_start(text, title, expected):
    assert parse_start(text, title, REF).candidates == expected


def test_start_asap_uses_posting_date():
    s = parse_start("Start: ASAP", "", REF)
    assert s.asap and s.candidates == [REF]
    s = parse_start("Poste à pourvoir dès que possible", "", REF)
    assert s.asap


def test_english_may_modal_is_not_a_month():
    assert parse_start("You may join us from our Paris office", "", REF).candidates == []


def test_start_compatibility():
    lo, hi = date(2027, 4, 20), date(2027, 6, 30)
    ok = lambda t, ti="": start_compatible(parse_start(t, ti, REF), lo, hi)  # noqa: E731
    assert ok("Début : mai 2027") is True
    assert ok("Début : avril 2027") is True          # late April is part of April
    assert ok("Début : mars 2027") is False
    assert ok("Start: September 2027") is False
    assert ok("Start: ASAP") is False                 # posted in Nov 2026
    assert ok("No date here") is None
    assert ok("dès janvier ou juillet 2027") is False
    assert ok("dès mai ou septembre 2027") is True


# ------------------------------------------------------------- deadline
def test_deadline():
    assert parse_deadline("Date limite de candidature : 15/02/2027", REF) == date(2027, 2, 15)
    assert parse_deadline("Apply by March 1, 2027", REF) == date(2027, 3, 1)
    assert parse_deadline("Postulez avant le 10 janvier 2027", REF) == date(2027, 1, 10)
    assert parse_deadline("No deadline mentioned", REF) is None


# ------------------------------------------------------------- pay
@pytest.mark.parametrize("text,lo,hi", [
    ("Gratification : 1 200 € / mois", 1200, 1200),
    ("Salary: €1,500 per month", 1500, 1500),
    ("Rémunération : 1000-1300€", 1000, 1300),
    ("stipend of EUR 1.400 gross monthly", 1400, 1400),
    ("Rémunération : 4,35 €/h", 670, 670),
    ("compensation €30k per year", 2500, 2500),
    ("Pay: 900€ brut mensuel", 900, 900),
])
def test_pay(text, lo, hi):
    p = parse_pay(text)
    assert (p.monthly_min, p.monthly_max) == (lo, hi)


def test_pay_ignores_funding_and_unrelated_amounts():
    assert not parse_pay("Nous avons levé 15 M€ en 2024").stated
    assert not parse_pay("A 2 000 € budget for training").stated   # no pay keyword


def test_pay_legal_minimum_and_structured():
    assert parse_pay("Gratification légale").legal_minimum
    assert parse_pay("", "€1.2K – €1.5K per month").monthly_min == 1200
