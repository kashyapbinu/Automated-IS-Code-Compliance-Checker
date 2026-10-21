"""Parsers for the notations used on Indian RCC drawings (M25, Fe500, 4-16 dia, T10@150 c/c, 50d ...)."""
import math
import re
from typing import Optional, Tuple

STANDARD_BAR_DIAS = {6, 8, 10, 12, 16, 20, 25, 28, 32, 36, 40}

_NUM = r"(\d+(?:\.\d+)?)"


def first_number(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    m = re.search(_NUM, str(text))
    return float(m.group(1)) if m else None


def concrete_grade(text: Optional[str]) -> Optional[int]:
    """'M25' / 'M 25' / 'M-25' -> 25. Takes the first grade when several are listed."""
    if not text:
        return None
    m = re.search(r"\bM\s*-?\s*(\d{2})\b", str(text), re.IGNORECASE)
    return int(m.group(1)) if m else None


def steel_grade(text: Optional[str]) -> Optional[int]:
    """'Fe 500D' / 'Fe500' / 'HYSD 415' -> 500 / 415."""
    if not text:
        return None
    m = re.search(r"Fe\s*-?\s*(\d{3})", str(text), re.IGNORECASE) or re.search(r"\b(250|415|500|550|600)\b", str(text))
    return int(m.group(1)) if m else None


def length_mm(text: Optional[str]) -> Optional[float]:
    """Length in mm from '50 mm', '0.05 m', '5 cm', '2\'-6"' or a bare number (assumed mm)."""
    if not text:
        return None
    s = str(text).lower().replace(",", "")
    ft_in = re.search(r"(\d+)\s*['’]\s*-?\s*(\d+(?:\.\d+)?)?\s*(?:\"|”|in)?", s)
    if ft_in:
        feet = float(ft_in.group(1))
        inches = float(ft_in.group(2) or 0)
        return round((feet * 12 + inches) * 25.4, 1)
    m = re.search(_NUM + r"\s*(mm|cm|m|in|\")?", s)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    factor = {"mm": 1, "cm": 10, "m": 1000, "in": 25.4, '"': 25.4}.get(unit, 1)
    return round(value * factor, 1)


def multiple_of_d(text: Optional[str]) -> Optional[float]:
    """'50d' / '50 x dia' / '50 times bar diameter' -> 50."""
    if not text:
        return None
    m = re.search(_NUM + r"\s*(?:x|times|×)?\s*(?:d\b|dia|ø|φ|bar dia)", str(text), re.IGNORECASE)
    return float(m.group(1)) if m else None


def bar_set(text: Optional[str]) -> Optional[Tuple[int, int]]:
    """'4-16 dia' / '4#16' / '4 nos 16ø' / '3 Y16' / '4T16' -> (count, dia)."""
    if not text:
        return None
    m = re.search(
        r"(\d+)\s*(?:nos\.?|no\.?|numbers)?\s*[-#x×]?\s*(?:[TYØφ#]|dia\.?|mm)?\s*-?\s*(\d{1,2})\s*(?:mm)?\s*(?:dia|ø|φ|#|tor|tmt)?",
        str(text),
        re.IGNORECASE,
    )
    if not m:
        return None
    count, dia = int(m.group(1)), int(m.group(2))
    if dia not in STANDARD_BAR_DIAS:
        return None
    return count, dia


def bar_spacing(text: Optional[str]) -> Optional[Tuple[Optional[int], Optional[float]]]:
    """'T10@150 c/c' / '10 dia @ 150' / '8ø-200' -> (dia, spacing_mm)."""
    if not text:
        return None
    m = re.search(r"(?:[TYØφ#]\s*)?(\d{1,2})\s*(?:mm)?\s*(?:dia\.?|ø|φ|#|tor)?\s*(?:@|-|at)\s*" + _NUM, str(text), re.IGNORECASE)
    if not m:
        return None
    dia = int(m.group(1))
    return (dia if dia in STANDARD_BAR_DIAS else None), float(m.group(2))


def section_mm(text: Optional[str]) -> Optional[Tuple[float, float]]:
    """'230 x 450' / '300X600 mm' -> (230, 450)."""
    if not text:
        return None
    m = re.search(_NUM + r"\s*(?:mm)?\s*[x×X\*]\s*" + _NUM, str(text))
    return (float(m.group(1)), float(m.group(2))) if m else None


def bar_area(dia_mm: float) -> float:
    return math.pi * dia_mm**2 / 4
