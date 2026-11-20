"""Check a reply's chart claims against the chart the app sent. Pure code, no AI: the eval's grader only
lists the claims, this file decides if each one is true.

    chart = parse_chart(app_data_text)
    check_claims(chart, [{"kind": "dignity", "planet": "புதன்", "dignity": "ஆட்சி"}])
    -> [("wrong", "புதன் is not ஆட்சி in ரிஷபம்")]

Reads AstroTamil's chart text (RASI CHART / NAVAMSAM / DASA / BHUKTI / TODAY'S TRANSIT blocks, as in
scripts/evals/jothidar_karthik.json). A claim this file cannot check comes back "unchecked", never "wrong".
"""
import re
from dataclasses import dataclass, field
from datetime import date

SIGNS = ["மேஷம்", "ரிஷபம்", "மிதுனம்", "கடகம்", "சிம்மம்", "கன்னி",
         "துலாம்", "விருச்சிகம்", "தனுசு", "மகரம்", "கும்பம்", "மீனம்"]
SIGN_LORD = dict(zip(SIGNS, ["செவ்வாய்", "சுக்கிரன்", "புதன்", "சந்திரன்", "சூரியன்", "புதன்",
                             "சுக்கிரன்", "செவ்வாய்", "குரு", "சனி", "சனி", "குரு"]))
# Classical exaltation signs; debilitation is the opposite sign. ராகு/கேது left out (texts disagree).
EXALTED = {"சூரியன்": "மேஷம்", "சந்திரன்": "ரிஷபம்", "செவ்வாய்": "மகரம்", "புதன்": "கன்னி",
           "குரு": "கடகம்", "சுக்கிரன்": "மீனம்", "சனி": "துலாம்"}
PLANETS = ["சூரியன்", "சந்திரன்", "செவ்வாய்", "புதன்", "குரு", "சுக்கிரன்", "சனி", "ராகு", "கேது"]

_PLANET_ALIASES = {
    "sun": "சூரியன்", "moon": "சந்திரன்", "mars": "செவ்வாய்", "mercury": "புதன்", "jupiter": "குரு",
    "venus": "சுக்கிரன்", "saturn": "சனி", "rahu": "ராகு", "ketu": "கேது",
    "சுக்ரன்": "சுக்கிரன்", "சுக்கிர": "சுக்கிரன்", "வியாழன்": "குரு", "சந்திர": "சந்திரன்", "சூரிய": "சூரியன்",
}
_SIGN_ALIASES = {
    "aries": "மேஷம்", "taurus": "ரிஷபம்", "gemini": "மிதுனம்", "cancer": "கடகம்", "leo": "சிம்மம்",
    "virgo": "கன்னி", "libra": "துலாம்", "scorpio": "விருச்சிகம்", "sagittarius": "தனுசு",
    "capricorn": "மகரம்", "aquarius": "கும்பம்", "pisces": "மீனம்",
}
_DATE = r"(\d{2})-(\d{2})-(\d{4})"


def _prefix(v: str, names: list[str]) -> str | None:
    """A name with a case ending ('சனியின்', 'ரிஷபத்தில்') -> the name; the full name is tried first, then
    the name minus its last letter (5+ code points only, so short names like சனி never match loosely)."""
    return (next((n for n in names if v.startswith(n)), None)
            or next((n for n in names if len(n) >= 5 and v.startswith(n[:-2])), None))


def planet_name(value) -> str | None:
    """'Venus' / 'சுக்ரன்' / 'சுக்கிரன்' -> 'சுக்கிரன்'; unknown -> None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v in PLANETS:
        return v
    return _PLANET_ALIASES.get(v.lower()) or _prefix(v, PLANETS)


def sign_name(value) -> str | None:
    """'Taurus' / 'ரிஷப' / 'ரிஷபம்' -> 'ரிஷபம்'; unknown -> None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v in SIGNS:
        return v
    return _SIGN_ALIASES.get(v.lower()) or _prefix(v, SIGNS)


@dataclass
class Period:
    planet: str
    start: date
    end: date | None


