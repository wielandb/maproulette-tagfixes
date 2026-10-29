"""Suggest missing pizza/kebab cuisine values for human review in MapRoulette."""

import argparse
import math
from pathlib import Path
import re
import sys
from urllib.parse import quote, urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from shared import challenge_builder as mrcb
from shared.geofabrik import download_germany, iter_pbf_elements


DEFAULT_CACHE_DIR = SCRIPT_DIR.parents[1] / ".cache" / "geofabrik"
DEFAULT_OUTPUT = SCRIPT_DIR / "cuisine_from_name.json"
NAME_RULES = (
    ("kebab", re.compile(r"döner|doener|doner|kebab|kebap", re.IGNORECASE)),
    ("pizza", re.compile(r"pizza|pizzeria", re.IGNORECASE)),
)
PIZZA_ALIASES = {"pizza", "italian_pizza"}
LIFECYCLE_PREFIXES = (
    "disused", "abandoned", "demolished", "razed", "removed", "destroyed",
    "construction", "proposed", "planned", "was",
)
INACTIVE_VALUES = {"no", "false", "0", ""}


def is_active(tags):
    for prefix in LIFECYCLE_PREFIXES:
        flag = tags.get(prefix)
        if isinstance(flag, str) and flag.strip().casefold() not in INACTIVE_VALUES:
            return False
        if any(f"{prefix}:{key}" in tags for key in ("amenity", "name", "cuisine")):
            return False
    return True


def matching_name_parts(tags):
    name = tags.get("name")
    if not isinstance(name, str):
        return {}
    return {value: match.group(0) for value, pattern in NAME_RULES
            if (match := pattern.search(name))}


def propose_changes(tags):
    """Return an additive cuisine TagFix, or None when no safe change exists."""
    if tags.get("amenity") not in {"fast_food", "restaurant"} or not is_active(tags):
        return None
    matches = matching_name_parts(tags)
    if not matches:
        return None
    current = tags.get("cuisine", "")
    if not isinstance(current, str):
        return None
    # Preserve spelling, ordering and spacing. Broken lists need manual repair.
    if current.strip():
        parts = [part.strip().casefold() for part in current.split(";")]
        if any(not part or "," in part for part in parts):
            return None
        existing = set(parts)
    else:
        existing = set()
    additions = []
    for cuisine in matches:
        covered = bool(existing & PIZZA_ALIASES) if cuisine == "pizza" else cuisine in existing
        if not covered:
            additions.append(cuisine)
    if not additions:
        return None
    proposed = ";".join(([current] if current.strip() else []) + additions)
    return {"cuisine": proposed}


def validate_bbox(bbox):
    if bbox is None:
        return None
    if len(bbox) != 4 or any(isinstance(value, bool) or not isinstance(value, (int, float))
                             or not math.isfinite(value) for value in bbox):
        raise ValueError("Bounding box must contain four finite coordinates: south west north east")
    south, west, north, east = bbox
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("Bounding box must be south west north east within valid coordinates")
    return tuple(bbox)


def inline_code(value):
    value = str(value).replace("\r", " ").replace("\n", " ").replace("|", "\\|")
    longest = max((len(match.group()) for match in re.finditer(r"`+", value)), default=0)
    delimiter = "`" * (longest + 1)
    return f"{delimiter} {value} {delimiter}"


