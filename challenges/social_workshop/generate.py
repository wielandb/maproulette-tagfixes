"""Suggest social-facility tags for explicitly identified sheltered workshops."""

import argparse
import html
import math
from pathlib import Path
import re
import sys
import unicodedata
from urllib.parse import urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from shared import challenge_builder as mrcb

OUTPUT_FILE = SCRIPT_DIR / "social_workshop.json"
EVIDENCE_FIELDS = ("name", "description", "description:de")
COMPETING_KEYS = ("shop", "craft", "office", "healthcare", "leisure")
LIFECYCLE_PREFIXES = ("disused:", "abandoned:", "demolished:", "razed:", "removed:", "destroyed:", "construction:", "proposed:")
WORKSHOP_PATTERN = re.compile(r"werkst(?:a|ae)tt(?:e|en)?")
DISABILITY_PATTERN = re.compile(r"behinder\w*")
ABBREVIATION_PATTERN = re.compile(r"\bwfbm\b")
NOT_CURRENT_PATTERN = re.compile(r"\b(?:kein\w*|ehemalig\w*|ehemals|frueher|geschlossen|stillgelegt|leerstehend)\b")
THIRD_PARTY_PATTERN = re.compile(
    r"\b(?:gegenueber|neben(?:an)?|nahe|unweit|naehe|benachbart\w*)\b"
    r"[^.!?]{0,160}\b(?:[\w-]*werkst(?:a|ae)tt\w*|wfbm)\b"
)
OTHER_USE_PATTERN = re.compile(
    r"werkst(?:a|ae)tt(?:en)?(?:laden|shop|verkauf)|verwaltungs\w*|"
    r"\b(?:verwaltung|schule|kindergarten|wohnheim|tagespflege|tagesstaette|verkaufsstelle|laden|shop)\b"
)


def normalized_text(value):
    value = value.casefold().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    return "".join(char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char))


def workshop_evidence(tags):
    """Return a site-classification clue only after checking every field for conflicts."""
    if not isinstance(tags, dict):
        return None
    texts = [
        (key, original, normalized_text(original))
        for key in EVIDENCE_FIELDS
        if isinstance(original := tags.get(key), str) and original.strip()
    ]
    # A matching name cannot overrule evidence that the building now has another
    # use, or that the workshop mentioned in its description is somewhere else.
    if any(OTHER_USE_PATTERN.search(text) or NOT_CURRENT_PATTERN.search(text)
           or THIRD_PARTY_PATTERN.search(text) for _, _, text in texts):
        return None
    for key, original, text in texts:
        if ABBREVIATION_PATTERN.search(text) or (
            WORKSHOP_PATTERN.search(text) and DISABILITY_PATTERN.search(text)
        ):
            return key, original
    return None


def propose_changes(tags):
    """Return only missing/correctable tags, preserving other classifications."""
    if not workshop_evidence(tags):
        return None
    for key, value in tags.items():
        if not isinstance(key, str) or not isinstance(value, str):
            return None
        if key in ("disused", "abandoned", "demolished", "razed", "removed", "destroyed", "construction", "proposed") and value not in ("", "no"):
            return None
        if key.startswith(LIFECYCLE_PREFIXES) and value not in ("", "no"):
            return None
    if any(tags.get(key, "") not in ("", "no") for key in COMPETING_KEYS):
        return None
    if tags.get("amenity", "") not in ("", "workshop", "social_facility"):
        return None
    if tags.get("social_facility", "") not in ("", "workshop"):
        return None
    changes = {}
    if tags.get("amenity") != "social_facility":
        changes["amenity"] = "social_facility"
    if tags.get("social_facility") != "workshop":
        changes["social_facility"] = "workshop"
    if "social_facility:for" not in tags:
        changes["social_facility:for"] = "disabled"
    return changes or None


def validate_bbox(bbox):
    if bbox is None:
        return None
    if len(bbox) != 4 or any(isinstance(value, bool) for value in bbox):
        raise ValueError("bbox must contain SOUTH WEST NORTH EAST")
    try:
        south, west, north, east = map(float, bbox)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox must contain four finite coordinates") from exc
    if not all(math.isfinite(value) for value in (south, west, north, east)):
        raise ValueError("bbox must contain four finite coordinates")
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("bbox must satisfy -90 <= south < north <= 90 and -180 <= west < east <= 180")
    return south, west, north, east


