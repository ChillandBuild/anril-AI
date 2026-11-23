"""Check a reply's chart claims against the chart the app sent. Pure code, no AI.

Two users:
- the eval: its grader lists the claims, check_claims decides if each one is true.
      chart = parse_chart(app_data_text)
      check_claims(chart, [{"kind": "dignity", "planet": "புதன்", "dignity": "ஆட்சி"}])
      -> [("wrong", "புதன் is not ஆட்சி in ரிஷபம்")]
- the live reply check (chart guard, engine.py): find_wrong(chart, reply) finds the claims itself, by code.
      find_wrong(parse_app_data(app_data), "Sani Mithunathil aatchi")
      -> ["சனி is not ஆட்சி in மிதுனம் (சனி rules மகரம், கும்பம்)"]

Reads AstroTamil's chart text (RASI CHART / NAVAMSAM / DASA / BHUKTI / TODAY'S TRANSIT blocks, as in
scripts/evals/jothidar_karthik.json) and its chart JSON (overview / planets / navamsa / dasa / gocharam, as in
prem-chart-astrotamil.json). A claim this file cannot check comes back "unchecked", never "wrong".
"""
import json
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
# Tanglish / English spellings as a stem + optional Tamil case ending: "Simmathil", "Guruvin", "Saniyal".
# A whole word must match, so "kumbabishekam" is not கும்பம். Built in _latin below.
_LATIN_PLANETS = {
    "சூரியன்": r"s[uo]+r[iy]+(?:y)?an|surya|sun", "சந்திரன்": r"[cs]h?an[dt]h?[iy]?ran|moon",
    "செவ்வாய்": r"[cs]h?evv?aa?i|angaragan|mars", "புதன்": r"bu[dt]h?an|mercury",
    "குரு": r"guru|vi[yz]a+[zl]h?an|jupiter", "சுக்கிரன்": r"s[hu]u?k+i?ran|venus",
    "சனி": r"s[h]?ani|saneeswaran|saturn", "ராகு": r"ra+[gh]?u|rahu", "கேது": r"ke[dt]h?u",
}
_LATIN_SIGNS = {
    "மேஷம்": r"mesh(?:am|a)?|aries", "ரிஷபம்": r"v?rish(?:a)?bh?(?:am|a)?|taurus",
    "மிதுனம்": r"mi[dt]h?un(?:am|a)?|gemini", "கடகம்": r"ka[dt]a?[gk](?:am|a)?|cancer",
    "சிம்மம்": r"simm?h?(?:am|a)|leo", "கன்னி": r"kanni|kanya|virgo", "துலாம்": r"th?ul(?:aa?m|a)|libra",
    "விருச்சிகம்": r"v[ir]+u?[sc]+h?i[gk](?:am|a)?|scorpio", "தனுசு": r"[dt]h?anus(?:u)?|[dt]h?anur|sagittarius",
    "மகரம்": r"ma[gk]ar(?:am|a)?|capricorn", "கும்பம்": r"kumbh?(?:am|a)|aquarius", "மீனம்": r"meen(?:am|a)|pisces",
}
_LATIN_ENDING = (r"(?:th?ila|th?il|th?ula|thla|il|yil|iyil|ukku|kku|vukku|ai|vai|in|vin|yin|iyin|al|aal|"
                 r"yal|iyal|oda|voda|ku|um|e|a|s)?")


def _latin(table: dict[str, str]) -> list[tuple[re.Pattern, str]]:
    return [(re.compile(rf"(?:{stem}){_LATIN_ENDING}", re.I), name) for name, stem in table.items()]


_LATIN_PLANET_RES, _LATIN_SIGN_RES = _latin(_LATIN_PLANETS), _latin(_LATIN_SIGNS)
_DATE = r"(\d{2})-(\d{2})-(\d{4})"


def _prefix(v: str, names: list[str], cut: int = 2) -> str | None:
    """A name with a case ending ('சனியின்', 'ரிஷபத்தில்') -> the name; the full name is tried first, then
    the name minus its last letter (5+ code points only, so short names like சனி never match loosely)."""
    return (next((n for n in names if v.startswith(n)), None)
            or next((n for n in names if len(n) >= 5 and v.startswith(n[:-cut])), None))