def source_link(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return None
    return quote(url, safe=":/?#[]@!$&'*,;=%+-._~")


def build_instruction(element, changes):
    tags = element["tags"]
    matches = matching_name_parts(tags)
    evidence = ", ".join(f"{inline_code(part)} → {inline_code(cuisine)}"
                         for cuisine, part in matches.items())
    old_value = inline_code(tags["cuisine"]) if "cuisine" in tags else "fehlt"
    osm_url = f"https://www.openstreetmap.org/{element['type']}/{element['id']}"
    lines = [
        f"## Küchenangebot von {inline_code(tags['name'])} prüfen",
        "",
        f"Der Name enthält folgende Hinweise: {evidence}.",
        "Der Vorschlag wurde ausschließlich aus dem Namen abgeleitet und muss geprüft werden.",
        "",
        "| Tag | Bisher | Vorschlag |",
        "| --- | --- | --- |",
        f"| cuisine | {old_value} | {inline_code(changes['cuisine'])} |",
        "",
        "Vorhandene Küchenwerte bleiben erhalten; fehlende Werte werden ergänzt. "
        "Ein vorhandenes `italian_pizza` erfüllt den Pizza-Hinweis bereits.",
        "",
        "Prüfe, ob der Betrieb aktuell ist und die genannten Speisen tatsächlich anbietet. "
        "Bestätige mit **Ja**, wenn der vollständige Vorschlag passt; korrigiere ihn andernfalls "
        "im Editor oder wähle **Nein**. Bei Unsicherheit überspringe die Aufgabe.",
        "",
        "Quellen zur Prüfung:",
        f"- [Aktuelles OSM-Objekt]({osm_url})",
    ]
    if element.get("pbf_source"):
        stamp = element.get("pbf_timestamp") or "im PBF-Header nicht angegeben"
        lines.append(f"- PBF-Quelle: {inline_code(element['pbf_source'])}; Datenstand: {inline_code(stamp)}. "
                     "Tags und Kartenposition stammen aus diesem Extrakt und können inzwischen geändert sein.")
    for key, label in (("website:menu", "Speisekarte"), ("website", "Website"),
                       ("contact:website", "Kontakt-Website")):
        if (url := source_link(tags.get(key))):
            lines.append(f"- [{label}]({url})")
    lines.extend([
        "- [Dokumentation zu cuisine](https://wiki.openstreetmap.org/wiki/Key:cuisine)",
        "- [Ursprüngliche O-sus-M-Idee](https://haukauntrie.de/projekte/osusm)",
    ])
    return "\n".join(lines)


def build_task(element):
    tags = element.get("tags", {})
    changes = propose_changes(tags)
    if changes is None:
        return None
    if element.get("type") not in {"node", "way", "relation"}:
        raise ValueError("Unsupported OSM element type")
    osm_id = element.get("id")
    if isinstance(osm_id, bool) or not isinstance(osm_id, int) or osm_id <= 0:
        raise ValueError("Invalid OSM ID")
    center = mrcb.getElementCenterPoint(dict(element))
    lon, lat = center
    if (any(isinstance(value, bool) or not math.isfinite(value) for value in center)
            or not (-180 <= lon <= 180 and -90 <= lat <= 90)):
        raise ValueError("Invalid OSM center coordinates")
    feature = mrcb.GeoFeature.withId(element["type"], osm_id, center, {
        "name": tags["name"],
        "old_cuisine": tags.get("cuisine", ""),
        "suggested_cuisine": changes["cuisine"],
        "task_instruction": build_instruction(element, changes),
    })
    return mrcb.Task(feature, cooperativeWork=mrcb.TagFix(element["type"], osm_id, changes))


def main(output_file=None, bbox=None, max_tasks=None, pbf=None, cache_dir=None):
    bbox = validate_bbox(bbox)
    challenge = mrcb.Challenge(max_tasks=max_tasks)
    if pbf is None:
        cache = Path(cache_dir).resolve() if cache_dir is not None else DEFAULT_CACHE_DIR
        cache.mkdir(parents=True, exist_ok=True)
        path = download_germany(cache)
    else:
        path = Path(pbf).resolve()
    elements = iter(iter_pbf_elements(
        path, tag_keys=("amenity",),
        predicate=lambda tags: propose_changes(tags) is not None, bbox=bbox,
    ))
    try:
        # Check the cap before next(): do not continue scanning the PBF once the
        # task or byte budget has been reached.
        while not challenge.limit_reached:
            try:
                element = next(elements)
            except StopIteration:
                break
            try:
                task = build_task(element)
            except (KeyError, TypeError, ValueError) as exc:
                print(f"Skipping {element.get('type')}/{element.get('id')}: {exc}")
                continue
            if task is not None and not challenge.addTask(task):
                break
    finally:
        close = getattr(elements, "close", None)
        if close is not None:
            close()
    destination = Path(output_file).resolve() if output_file is not None else DEFAULT_OUTPUT
    destination.parent.mkdir(parents=True, exist_ok=True)
    challenge.saveToFile(destination)
    print(f"Saved {len(challenge.tasks)} cuisine tasks to {destination}")
    return challenge


def cli(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, help="Use an existing Geofabrik PBF instead of downloading Germany.")
    parser.add_argument("--cache-dir", type=Path, help="Download cache; defaults to repository .cache/geofabrik.")
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"),
                        help="Filter PBF object centres locally; can be combined with --pbf.")
    parser.add_argument("--output", type=Path, help="Write the JSON sequence to this file.")
    parser.add_argument("--max-tasks", type=int, help="Generate a smaller sample (maximum 50,000).")
    args = parser.parse_args(argv)
    try:
        main(output_file=args.output, bbox=args.bbox, max_tasks=args.max_tasks,
             pbf=args.pbf, cache_dir=args.cache_dir)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    cli()