def build_query(bbox=None):
    bbox = validate_bbox(bbox)
    selection = "area(id:3600051477)->.searchArea;\n" if bbox is None else ""
    area = "area.searchArea" if bbox is None else ",".join(str(value) for value in bbox)
    # Broad selection, followed by the same authoritative classifier for all fields.
    selectors = "\n".join(
        f'nwr["{key}"~"behin|wfbm",i]({area});' for key in EVIDENCE_FIELDS
    )
    return f"[out:json][timeout:250];\n{selection}(\n{selectors}\n);\nout tags center;"


def markdown_text(value):
    text = html.escape(str(value), quote=False).replace("\r", " ").replace("\n", " ")
    for char in ("\\", "`", "*", "_", "[", "]", "|", "~"):
        text = text.replace(char, "\\" + char)
    return text


def source_links(tags):
    links = []
    for key in ("website", "contact:website"):
        value = tags.get(key, "")
        try:
            parsed = urlsplit(value)
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            continue
        target = value.replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")
        links.append(f"[{key}](<{target}>)")
    return " · ".join(links)


def build_task(element):
    tags = element.get("tags", {})
    changes = propose_changes(tags)
    if not changes:
        return None
    osm_type, osm_id = element.get("type"), element.get("id")
    if osm_type not in ("node", "way", "relation") or isinstance(osm_id, bool) or not isinstance(osm_id, int) or osm_id < 1:
        return None
    try:
        geometry = mrcb.getElementCenterPoint(dict(element))
        lon, lat = geometry
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in geometry):
            return None
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            return None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    field, evidence = workshop_evidence(tags)
    rows = ["| Tag | Bisher | Vorschlag |", "| --- | --- | --- |"]
    for key, value in changes.items():
        rows.append(f"| {markdown_text(key)} | {markdown_text(tags.get(key, '—'))} | {markdown_text(value)} |")
    instruction = (
        "Prüfe, ob dieser Standort tatsächlich eine Werkstatt für Menschen mit Behinderungen ist.\n\n"
        f"**Objekt:** {markdown_text(tags.get('name', '(ohne Namen)'))}\n\n"
        f"**Hinweis aus {markdown_text(field)}:** {markdown_text(evidence)}\n\n"
        + "\n".join(rows)
        + "\n\nDer Text ist ein Suchhinweis. Prüfe die tatsächliche Nutzung, gegebenenfalls auf der Betreiberwebsite. "
        "Verwaltung, Werkstattladen, Schule, Wohnen und Tagespflege sind keine ausreichende Grundlage für diese Änderung. "
        "Bestätige den Vorschlag nur, wenn die Einordnung zum Standort passt; überspringe unsichere Fälle. "
        "Vorhandene Zielgruppen und andere Eigenschaften bleiben erhalten.\n\n"
        "[Tagging für soziale Einrichtungen](https://wiki.openstreetmap.org/wiki/DE:Key:social_facility) · "
        "[Zielgruppen](https://wiki.openstreetmap.org/wiki/DE:Key:social_facility:for)"
    )
    links = source_links(tags)
    if links:
        instruction += "\n\n**Vorhandene Quellenlinks:** " + links
    feature = mrcb.GeoFeature.withId(osm_type, osm_id, geometry, {"task_instruction": instruction})
    return mrcb.Task(feature, additionalFeatures=[], cooperativeWork=mrcb.TagFix(osm_type, osm_id, changes))


def main(output_file=None, bbox=None, max_tasks=None):
    query = build_query(bbox)
    challenge = mrcb.Challenge(max_tasks=max_tasks)
    elements = mrcb.Overpass().getElementsFromQuery(query)
    seen = set()
    for element in elements:
        if challenge.limit_reached:
            break
        identity = element.get("type"), element.get("id")
        if identity in seen:
            continue
        seen.add(identity)
        task = build_task(element)
        if task is not None and not challenge.addTask(task):
            break
    output_file = Path(output_file).resolve() if output_file is not None else OUTPUT_FILE
    output_file.parent.mkdir(parents=True, exist_ok=True)
    challenge.saveToFile(output_file)
    print(f"Saved {len(challenge.tasks)} social-workshop tasks to {output_file}")
    return challenge


def cli():
    parser = argparse.ArgumentParser(description="Generate German TagFix tasks for explicitly identified sheltered workshops.")
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"))
    parser.add_argument("--output", type=Path, help="Output file; defaults to social_workshop.json beside this script.")
    parser.add_argument("--max-tasks", type=int, help="Smaller task limit, up to the shared maximum of 50,000.")
    args = parser.parse_args()
    try:
        main(output_file=args.output, bbox=args.bbox, max_tasks=args.max_tasks)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    cli()