def planet_name(value) -> str | None:
    """'Venus' / 'சுக்ரன்' / 'சுக்கிரன்' -> 'சுக்கிரன்'; unknown -> None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if v in PLANETS:
        return v
    if "கிழமை" in v:            # சனிக்கிழமை = Saturday, not சனி
        return None
    return (_PLANET_ALIASES.get(v.lower()) or _prefix(v, PLANETS, cut=1)
            or next((n for r, n in _LATIN_PLANET_RES if r.fullmatch(v)), None))


def sign_name(value) -> str | None:
    """'Taurus' / 'ரிஷப' / 'ரிஷபம்' -> 'ரிஷபம்'; unknown -> None."""
    if not isinstance(value, str):
        return None
    v = re.sub(r"\s*\(.*?\)\s*", "", value).strip()      # "Magaram (Capricorn)" -> "Magaram"
    if v in SIGNS:
        return v
    return (_SIGN_ALIASES.get(v.lower()) or _prefix(v, SIGNS)
            or next((n for r, n in _LATIN_SIGN_RES if r.fullmatch(v)), None))


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
    d9_lagna: str | None = None
    moves: dict[str, set[str]] = field(default_factory=dict)  # planet -> signs it passes through this year
    dasas: list[Period] = field(default_factory=list)          # the whole dasa list, when the app sends it

    def empty(self) -> bool:
        return not (self.lagna or self.rasi or self.d1 or self.transit)

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
            if listed_to and first and (first[0] < listed_to.year if first[1] is None
                                        else _n(*first) < _n(listed_to.year, listed_to.month)):
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


# ---------------------------------------------------------------- AstroTamil chart JSON
_MON = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                                     "nov", "dec"], 1)}


def _loose_date(value) -> date | None:
    """'23 Jun 2026' / 'Jun 2044' / '2026' / '23-06-2026' -> a date (missing day/month = 1)."""
    v = str(value or "").strip().lower()
    if m := re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", v):
        return date(int(m[3]), int(m[2]), int(m[1]))
    if m := re.fullmatch(r"(?:(\d{1,2})\s+)?([a-z]{3})[a-z]*\.?\s+(\d{4})", v):
        return date(int(m[3]), _MON.get(m[2], 1), int(m[1] or 1)) if m[2] in _MON else None
    if m := re.fullmatch(r"(\d{4})", v):
        return date(int(m[1]), 1, 1)
    return None


def _get(d, *keys):
    """The first of keys present in dict d (keys compared lower-case)."""
    if not isinstance(d, dict):
        return None
    low = {str(k).lower(): v for k, v in d.items()}
    return next((low[k] for k in keys if k in low and low[k] not in (None, "")), None)


def _positions(rows) -> dict[str, str]:
    out = {}
    for row in rows if isinstance(rows, list) else []:
        p, s = planet_name(_get(row, "planet", "name", "graha")), sign_name(_get(row, "rasi", "sign", "rashi"))
        if p and s:
            out[p] = s
    return out


def parse_chart_json(data: dict) -> Chart:
    c = Chart()
    ov = _get(data, "overview", "summary") or data
    c.lagna = sign_name(_get(ov, "lagnam", "lagna", "ascendant"))
    c.rasi = sign_name(_get(ov, "rasi", "rashi", "moon_sign"))
    c.d1 = _positions(_get(data, "planets", "rasi_chart", "d1"))
    nav = _get(data, "navamsa", "navamsam", "d9")
    if isinstance(nav, dict):
        c.d9_lagna = sign_name(_get(nav, "lagnam", "lagna"))
        c.d9 = {planet_name(k): sign_name(v) for k, v in nav.items()
                if isinstance(v, str) and planet_name(k) and sign_name(v)}
    elif isinstance(nav, list):
        c.d9 = _positions(nav)
    goch = _get(data, "gocharam", "transit", "transits")
    if isinstance(goch, dict):
        c.transit = _positions(_get(goch, "planets_today", "planets", "today"))
        readings = _get(_get(goch, "month_readings") or {}, "readings") or []
        for r in readings if isinstance(readings, list) else []:
            p = planet_name(_get(r, "planet"))
            for move in _get(r, "moves_this_year") or []:
                for name in re.findall(r"[A-Za-z஀-௿]+", str(move)):
                    if p and sign_name(name):
                        c.moves.setdefault(p, set()).add(sign_name(name))
    elif isinstance(goch, list):
        c.transit = _positions(goch)
    dasa = _get(data, "dasa", "dasha") or {}
    for row in _get(dasa, "all", "list") or []:
        if isinstance(row, (list, tuple)) and len(row) >= 3 and planet_name(row[0]) and _loose_date(row[1]):
            c.dasas.append(Period(planet_name(row[0]), _loose_date(row[1]), _loose_date(row[2])))
    now = _get(dasa, "now", "current") or {}
    if p := planet_name(_get(now, "dasa", "planet")):
        start = _loose_date(_get(now, "from", "start"))
        c.dasa = Period(p, start, _loose_date(_get(now, "to", "end"))) if start else None
        later = [d for d in c.dasas if c.dasa and d.start > c.dasa.start]
        c.next_dasa = later[0] if later else None
    if (b := planet_name(_get(now, "bhukti"))) and (bs := _loose_date(_get(now, "bhukti_from"))):
        c.bhuktis.append(Period(b, bs, _loose_date(_get(now, "bhukti_to"))))
    return c


def parse_app_data(app_data) -> Chart:
    """The app's data as JSON or text -> Chart (empty when it is not a chart)."""
    if isinstance(app_data, dict):
        return parse_chart_json(app_data)
    try:
        parsed = json.loads(app_data or "")
    except (ValueError, TypeError):
        return parse_chart(app_data or "")
    return parse_chart_json(parsed) if isinstance(parsed, dict) else Chart()


