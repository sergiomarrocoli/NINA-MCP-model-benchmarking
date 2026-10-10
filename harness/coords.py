"""Convert catalogue (J2000) coordinates to what the mount reports (JNOW).

The Advanced API takes J2000 coordinates for slews, while mount info reports JNOW, so the two
differ by precession: about 0.37° in RA and 0.15° in Dec for M31 in 2026. Without this conversion a
mount that is exactly on target looks 0.4° off.

Rigorous enough for a few arc-minutes over decades (first-order precession at the mid-epoch),
which is far inside any tolerance a task needs.
"""
import math
from datetime import datetime, timezone

J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def _years_since_j2000(when: datetime) -> float:
    return (when - J2000).total_seconds() / (365.25 * 86400)


def j2000_to_jnow(ra_deg: float, dec_deg: float, when: datetime | None = None) -> tuple[float, float]:
    """Precess J2000 (RA, Dec) in degrees to the equinox of `when` (default now)."""
    years = _years_since_j2000(when or datetime.now(timezone.utc))
    t = years / 200  # centuries from 2000 at the middle of the interval
    m = 3.07496 + 0.00186 * t               # seconds of time per year
    n = 20.0431 - 0.0085 * t                # arc-seconds per year

    def shift(ra_rad: float, dec_rad: float) -> tuple[float, float]:
        """Total shift in degrees (RA, Dec) over the interval, with the rates taken at this position."""
        d_ra = (m + (n / 15) * math.sin(ra_rad) * math.tan(dec_rad)) * years * 15 / 3600
        d_dec = n * math.cos(ra_rad) * years / 3600
        return d_ra, d_dec

    ra, dec = math.radians(ra_deg), math.radians(dec_deg)
    d_ra, d_dec = shift(ra, dec)                                                     # rates at the start...
    d_ra, d_dec = shift(ra + math.radians(d_ra) / 2, dec + math.radians(d_dec) / 2)  # ...then at the middle
    return (ra_deg + d_ra) % 360, dec_deg + d_dec


def separation_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Angular distance in degrees between two (RA, Dec) positions given in degrees."""
    a1, d1, a2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    cos_sep = math.sin(d1) * math.sin(d2) + math.cos(d1) * math.cos(d2) * math.cos(a1 - a2)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos_sep))))
