import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, List, Optional, Pattern, Tuple

import requests

sys.path.append('../../shared')
import challenge_builder as mrcb

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, *args, **kwargs):
        return iterable


@dataclass
class DateCandidate:
    precision: int
    year: int
    month: Optional[int]
    day: Optional[int]
    normalized: str


@dataclass
class HistoryInfo:
    tag_key: Optional[str]
    tag_value: Optional[str]
    name_value: Optional[str]
    last_timestamp: Optional[datetime]


DATE_PATTERNS: List[Tuple[Pattern, Callable[[re.Match], Optional[DateCandidate]]]] = []


def _valid_month(value: int) -> Optional[int]:
    if 1 <= value <= 12:
        return value
    return None


def _valid_day(value: int) -> Optional[int]:
    if 1 <= value <= 31:
        return value
    return None


def _build_candidate(year: int, month: Optional[int] = None, day: Optional[int] = None) -> Optional[DateCandidate]:
    month = _valid_month(month) if month is not None else None
    day = _valid_day(day) if day is not None else None
    if day is not None and month is None:
        return None
    precision = 1
    if month is not None:
        precision += 1
        if day is not None:
            precision += 1
    normalized = f"{year:04d}"
    if month is not None:
        normalized += f"-{month:02d}"
        if day is not None:
            normalized += f"-{day:02d}"
    return DateCandidate(precision, year, month, day, normalized)