# ---------------------------------------------------------------- live check: find claims in a reply by code
# Rule: a claim is "wrong" only when it matches NOTHING the chart gives (birth chart, today's transit,
# navamsa, this year's moves; house counted from lagnam or rasi). Anything unsure is skipped, because a
# false alarm costs a redo and maybe an astrologer handoff.
_CLAUSE_SPLIT = re.compile(r"[.!?।\n;]+|\s(?:but|however|ஆனால்|ஆனா|aanaa|aanal)\s", re.I)
_WORD_SPLIT = re.compile(r"[\s,:()\"'“”‘’–—/*]+")
_SKIP = re.compile(   # hypothetical, general, quoted, negated or future-movement clauses
    r"\b(?:if|when|whenever|suppose|generally|usually|example|said|mentioned|told|think|thought|not|no|"
    r"moves?|moved|moving|enters?|entered|entering|came|left|was|were|next\s+year|irundhar|irunthar|na|irundh?a|irunth?a|irundh?al|irunth?al|vandh?al|vanth?al|"
    r"amaindh?al|peyarchi|maarum|maaruvar|illa|illai|illanga|illaama|alla|sonn\w*|irukkuradh?u|irupp?adh?u|people|person|those|anyone|someone|natives?)\b|"
    r"பொதுவாக|உதாரண|இருந்தால்|இருப்பின்|அமைந்தால்|வந்தால்|நின்றால்|பெற்றால்|சென்றால்|இல்லை|இல்லா|அல்ல|"
    r"இல்ல|ில்லை|மாட்டா|போது|இருப்பது|இருப்பின்|அமர்வது|நிற்பது|ஒருவருக்கு|ந்தா(?=\s|,|$)|ந்தால்|வங்க(?=\s|,|$)|வர்கள்|வர்களுக்கு|நபர்|ஒருவர்|ஜாதகருக்கு|சொன்ன|சொல்லி|நினை|பெயர்ச்சி|மாறு|நுழை|இருந்தார்|அடுத்த\s*(?:ஆண்டு|வருட)", re.I)
_DIGNITY = {"ஆட்சி": r"ஆட்சி|aatchi|aatsi|own\s+(?:sign|house)|சொந்த\s*வீ", "உச்சம்": r"உச்ச|uchch?am|uchcha|exalted",
            "நீசம்": r"நீச|neech?am|neecha|debilitated"}
