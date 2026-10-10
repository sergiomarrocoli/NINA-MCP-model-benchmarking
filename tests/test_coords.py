from datetime import datetime, timezone

import pytest

from harness.coords import j2000_to_jnow, separation_deg

WHEN = datetime(2026, 10, 10, 18, 1, tzinfo=timezone.utc)


def test_m31_matches_what_nina_reported():
    # NINA's log: M31 at J2000 RA 0.712 h, Dec +41.27 became JNOW 00:44:13 / +41° 25' 11" (11.0549°, 41.4198°).
    ra, dec = j2000_to_jnow(0.712 * 15, 41.27, WHEN)
    assert ra == pytest.approx(11.0549, abs=0.02)
    assert dec == pytest.approx(41.4198, abs=0.02)


def test_no_change_at_j2000():
    j2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    assert j2000_to_jnow(83.8, -5.4, j2000) == pytest.approx((83.8, -5.4))


def test_ra_wraps_past_360():
    ra, _ = j2000_to_jnow(359.99, 10, WHEN)
    assert 0 <= ra < 360


def test_separation():
    assert separation_deg(10, 20, 10, 20) == pytest.approx(0)
    assert separation_deg(0, 0, 90, 0) == pytest.approx(90)
    assert separation_deg(0, 89, 180, 89) == pytest.approx(2)  # across the pole