def _parse_ymd(match: re.Match) -> Optional[DateCandidate]:
    return _build_candidate(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _parse_ym(match: re.Match) -> Optional[DateCandidate]:
    return _build_candidate(int(match.group(1)), int(match.group(2)))


def _parse_dmy4(match: re.Match) -> Optional[DateCandidate]:
    return _build_candidate(int(match.group(3)), int(match.group(2)), int(match.group(1)))


def _parse_dmy2(match: re.Match) -> Optional[DateCandidate]:
    year = int(match.group(3)) + 2000
    return _build_candidate(year, int(match.group(2)), int(match.group(1)))


def _parse_my4(match: re.Match) -> Optional[DateCandidate]:
    return _build_candidate(int(match.group(2)), int(match.group(1)))


def _parse_year(match: re.Match) -> Optional[DateCandidate]:
    return _build_candidate(int(match.group(1)))


DATE_PATTERNS.extend([
    (re.compile(r'\b(\d{4})[.\-/ ](\d{2})[.\-/ ](\d{2})\b'), _parse_ymd),
    (re.compile(r'\b(\d{4})[.\-/ ](\d{2})\b'), _parse_ym),
    (re.compile(r'\b(\d{2})[.\-/](\d{2})[.\-/](\d{4})\b'), _parse_dmy4),
    (re.compile(r'\b(\d{2})[.\-/](\d{2})[.\-/](\d{2})\b'), _parse_dmy2),
    (re.compile(r'\b(\d{2})[.\-/](\d{4})\b'), _parse_my4),
    (re.compile(r'\b(\d{4})\b'), _parse_year),
])


FALLBACK_INTRO = """Dieses Objekt enthält nur einen einzelnen `note`-Tag, der darauf hinweist, dass hier etwas abgerissen wurde.

Ein Objekt sollte nicht nur einen einzelnen `note`-Tag haben, sondern Tags, die das Objekt beschreiben.

Löse das Problem auf eine der folgenden Weisen:"""

FALLBACK_PART1 = """1. 🏗️ Wenn auf einem der verfügbaren Luftbilder das abgerissene Objekt noch zu sehen ist:
   - Wenn es ein Gebäude ist, dann füge `razed:building=yes` hinzu
   - Du kannst natürlich auch gerne eine genauere Beschreibung hinzufügen, wenn ersichtlich ist, was es früher war. Z.B. `razed:building=garages` oder `razed:building=apartments`
   - Wenn die Note einen Hinweis darauf enthält, wann das Gebäude abgerissen wurde, kannst du es mittels `end_date=*` angeben, z.B. `end_date=2024-05`"""

FALLBACK_PART2 = """2. 🗑️ Wenn auf KEINEM der verfügbaren Luftbilder das Objekt zu sehen ist:
   - Lösche das Objekt."""

NO_TAGFIX_MESSAGE = "⚠️ Für dieses Objekt stehen keine TagFix-Vorschläge zur Verfügung; bitte überspringe es."

FIVE_YEARS = timedelta(days=365 * 5)


def needs_task(element: dict) -> bool:
    return len(element.get("tags", {})) == 1


def extract_date_candidates(text: str) -> List[DateCandidate]:
    candidates: List[DateCandidate] = []
    for pattern, parser in DATE_PATTERNS:
        for match in pattern.finditer(text):
            candidate = parser(match)
            if candidate:
                candidates.append(candidate)
    return candidates


def _is_better(candidate: DateCandidate, current: Optional[DateCandidate]) -> bool:
    if current is None:
        return True
    current_tuple = (current.precision, current.year, current.month or 0, current.day or 0)
    candidate_tuple = (candidate.precision, candidate.year, candidate.month or 0, candidate.day or 0)
    return candidate_tuple > current_tuple


def find_best_date_from_tags(tags: dict) -> Optional[DateCandidate]:
    best: Optional[DateCandidate] = None
    for key, value in tags.items():
        for text in (key, value):
            if not isinstance(text, str):
                continue
            for candidate in extract_date_candidates(text):
                if _is_better(candidate, best):
                    best = candidate
    return best


def _parse_osm_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if value.endswith('Z'):
        value = value[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def fetch_history_info(osm_type: str, osm_id: int) -> HistoryInfo:
    url = f"https://api.openstreetmap.org/api/0.6/{osm_type}/{osm_id}/history.json"
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException:
        return HistoryInfo(None, None, None)

    if response.status_code != 200:
        return HistoryInfo(None, None, None)
    try:
        payload = response.json()
    except ValueError:
        return HistoryInfo(None, None, None)

    versions = payload.get("elements", [])
    name_value: Optional[str] = None
    for version in reversed(versions):
        tags = version.get("tags") or {}
        if name_value is None and "name" in tags:
            name_value = tags["name"]

    history_tag_key: Optional[str] = None
    history_tag_value: Optional[str] = None
    for version in reversed(versions):
        tags = version.get("tags") or {}
        building = tags.get("building")
        if building:
            history_tag_key = "building"
            history_tag_value = building
            break
        highway = tags.get("highway")
        if highway:
            history_tag_key = "highway"
            history_tag_value = highway
            break

    last_timestamp: Optional[datetime] = None
    for version in reversed(versions):
        ts = _parse_osm_timestamp(version.get("timestamp"))
        if ts:
            last_timestamp = ts
            break

    return HistoryInfo(history_tag_key, history_tag_value, name_value, last_timestamp)


def should_show_deletion_hint(last_timestamp: Optional[datetime]) -> bool:
    if not last_timestamp:
        return False
    now = datetime.now(timezone.utc)
    if last_timestamp.tzinfo is None:
        last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)
    return (now - last_timestamp) > FIVE_YEARS


def build_instruction_text(history_info: HistoryInfo, date_candidate: Optional[DateCandidate], show_deletion_hint: bool) -> str:
    tag_key = history_info.tag_key
    tag_value = history_info.tag_value
    if not tag_value:
        text = [FALLBACK_INTRO, "", NO_TAGFIX_MESSAGE, "", FALLBACK_PART1]
        if show_deletion_hint:
            text.append("")
            text.append(FALLBACK_PART2)
        return "\n".join(text)

    lines = [
        "📝 Dieses Objekt enthält nur einen einzigen `note`-Tag, der darauf hinweist, dass hier etwas abgerissen wurde.",
        "",
        "Bitte prüfe die angezeigten Vorschläge anhand der verfügbaren Luftbilder, bevor du bestätigst:",
        ""
    ]

    if tag_key:
        lines.append(f"🏗️ Die Historie nennt zuletzt `{tag_key}={tag_value}`; bestätige oder verbessere `razed:building={tag_value}`.")
    if date_candidate:
        lines.append(f"📅 In den Tags wurde der Zeitpunkt `{date_candidate.normalized}` erkannt; bestätige oder korrigiere `end_date={date_candidate.normalized}`.")

    if show_deletion_hint:
        lines.append("")
        lines.append("🗑️ Wenn auf KEINEM der verfügbaren Luftbilder das Objekt noch zu erkennen ist (und die letzte Bearbeitung länger als fünf Jahre zurückliegt), entferne das Element.")

    return "\n".join(lines)


def build_tagfix(osm_type: str, osm_id: int, history_info: HistoryInfo, date_candidate: Optional[DateCandidate]) -> Optional[mrcb.TagFix]:
    if not history_info.tag_value:
        return None
    tags_to_set = {
        "razed:building": history_info.tag_value
    }
    if date_candidate:
        tags_to_set["end_date"] = date_candidate.normalized
    return mrcb.TagFix(osm_type, osm_id, tags_to_set)


def build_main_feature(element: dict, instruction_text: str) -> mrcb.GeoFeature:
    geometry = mrcb.getElementCenterPoint(element)
    properties = {
        "task_instruction": instruction_text,
    }
    return mrcb.GeoFeature.withId(element["type"], element["id"], geometry, properties)


def main():
    overpass = mrcb.Overpass()
    print("Fetching elements from Overpass...")
    elements = overpass.getElementsFromQuery(
        """
[out:json][timeout:250];
area(id:3600051477)->.searchArea;
nwr["note"~"bgerissen"](if:count_tags()==1)(area.searchArea);
out tags center;
        """
    )

    challenge = mrcb.Challenge()

    for element in tqdm(elements):
        if not needs_task(element):
            continue

        date_candidate = find_best_date_from_tags(element.get("tags", {}))
        history_info = fetch_history_info(element["type"], element["id"])

        instruction_text = build_instruction_text(
            history_info,
            date_candidate,
            should_show_deletion_hint(history_info.last_timestamp)
        )

        feature = build_main_feature(element, instruction_text)
        cooperative = build_tagfix(element["type"], element["id"], history_info, date_candidate)
        if cooperative:
            task = mrcb.Task(feature, cooperativeWork=cooperative)
        else:
            task = mrcb.Task(feature)

        challenge.addTask(task)

    print("Saving challenge...")
    challenge.saveToFile("note_abgerissen.json")


if __name__ == "__main__":
    main()