_LORD = re.compile(r"அதிபதி|athipathi|adhipathi|\blord\b|\bruler\b", re.I)
# A lord word that names the planet as lord ("7ம் அதிபதி சந்திரன்", "Sani is the 6th lord"), not
# "10ம் அதிபதியுடன்" (with the 10th lord).
_LORD_EXACT = re.compile(r"^(?:அதிபதி|அதிபதியான|அதிபதியாக|அதிபதியாகிய|athipathi|adhipathi|lord|ruler)$", re.I)
_ITS = re.compile(r"அதோட|அதன்|அதனுடைய|அதற்கு|\b(?:its|athoda|adhoda|athan|adhan)\b", re.I)
_NAVAMSA = re.compile(r"நவாம்ச|navams|navamsam|\bd9\b", re.I)
_YOUR = re.compile(r"\b(?:your|unga|ungal|ungaloda|unnoda|un)\b|உங்கள்|உங்க|உன்|உனது|தங்கள்", re.I)
_RASI_WORD = re.compile(r"^(?:ராசி|rasi|raasi|rashi|moon\s*sign)", re.I)
_LAGNA_WORD = re.compile(r"^(?:லக்ன|lagn|ascendant)", re.I)
_DASA_WORD = re.compile(r"^(?:தசை|திசை|dasa|dhasa|dasai|thasai|dasha|mahadasa)", re.I)
_BHUKTI_WORD = re.compile(r"^(?:புத்தி|புக்தி|bhukti|bhukthi|bukthi|antardasa)", re.I)
_NOW = re.compile(r"\b(?:now|current|currently|running|ippo|ippodhu|ipo|tharpodhu|nadappu|nadakkudhu|"
                  r"nadakkuthu)\b|இப்போது|இப்ப|தற்போது|நடப்பு|நடக்கிறது|நடந்து", re.I)   # not "நடக்கும்" (will happen)
_HOUSE_WORD = re.compile(r"^(?:house|bhava|veed|veet|vitt|வீ|இட|பாவ|ஸ்தான|sthan)", re.I)
_ORD_WORDS = {w: i for i, ws in enumerate([
    ("first", "ஒன்றாம்"), ("second", "இரண்டாம்"), ("third", "மூன்றாம்"), ("fourth", "நான்காம்"),
    ("fifth", "ஐந்தாம்"), ("sixth", "ஆறாம்"), ("seventh", "ஏழாம்"), ("eighth", "எட்டாம்"),
    ("ninth", "ஒன்பதாம்"), ("tenth", "பத்தாம்"), ("eleventh", "பதினொன்றாம்", "பதினோராம்"),
    ("twelfth", "பன்னிரண்டாம்")], 1) for w in ws}
_NUM = re.compile(r"(\d{1,2})(?:-?(st|nd|rd|th|ம்|ஆம்|வது|ஆவது|aam|am|vathu|avathu)|-?(ல்|இல்|il|la|ila))?$", re.I)
_DATIVE = re.compile(r"(?:க்கு|ukku|kku|vukku)$")


def _house(word: str, nxt: str) -> int | None:
    """'8ம் வீட்டில்' / '8th house' / '8ல்' / 'எட்டாம் இடம்' -> 8."""
    if (n := _ORD_WORDS.get(word.lower())) and _HOUSE_WORD.match(nxt):
        return n
    m = _NUM.fullmatch(word)
    if not m or not 1 <= int(m[1]) <= 12:
        return None
    return int(m[1]) if (m[3] or _HOUSE_WORD.match(nxt)) else None


