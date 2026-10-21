import pytest

from src import units


@pytest.mark.parametrize("text,expected", [("M25", 25), ("M 20 grade", 20), ("M-30 for columns, M25 slabs", 30), ("RCC", None)])
def test_concrete_grade(text, expected):
    assert units.concrete_grade(text) == expected


@pytest.mark.parametrize("text,expected", [("Fe 500D TMT", 500), ("Fe415", 415), ("HYSD bars 500", 500), ("TMT", None)])
def test_steel_grade(text, expected):
    assert units.steel_grade(text) == expected


@pytest.mark.parametrize("text,expected", [("50 mm", 50), ("5 cm", 50), ("0.15 m", 150), ("40", 40), ("2'-6\"", 762.0)])
def test_length_mm(text, expected):
    assert units.length_mm(text) == pytest.approx(expected)


@pytest.mark.parametrize("text,expected", [("50d", 50), ("47 x dia", 47), ("50 times bar diameter", 50), ("600 mm", None)])
def test_multiple_of_d(text, expected):
    assert units.multiple_of_d(text) == expected


@pytest.mark.parametrize("text,expected", [("4-16 dia", (4, 16)), ("4#16", (4, 16)), ("3 nos 12 dia", (3, 12)), ("4T20", (4, 20))])
def test_bar_set(text, expected):
    assert units.bar_set(text) == expected


@pytest.mark.parametrize("text,expected", [("T10@150 c/c", (10, 150)), ("8 dia @ 200", (8, 200)), ("12ø-125", (12, 125))])
def test_bar_spacing(text, expected):
    assert units.bar_spacing(text) == expected


def test_section_mm():
    assert units.section_mm("230 x 450") == (230, 450)
    assert units.section_mm("300X600 mm") == (300, 600)
    assert units.section_mm("no size") is None
