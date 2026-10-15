import pytest

from harness.reply import positions


def one(text):
    found = positions(text)
    assert len(found) == 1, found
    return found[0]


def test_sexagesimal_ra_and_dec():
    ra, dec = one('The camera points at RA 01h 20m 00s, Dec +83° 00\' 00".')
    assert ra == [pytest.approx(20.0)] and dec == pytest.approx(83.0)


def test_negative_declination_applies_to_the_whole_value():
    assert one("RA 10h 30m, Dec -12° 30' 00\"")[1] == pytest.approx(-12.5)


def test_decimal_degrees_with_units():
    ra, dec = one("RA: 20.04°, Dec: +83.01°")
    assert ra == [pytest.approx(20.04)] and dec == pytest.approx(83.01)


def test_decimal_hours():
    assert one("Right ascension 1.336 h, declination 83.0 degrees")[0] == [pytest.approx(20.04)]


def test_colon_form():
    ra, dec = one("RA 01:20:00 Dec +83:00:00")
    assert ra == [pytest.approx(20.0)] and dec == pytest.approx(83.0)


def test_a_bare_ra_is_read_both_ways():
    ra, _ = one("RA 20.0, Dec 83.0")
    assert sorted(ra) == [pytest.approx(20.0), pytest.approx(300.0)]
    assert one("RA 100.0, Dec 83.0")[0] == [pytest.approx(100.0)]  # too big for hours


def test_markdown_and_unicode_minus():
    text = "**RA:** 5h 35m 17s\n**Dec:** −5° 23′ 14″"
    ra, dec = one(text)
    assert ra == [pytest.approx(83.82, abs=0.01)] and dec == pytest.approx(-5.387, abs=0.001)


def test_several_positions_are_all_returned_in_order():
    found = positions("Mount reports RA 1h 25m, Dec +81°. The plate solve gives RA 1h 20m, Dec +83°.")
    assert [round(dec) for _, dec in found] == [81, 83]


@pytest.mark.parametrize("text", [None, "", "I could not solve the frame.", "RA unknown, Dec unknown", "Dec 95.0 RA 3h"])
def test_no_position_when_there_is_none(text):
    assert positions(text) == []