def _mentions(clause: str) -> list[tuple[str, object, str]]:
    """Words in order as ("p", planet) / ("s", sign) / ("R"/"L", sign of rasi/lagnam) / ("h", house)
    / ("d"/"b", planet of a dasa/bhukti); the 3rd item is the raw word."""
    words = [w.strip(".-") for w in _WORD_SPLIT.split(clause) if w.strip(".-")]
    out = []
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else ""
        if (p := planet_name(w)) and _DASA_WORD.match(nxt):
            out.append(("d", p, w))
        elif p and _BHUKTI_WORD.match(nxt):
            out.append(("b", p, w))
        elif p:
            out.append(("p", p, w))
        elif (s := sign_name(w)) and (re.search(r"(?:க்கு|ukku|kku)$", w)
                                     or re.match(r"(?:ராசிக்கு|லக்னத்துக்கு|லக்னத்திற்கு|rasikku|raasikku|lagnathukku)", nxt, re.I)):
            continue   # "சிம்ம ராசிக்கு 8ல் சனி": the sign is where the count starts, not where சனி sits
        elif s:
            # "சிம்ம ராசி" (word after) or "your rasi is Kanni" (word before, maybe with "is" between)
            before = ([x for x in words[max(0, i - 2):i] if x.lower() not in ("is", "=", "-")][-1:] or [""])[0]
            bare = re.fullmatch(r"(?:ராசி|rasi|raasi|rashi|லக்னம்|lagnam|lagna)", nxt, re.I)
            if _RASI_WORD.fullmatch(before) or (bare and _RASI_WORD.match(nxt)):
                out.append(("R", s, w))
            elif re.fullmatch(r"(?:லக்னம்|lagnam|lagna|ascendant)", before, re.I) or (bare and _LAGNA_WORD.match(nxt)):
                out.append(("L", s, w))
            else:
                out.append(("s", s, w))
        elif (_LORD_EXACT.match(nxt) or (_HOUSE_WORD.match(nxt) and i + 2 < len(words) and _LORD_EXACT.match(words[i + 2]))) \
                and (_NUM.fullmatch(w) or w.lower() in _ORD_WORDS):
            n = int(_NUM.fullmatch(w)[1]) if _NUM.fullmatch(w) else _ORD_WORDS[w.lower()]
            if 1 <= n <= 12:
                out.append(("H", n, w))           # "7ம் அதிபதி": the 7th lord
        elif (h := _house(w, nxt)) is not None:
            out.append(("h", h, w))
    return out


def _rule_checks(c: Chart, clause: str, ms) -> list[tuple[str, str]]:
    """Dignity (true for everyone: "Sani aatchi in Mithunam" is wrong), sign lords, house lords
    ("7ம் அதிபதி சந்திரன்": house 7 from lagnam or from rasi must be ruled by சந்திரன்), and the sign of a
    house when no planet is named ("4ம் இடம் மேஷ ராசியில")."""
    out = []
    planets = [m[1] for m in ms if m[0] == "p"]
    signs = [m[1] for m in ms if m[0] in "sRL"]
    exact_lord = any(_LORD_EXACT.match(w) for w in _WORD_SPLIT.split(clause))
    if (len(set(planets)) == 1 and not signs and planets[0] in EXALTED
            and (any(m[0] == "h" for m in ms) or _YOUR.search(clause))):
        # "சனி 6ம் இடத்துலயே ஆட்சி பலத்தோட": the dignity of the planet where the chart puts it (birth or today)
        p = planets[0]
        where = {x for x in (c.d1.get(p), c.transit.get(p)) if x}
        for dignity, pat in _DIGNITY.items():
            if re.search(pat, clause, re.I) and where:
                results = [check_claim(Chart(d1={p: sg}), {"kind": "dignity", "planet": p, "dignity": dignity})
                           for sg in sorted(where)]
                out.append(("ok", "") if any(r[0] == "ok" for r in results) else
                           ("wrong", f"{p} is not {dignity}: the chart has it in {' / '.join(sorted(where))}"))
    if len(set(planets)) == 1 and signs:
        p = planets[0]
        for dignity, pat in _DIGNITY.items():
            if re.search(pat, clause, re.I) and p in EXALTED:
                for sg in signs:
                    out.append(check_claim(Chart(d1={p: sg}), {"kind": "dignity", "planet": p, "dignity": dignity}))
        # only the sign right before the lord word: "ராசி சிம்மம், அதிபதி சூரியன் விருச்சிகத்துல" checks சிம்மம்
        ruled = [m[1] for m in ms if m[0] in "sRL" and re.search(
            rf"{re.escape(m[2])}\S*\s+(?:(?:ராசி|rasi|லக்ன)\S*\s+)?(?:அதிபதி|athipathi|adhipathi)|lord\s+of\s+{re.escape(m[2])}",
            clause, re.I)]
        if exact_lord and not any(m[0] == "H" for m in ms):
            for sg in ruled:
                lord = SIGN_LORD[sg]
                out.append(("ok", "") if lord == p else ("wrong", f"the lord of {sg} is {lord}, not {p}"))
    for k, (kind, h, raw_h) in enumerate(ms):
        if kind != "H":
            continue
        nxt = ms[k + 1] if k + 1 < len(ms) and ms[k + 1][0] == "p" else None
        prv = ms[k - 1] if k > 0 and ms[k - 1][0] == "p" else None
        lord = r"(?:\S+\s+)?(?:அதிபதி|அதிபதியான|அதிபதியாக|athipathi|adhipathi|lord|ruler)"
        if nxt and not re.search(rf"{re.escape(raw_h)}\s+{lord}\s+(?:is\s+)?{re.escape(nxt[2])}", clause, re.I):
            nxt = None
        if prv and not re.search(rf"{re.escape(prv[2])}\s+(?:is\s+(?:the\s+|your\s+)?|(?:the|your)\s+)?{re.escape(raw_h)}", clause, re.I):
            prv = None
        if not (planet := (nxt or prv or (None, None))[1]):
            continue
        lords = {SIGN_LORD[x] for x in (c.house_sign(h), c.house_sign(h, "rasi")) if x}
        if lords:
            out.append(("ok", "") if planet in lords else
                       ("wrong", f"the lord of house {h} is {' / '.join(sorted(lords))}, not {planet}"))
    if not planets:
        for k, (kind, h, _) in enumerate(ms):
            if kind == "h" and k + 1 < len(ms) and ms[k + 1][0] == "s":
                sg, real = ms[k + 1][1], {x for x in (c.house_sign(h), c.house_sign(h, "rasi")) if x}
                if real:
                    out.append(("ok", "") if sg in real else
                               ("wrong", f"house {h} is {' / '.join(sorted(real))}, not {sg}"))
    return out