@dataclass
class Chart:
    lagna: str | None = None                                  # sign of house 1
    rasi: str | None = None                                   # the Moon sign
    d1: dict[str, str] = field(default_factory=dict)          # planet -> sign
    d9: dict[str, str] = field(default_factory=dict)          # planet -> navamsa sign
    transit: dict[str, str] = field(default_factory=dict)     # planet -> sign today
    dasa: Period | None = None
    next_dasa: Period | None = None
    bhuktis: list[Period] = field(default_factory=list)       # current first, then the listed next ones

    def house_sign(self, house: int, origin: str = "lagnam") -> str | None:
        base = self.rasi if origin == "rasi" else self.lagna
        if base is None or not 1 <= house <= 12:
            return None
        return SIGNS[(SIGNS.index(base) + house - 1) % 12]

    def house_of(self, sign: str, origin: str = "lagnam") -> int | None:
        base = self.rasi if origin == "rasi" else self.lagna
        return None if base is None else (SIGNS.index(sign) - SIGNS.index(base)) % 12 + 1


def _d(m) -> date:
    return date(int(m[2]), int(m[1]), int(m[0]))


def _section(text: str, title: str) -> str:
    """The lines under a heading, up to the next blank line."""
    m = re.search(rf"^{re.escape(title)}[^\n]*\n(.*?)(?:\n\s*\n|\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def parse_chart(text: str) -> Chart:
    c = Chart()
    if m := re.search(r"Lagnam:\s*(\S+)", text):
        c.lagna = sign_name(m.group(1))
    if m := re.search(r"^Rasi:\s*(\S+)", text, re.M):
        c.rasi = sign_name(m.group(1))
    for line in _section(text, "RASI CHART").splitlines():
        if m := re.match(r"\s*(\d{1,2})\s+(\S+)\s+–\s+(.*)", line):
            sign = sign_name(m.group(2))
            for raw in re.split(r"[,،]", m.group(3)):
                p = planet_name(re.sub(r"\(.*?\)|–", "", raw).strip())
                if p and sign:
                    c.d1[p] = sign
    for p, s in re.findall(r"(\S+)\s+–\s+(\S+)", _section(text, "NAVAMSAM")):
        if planet_name(p) and sign_name(s):
            c.d9[planet_name(p)] = sign_name(s)
    for p, s in re.findall(r"(\S+)\s+–\s+(\S+)", _section(text, "TODAY'S TRANSIT")):
        if planet_name(p) and sign_name(s):
            c.transit[planet_name(p)] = sign_name(s)
    if m := re.search(rf"Current Dasa:\s*(\S+)\s+தசை\s*\({_DATE}\s+to\s+{_DATE}\)", text):
        c.dasa = Period(planet_name(m.group(1)), _d(m.groups()[1:4]), _d(m.groups()[4:7]))
    if m := re.search(rf"Current Bhukti:\s*(\S+)\s+புத்தி\s*\({_DATE}\s+to\s+{_DATE}\)", text):
        c.bhuktis.append(Period(planet_name(m.group(1)), _d(m.groups()[1:4]), _d(m.groups()[4:7])))
    for m in re.finditer(rf"•\s*(\S+)\s+புத்தி\s+{_DATE}\s+to\s+{_DATE}", text):
        c.bhuktis.append(Period(planet_name(m.group(1)), _d(m.groups()[1:4]), _d(m.groups()[4:7])))
    if m := re.search(rf"Next Dasa:\s*(\S+)\s+தசை\s+from\s+{_DATE}", text):
        c.next_dasa = Period(planet_name(m.group(1)), _d(m.groups()[1:4]), None)
    return c


def _month(value) -> tuple[int, int | None] | None:
    """'2027-05' -> (2027, 5); '2028' (only a year said) -> (2028, None)."""
    m = re.fullmatch(r"\s*(\d{4})(?:-(\d{1,2}))?\s*", str(value)) if value is not None else None
    return (int(m[1]), int(m[2]) if m[2] else None) if m else None


def _n(year: int, month: int) -> int:
    return year * 12 + month


def _near(claimed: tuple[int, int | None], actual: date, months: int = 1) -> bool:
    """Same month (one month either way); a year-only claim matches the same year."""
    if claimed[1] is None:
        return claimed[0] == actual.year
    return abs(_n(*claimed) - _n(actual.year, actual.month)) <= months


def _inside(claimed: tuple[int, int | None], period: "Period", months: int = 1) -> bool:
    """A predicted window month lies inside the period (one month slack each side)."""
    lo = _n(period.start.year, period.start.month) - months
    hi = _n(period.end.year, period.end.month) + months if period.end else 10 ** 9
    if claimed[1] is None:
        return lo // 12 <= claimed[0] <= hi // 12
    return lo <= _n(*claimed) <= hi


def _check_period(c: Chart, cl: dict) -> tuple[str, str]:
    planet, level, when = planet_name(cl.get("planet")), cl.get("level"), cl.get("when")
    start, end = _month(cl.get("start")), _month(cl.get("end"))
    window = [w for w in (_month(cl.get("window_start")), _month(cl.get("window_end"))) if w]
    if not planet or level not in ("dasa", "bhukti"):
        return "unchecked", "unreadable period claim"
    word = "தசை" if level == "dasa" else "புத்தி"
    if level == "dasa":
        if when == "current" or (when is None and c.dasa and planet == c.dasa.planet):
            if not c.dasa:
                return "unchecked", "no dasa in chart"
            if planet != c.dasa.planet:
                return "wrong", f"running dasa is {c.dasa.planet} தசை, not {planet} தசை"
            period = c.dasa
        elif when == "next" and c.next_dasa and planet != c.next_dasa.planet:
            return "wrong", f"next dasa is {c.next_dasa.planet} தசை, not {planet} தசை"
        elif c.next_dasa and planet == c.next_dasa.planet:
            period = c.next_dasa
        else:
            return "unchecked", f"{planet} தசை is not in the chart's list"
    else:
        if when == "current":
            if not c.bhuktis:
                return "unchecked", "no bhukti in chart"
            if planet != c.bhuktis[0].planet:
                return "wrong", f"running bhukti is {c.bhuktis[0].planet} புத்தி, not {planet} புத்தி"
        found = [b for b in c.bhuktis if b.planet == planet]
        if not found:
            listed_to = c.bhuktis[-1].end if c.bhuktis else None
            first = start or (window[0] if window else None)
            if listed_to and first and _n(first[0], first[1] or 1) < _n(listed_to.year, listed_to.month):
                return "wrong", f"no {planet} புத்தி before {listed_to:%m-%Y}"
            return "unchecked", f"{planet} புத்தி is not in the chart's list"
        period = found[0]
    if start and not _near(start, period.start):
        return "wrong", f"{planet} {word} starts {period.start:%m-%Y}, not {_show(start)}"
    if end and period.end and not _near(end, period.end):
        return "wrong", f"{planet} {word} ends {period.end:%m-%Y}, not {_show(end)}"
    for w in window:
        if not _inside(w, period):
            to = f"{period.end:%m-%Y}" if period.end else "on"
            return "wrong", f"window {_show(w)} is outside {planet} {word} ({period.start:%m-%Y} to {to})"
    return "ok", ""


def _show(m: tuple[int, int | None]) -> str:
    return str(m[0]) if m[1] is None else f"{m[1]:02d}-{m[0]}"


def check_claim(c: Chart, cl: dict) -> tuple[str, str]:
    """One claim -> ("ok" | "wrong" | "unchecked", reason)."""
    kind = cl.get("kind")
    origin = "rasi" if cl.get("from") == "rasi" else "lagnam"
    if kind == "house_sign":
        house, sign = cl.get("house"), sign_name(cl.get("sign"))
        actual = c.house_sign(house, origin) if isinstance(house, int) else None
        if not actual or not sign:
            return "unchecked", "unreadable house claim"
        return ("ok", "") if sign == actual else ("wrong", f"house {house} is {actual}, not {sign}")
    if kind == "lord":
        house, planet = cl.get("house"), planet_name(cl.get("planet"))
        actual = c.house_sign(house, origin) if isinstance(house, int) else None
        if not actual or not planet:
            return "unchecked", "unreadable lord claim"
        lord = SIGN_LORD[actual]
        return ("ok", "") if planet == lord else ("wrong", f"lord of house {house} is {lord}, not {planet}")
    if kind == "position":
        planet, chart_name = planet_name(cl.get("planet")), cl.get("chart") or "D1"
        table = {"D1": c.d1, "D9": c.d9, "transit": c.transit}.get(chart_name, {})
        actual = table.get(planet) if planet else None
        if not actual:
            return "unchecked", f"no {chart_name} position for {cl.get('planet')}"
        sign, house = sign_name(cl.get("sign")), cl.get("house")
        if sign and sign != actual:
            return "wrong", f"{planet} is in {actual} ({chart_name}), not {sign}"
        if isinstance(house, int) and chart_name != "D9":
            real = c.house_of(actual, origin)
            if real is not None and real != house:
                where = "from ராசி" if origin == "rasi" else "from லக்னம்"
                return "wrong", f"{planet} is in house {real} {where} ({chart_name}), not {house}"
        return "ok", ""
    if kind == "dignity":
        planet, dignity = planet_name(cl.get("planet")), cl.get("dignity")
        sign = (c.d9 if cl.get("chart") == "D9" else c.d1).get(planet) if planet else None
        if not sign or planet not in EXALTED or dignity not in ("ஆட்சி", "உச்சம்", "நீசம்"):
            return "unchecked", "dignity not checkable"
        own = [s for s, lord in SIGN_LORD.items() if lord == planet]
        exalted = EXALTED[planet]
        debilitated = SIGNS[(SIGNS.index(exalted) + 6) % 12]
        true = {"ஆட்சி": sign in own, "உச்சம்": sign == exalted, "நீசம்": sign == debilitated}[dignity]
        return ("ok", "") if true else ("wrong", f"{planet} is not {dignity} in {sign}")
    if kind == "period":
        return _check_period(c, cl)
    return "unchecked", f"unknown claim kind {kind!r}"


def check_claims(c: Chart, claims) -> list[tuple[str, str]]:
    return [check_claim(c, cl) if isinstance(cl, dict) else ("unchecked", "not a claim") for cl in claims or []]


# The claim list the grader is asked for (pasted into its prompt).
CLAIMS_SPEC = """claims = every fact the reply states about THIS chart, as a list (empty if none). Not general rules
("7ம் அதிபதி பலம் இருந்தால்..."), only statements about this person's chart. One object per fact:
  {"kind": "house_sign", "house": 12, "sign": "மேஷம்"}                      house 12 is மேஷம்
  {"kind": "lord", "house": 6, "planet": "சுக்கிரன்"}                         the 6th lord is சுக்கிரன்
  {"kind": "position", "planet": "புதன்", "house": 1, "sign": null, "chart": "D1"}   புதன் sits in house 1
  {"kind": "dignity", "planet": "புதன்", "dignity": "ஆட்சி", "chart": "D1"}   ஆட்சி / உச்சம் / நீசம்
  {"kind": "period", "level": "dasa" or "bhukti", "planet": "சுக்கிரன்", "when": "current" / "next" / "later",
   "start": "2027-05" or null, "end": "2028-07" or null,
   "window_start": "2027-06" or null, "window_end": "2028-02" or null}       a dasa/bhukti and its months
start/end = only when the reply says when the PERIOD ITSELF starts or ends ("ஜூன் 2029 வரை செவ்வாய் தசை").
window_start/window_end = a time the reply PREDICTS inside that period ("சுக்கிர புத்தியில 2027 ஜூன் முதல்
2028 பிப்ரவரிக்குள்ள கல்யாணம்"). Only a year said ("2028-ல") -> "2028", never invent a month.
chart is "D1" (ராசி கட்டம்), "D9" (நவாம்சம்) or "transit" (கோசாரம், today). Add "from": "rasi" when the
reply counts the house from ராசி (ராசிக்கு 12ல்) instead of லக்னம். Planet and sign names in Tamil, spelled:
சூரியன் சந்திரன் செவ்வாய் புதன் குரு சுக்கிரன் சனி ராகு கேது / மேஷம் ரிஷபம் மிதுனம் கடகம் சிம்மம் கன்னி
துலாம் விருச்சிகம் தனுசு மகரம் கும்பம் மீனம்."""
