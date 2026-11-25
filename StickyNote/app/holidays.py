"""Korean public holidays (관공서 공휴일, the "red days" on the calendar).

    on(day)        holidays on that day (a list, usually empty or one)
    in_year(year)  {day: [Holiday, ...]} for the whole year

Rules (공휴일에 관한 법률 / 관공서의 공휴일에 관한 규정):
* Fixed days: 1/1, 3·1절, 노동절 (2026-), 어린이날, 현충일, 제헌절 (-2007, 2026-),
  광복절, 개천절, 한글날 (-1990, 2013-), 기독탄신일, 식목일 (-2005).
* Lunar days: 설날 and 추석 with the day before and after, 부처님오신날.
* Substitute days (대체공휴일), on the first weekday after that is not a holiday:
  - 설날 / 추석 holidays that fall on a Sunday or on another holiday (from 2014),
  - 어린이날 on a weekend or another holiday (from 2014),
  - 3·1절, 광복절, 개천절, 한글날 likewise (from 2021),
  - 부처님오신날, 기독탄신일 likewise (from 2023), 노동절, 제헌절 (from 2026).
  One substitute day per overlapping day.
* Election days and one-off holidays are listed in SPECIAL. New ones the
  government declares later have to be added there.

LUNAR holds the solar dates of 설날, 부처님오신날 and 추석, taken from the
Korean lunisolar calendar (.NET KoreanLunisolarCalendar, KASI data) and
checked against the official 2023-2027 lists. Years outside it get only the
fixed holidays.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

#       year: (설날, 부처님오신날, 추석) as MMDD
LUNAR = {
    1990: ("0127", "0502", "1003"), 1991: ("0215", "0521", "0922"), 1992: ("0204", "0510", "0911"),
    1993: ("0123", "0528", "0930"), 1994: ("0210", "0518", "0920"), 1995: ("0131", "0507", "0909"),
    1996: ("0219", "0524", "0927"), 1997: ("0208", "0514", "0916"), 1998: ("0128", "0503", "1005"),
    1999: ("0216", "0522", "0924"), 2000: ("0205", "0511", "0912"), 2001: ("0124", "0501", "1001"),
    2002: ("0212", "0519", "0921"), 2003: ("0201", "0508", "0911"), 2004: ("0122", "0526", "0928"),
    2005: ("0209", "0515", "0918"), 2006: ("0129", "0505", "1006"), 2007: ("0218", "0524", "0925"),
    2008: ("0207", "0512", "0914"), 2009: ("0126", "0502", "1003"), 2010: ("0214", "0521", "0922"),
    2011: ("0203", "0510", "0912"), 2012: ("0123", "0528", "0930"), 2013: ("0210", "0517", "0919"),
    2014: ("0131", "0506", "0908"), 2015: ("0219", "0525", "0927"), 2016: ("0208", "0514", "0915"),
    2017: ("0128", "0503", "1004"), 2018: ("0216", "0522", "0924"), 2019: ("0205", "0512", "0913"),
    2020: ("0125", "0430", "1001"), 2021: ("0212", "0519", "0921"), 2022: ("0201", "0508", "0910"),
    2023: ("0122", "0527", "0929"), 2024: ("0210", "0515", "0917"), 2025: ("0129", "0505", "1006"),
    2026: ("0217", "0524", "0925"), 2027: ("0207", "0513", "0915"), 2028: ("0127", "0502", "1003"),
    2029: ("0213", "0520", "0922"), 2030: ("0203", "0509", "0912"), 2031: ("0123", "0528", "1001"),
    2032: ("0211", "0516", "0919"), 2033: ("0131", "0506", "0908"), 2034: ("0219", "0525", "0927"),
    2035: ("0208", "0515", "0916"), 2036: ("0128", "0503", "1004"), 2037: ("0215", "0522", "0924"),
    2038: ("0204", "0511", "0913"), 2039: ("0124", "0430", "1002"), 2040: ("0212", "0518", "0921"),
    2041: ("0201", "0507", "0910"), 2042: ("0122", "0526", "0928"), 2043: ("0210", "0516", "0917"),
    2044: ("0130", "0505", "1005"), 2045: ("0217", "0524", "0925"), 2046: ("0206", "0513", "0915"),
    2047: ("0126", "0502", "1004"), 2048: ("0214", "0520", "0922"), 2049: ("0202", "0509", "0911"),
    2050: ("0123", "0528", "0930"),
}

# Election days and one-off holidays: day -> (key, number of the election or None)
SPECIAL = {
    "2017-05-09": ("presidential_election", 19), "2017-10-02": ("temporary", None),
    "2018-06-13": ("local_election", 7), "2020-04-15": ("general_election", 21),
    "2020-08-17": ("temporary", None), "2022-03-09": ("presidential_election", 20),
    "2022-06-01": ("local_election", 8), "2023-10-02": ("temporary", None),
    "2024-04-10": ("general_election", 22), "2024-10-01": ("temporary", None),
    "2025-01-27": ("temporary", None), "2025-06-03": ("presidential_election", 21),
    "2026-06-03": ("local_election", 9),
    "2028-04-12": ("general_election", 23),     # fixed by the election law (공직선거법 34조)
}

NATIONAL = {"march_first", "constitution", "liberation", "foundation", "hangul"}     # 국경일


@dataclass(frozen=True)
class Holiday:
    day: date
    key: str                        # what it is: "chuseok", "liberation", "substitute", ...
    kind: str                       # "national", "public", "substitute", "election", "temporary"
    number: int | None = None       # which election (9 = the 9th)
    replaces: Holiday | None = None  # for a substitute day: the holiday it stands in for


def on(day: date) -> list[Holiday]:
    return list(in_year(day.year).get(day, ()))


@lru_cache(maxsize=None)
def _year(year: int) -> dict:
    days: dict[date, list[Holiday]] = {}

    def add(day, key, kind=None, number=None):
        kind = kind or ("national" if key in NATIONAL else "public")
        days.setdefault(day, []).append(Holiday(day, key, kind, number))

    add(date(year, 1, 1), "new_year")
    lunar = LUNAR.get(year)
    seollal = buddha = chuseok = None
    if lunar:
        seollal, buddha, chuseok = (date(year, int(x[:2]), int(x[2:])) for x in lunar)
        for day, key in ((seollal - timedelta(1), "seollal_eve"), (seollal, "seollal"),
                         (seollal + timedelta(1), "seollal_after")):
            add(day, key)
    add(date(year, 3, 1), "march_first")
    if year <= 2005:
        add(date(year, 4, 5), "arbor")
    if year >= 2026:
        add(date(year, 5, 1), "labor")
    add(date(year, 5, 5), "children")
    if buddha:
        add(buddha, "buddha")
    add(date(year, 6, 6), "memorial")
    if year <= 2007 or year >= 2026:
        add(date(year, 7, 17), "constitution")
    add(date(year, 8, 15), "liberation")
    if chuseok:
        for day, key in ((chuseok - timedelta(1), "chuseok_eve"), (chuseok, "chuseok"),
                         (chuseok + timedelta(1), "chuseok_after")):
            add(day, key)
    add(date(year, 10, 3), "foundation")
    if year <= 1990 or year >= 2013:
        add(date(year, 10, 9), "hangul")
    add(date(year, 12, 25), "christmas")
    for iso, (key, number) in SPECIAL.items():
        if iso.startswith(f"{year}-"):
            add(date.fromisoformat(iso), key, "election" if number else "temporary", number)

    for start, end, trigger in _overlaps(year, days, seollal, chuseok):
        day = end + timedelta(1)
        while day.weekday() >= 5 or day in days:
            day += timedelta(1)
        days[day] = [Holiday(day, "substitute", "substitute", replaces=trigger)]
    return {day: tuple(hs) for day, hs in sorted(days.items())}


def _overlaps(year, days, seollal, chuseok):
    """(first day, last day, holiday) for every holiday that earns a substitute day."""
    if year < 2014:
        return []
    weekend = {"children"}
    if year >= 2021:
        weekend |= {"march_first", "liberation", "foundation", "hangul"}
    if year >= 2023:
        weekend |= {"buddha", "christmas"}
    if year >= 2026:
        weekend |= {"labor", "constitution"}
    found = []
    for center in (seollal, chuseok):           # three-day holidays: Sunday or another holiday
        if center is None:
            continue
        span = [center + timedelta(i) for i in (-1, 0, 1)]
        hit = next((d for d in span if d.weekday() == 6 or len(days[d]) > 1), None)
        if hit is not None:
            own = next(h for h in days[hit] if h.key.startswith(("seollal", "chuseok")))
            found.append((span[0], span[-1], own))
    taken = {h.day for _, _, h in found}
    for day, hs in sorted(days.items()):        # one-day holidays: weekend or another holiday
        if day in taken:
            continue
        h = next((h for h in hs if h.key in weekend), None)
        if h and (day.weekday() >= 5 or len(hs) > 1):
            found.append((day, day, h))
    return sorted(found, key=lambda f: f[1])


def in_year(year: int) -> dict:
    return {day: list(hs) for day, hs in _year(year).items()}