def _allowed_signs(c: Chart, p: str, navamsa: bool) -> set[str]:
    if navamsa:
        return {c.d9[p]} if p in c.d9 else set()
    # navamsa too: "Rahu Viruchigam" in the sentence after the one that said "navamsa"
    return {s for s in (c.d1.get(p), c.transit.get(p), c.d9.get(p)) if s} | c.moves.get(p, set())


def _allowed_houses(c: Chart, p: str) -> set[int]:
    out = set()
    for s in {s for s in (c.d1.get(p), c.transit.get(p)) if s}:     # not this year's moves: "Guru in 7th" now is false
        out |= {h for h in (c.house_of(s), c.house_of(s, "rasi")) if h}
    return out


def _period_checks(c: Chart, clause: str, ms) -> list[tuple[str, str]]:
    out = []
    for kind, p, _ in ms:
        if kind == "d" and _NOW.search(clause) and c.dasa:
            out.append(("ok", "") if p == c.dasa.planet else
                       ("wrong", f"the running dasa is {c.dasa.planet} தசை, not {p} தசை"))
        if kind == "b" and _NOW.search(clause) and c.bhuktis:
            out.append(("ok", "") if p == c.bhuktis[0].planet else
                       ("wrong", f"the running bhukti is {c.bhuktis[0].planet} புத்தி, not {p} புத்தி"))
    years = [int(y) for y in re.findall(r"(?<!\d)((?:19|20|21)\d{2})(?!\d)", clause)]
    periods = []
    for kind, p, _ in ms:
        pool = (c.dasas or [x for x in (c.dasa, c.next_dasa) if x]) if kind == "d" else c.bhuktis if kind == "b" else []
        found = [x for x in pool if x.planet == p]
        if kind in "db" and not found:
            return out          # a period the chart doesn't list: its years can't be checked
        periods += found
    if periods and years:
        for y in years:
            if not any(x.start.year - 1 <= y <= (x.end.year if x.end else 9999) + 1 for x in periods):
                names = ", ".join(f"{x.planet} {x.start:%Y}-{x.end:%Y}" if x.end else f"{x.planet} from {x.start:%Y}"
                                  for x in periods)
                out.append(("wrong", f"{y} is outside {names}"))
    return out


