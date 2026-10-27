"""Read the RA and Dec a model reports in its final reply, so a task can check them against the sky.

Models write positions as 01h 20m 00s / +83° 00' 00", as decimals with units (20.0°, 1.33 h), as 01:20:00, or as
bare numbers after a label ("RA 20.0, Dec 83.0"). A bare RA is read both as hours and as degrees, and either may match.
"""
import re

SIGN = r"[+\-−–]"
NUM = r"\d+(?:\.\d+)?"
RA_LABEL = re.compile(r"(?:\bRA\b|right ascension)[*_]*\s*(?:\([^)]*\))?\s*[:=|]?[*_\s]*(?:is|of|at|≈|~)?\s*", re.I)
DEC_LABEL = re.compile(r"(?:\bDec\b|declination)[*_]*\s*(?:\([^)]*\))?\s*[:=|]?[*_\s]*(?:is|of|at|≈|~)?\s*", re.I)

RA_HMS = re.compile(rf"({NUM})\s*h(?:ours?)?\s*(?:({NUM})\s*(?:m|′|')\s*(?:({NUM})\s*(?:s|″|\")?)?)?", re.I)
RA_COLON = re.compile(rf"(\d{{1,2}}):(\d{{1,2}})(?::({NUM}))?")
RA_DEG = re.compile(rf"({NUM})\s*(?:°|deg)", re.I)
BARE = re.compile(NUM)

DEC_DMS = re.compile(rf"({SIGN})?\s*(\d{{1,2}})\s*(?:°|d|deg)\s*(\d{{1,2}})\s*(?:′|'|m)\s*(?:({NUM})\s*(?:″|\"|s)?)?", re.I)
DEC_COLON = re.compile(rf"({SIGN})?\s*(\d{{1,2}}):(\d{{1,2}})(?::({NUM}))?")
DEC_DEC = re.compile(rf"({SIGN})?\s*({NUM})\s*(?:°|deg)?", re.I)


def _negative(sign: str | None) -> bool:
    return bool(sign) and sign in "-−–"


def _ra_options(text: str) -> list[float]:
    """Degrees this RA could mean, from the text just after an RA label."""
    for pattern in (RA_HMS, RA_COLON):
        m = pattern.match(text)
        if m:
            h, mi, s = (float(g) if g else 0.0 for g in m.groups())
            return [(h + mi / 60 + s / 3600) * 15]
    m = RA_DEG.match(text)
    if m:
        return [float(m.group(1))]
    m = BARE.match(text)
    if m:
        value = float(m.group())
        return [v for v in (value * 15 if value <= 24 else None, value if value <= 360 else None) if v is not None]
    return []


def _dec(text: str) -> float | None:
    for pattern in (DEC_DMS, DEC_COLON):
        m = pattern.match(text)
        if m:
            sign, d, mi, s = m.groups()
            value = float(d) + float(mi) / 60 + (float(s) / 3600 if s else 0.0)
            return -value if _negative(sign) else value
    m = DEC_DEC.match(text)
    if m:
        value = float(m.group(2))
        return -value if _negative(m.group(1)) else value
    return None


def positions(reply: str | None) -> list[tuple[list[float], float]]:
    """Every (possible RA values in degrees, Dec in degrees) pair in the reply, pairing the nth RA with the nth Dec."""
    text = reply or ""
    ras = [_ra_options(text[m.end():]) for m in RA_LABEL.finditer(text)]
    decs = [_dec(text[m.end():]) for m in DEC_LABEL.finditer(text)]
    return [(ra, dec) for ra, dec in zip(ras, decs) if ra and dec is not None and abs(dec) <= 90]