def find_claims(c: Chart, text: str) -> list[tuple[str, str]]:
    """Every chart claim the code can read in a reply -> [("ok" | "wrong", reason)]. Empty chart -> []."""
    if c.empty() or not text:
        return []
    out, last_house = [], None
    for clause in _CLAUSE_SPLIT.split(text):
        ms = _mentions(clause)
        if not ms:
            continue
        # "6ம் இடம் மிதுனத்தில். அதோட அதிபதி சனி" -> "its lord" is the 6th lord
        if (last_house and _ITS.search(clause) and not any(m[0] in "hH" for m in ms)
                and any(_LORD_EXACT.match(w) for w in _WORD_SPLIT.split(clause))):
            k = next((i for i, m in enumerate(ms) if m[0] == "p"), None)
            if k is not None:
                ms = ms[:k] + [("H", last_house, "its")] + ms[k:]
        last_house = next((m[1] for m in reversed(ms) if m[0] == "h"), last_house)
        if any(m[0] in "hHp" for m in ms):    # "10ம் இடம் துலாம் ராசி": a house's sign, not the person's rasi
            ms = [("s", m[1], m[2]) if m[0] in "RL" else m for m in ms]
        skip = bool(_SKIP.search(clause))
        if not skip:
            out += _rule_checks(c, clause, ms)
            out += _period_checks(c, clause, ms)
        if skip or _LORD.search(clause) or any(re.search(p, clause, re.I) for p in _DIGNITY.values()):
            continue
        navamsa = bool(_NAVAMSA.search(clause))
        if _YOUR.search(clause):           # "your rasi is Simmam" / "உங்கள் மகர லக்னம்"
            for kind, s, _ in ms:
                actual = c.rasi if kind == "R" else (c.d9_lagna if navamsa else c.lagna) if kind == "L" else None
                if kind in "RL" and actual:
                    out.append(("ok", "") if s == actual else
                               ("wrong", f"the {'rasi' if kind == 'R' else 'lagnam'} is {actual}, not {s}"))
        # planet groups: "Sun, Mercury and Venus in Viruchigam" -> one group of 3
        dative = any(k == "p" and _DATIVE.search(w) for k, _, w in ms)
        groups, i = [], 0
        while i < len(ms):
            if ms[i][0] == "p":
                j = i
                while j + 1 < len(ms) and ms[j + 1][0] == "p":
                    j += 1
                groups.append((i, j))
                i = j + 1
            else:
                i += 1
        used = set()
        for gi, (a, b) in enumerate(groups):
            target = None
            if b + 1 < len(ms) and ms[b + 1][0] in "sh" and b + 1 not in used:
                target = b + 1
            elif a > 0 and ms[a - 1][0] in "sh" and a - 1 not in used:
                target = a - 1
            if target is None:
                continue
            used.add(target)
            kind, value, _ = ms[target]
            for _, p, w in ms[a:b + 1]:
                if _DATIVE.search(w):
                    continue
                if kind == "s":
                    allowed = _allowed_signs(c, p, navamsa)
                    if allowed:
                        out.append(("ok", "") if value in allowed else ("wrong", _where(c, p, f"{p} in {value}")))
                elif not navamsa and not dative and len({m[1] for m in ms if m[0] == "p"}) == 1:
                    allowed = _allowed_houses(c, p)
                    if allowed:
                        out.append(("ok", "") if value in allowed else ("wrong", _where(c, p, f"{p} in house {value}")))
    return out


def _where(c: Chart, p: str, said: str) -> str:
    parts = []
    if p in c.d1:
        parts.append(f"birth chart {c.d1[p]} (house {c.house_of(c.d1[p])} from lagnam, "
                     f"{c.house_of(c.d1[p], 'rasi')} from rasi)")
    if p in c.transit:
        parts.append(f"today {c.transit[p]} (house {c.house_of(c.transit[p], 'rasi')} from rasi)")
    return f"reply says {said}; the chart has {p}: " + "; ".join(parts)


def find_wrong(c: Chart, text: str) -> list[str]:
    """Reasons for every claim in the reply that the chart contradicts (unique, in order)."""
    return list(dict.fromkeys(r for status, r in find_claims(c, text) if status == "wrong"))


def redo_note(wrong: list[str]) -> str:
    """The note added for the one redo."""
    lines = "\n".join(f"- {w}" for w in wrong[:6])
    return ("Your last draft stated chart facts that are not in APP DATA:\n" + lines +
            "\nWrite the reply again. Use only the positions, houses and periods written in APP DATA. "
            "If APP DATA does not give a fact, say you don't have it. Keep the same friendly tone.")
