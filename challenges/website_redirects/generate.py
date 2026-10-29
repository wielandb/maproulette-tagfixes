"""Generate reviewed TagFix suggestions for permanent website redirects."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import html
from itertools import islice
import math
from pathlib import Path
import sys
import time
from urllib.parse import quote, urlsplit

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))
from shared import challenge_builder as mrcb
if __package__:
    from .http_checks import MAX_AGE, USER_AGENT, RedirectChecker, ResultCache, parse_url
else:
    from http_checks import MAX_AGE, USER_AGENT, RedirectChecker, ResultCache, parse_url

WEBSITE_KEYS = ("website", "contact:website")
GERMANY_PBF = "https://download.geofabrik.de/europe/germany-latest.osm.pbf"
DEFAULT_OUTPUT = SCRIPT_DIR / "website_redirects.json"
BATCH_SIZE = 32
CURRENT_BATCH_SIZE = 100


def candidate(element):
    if element.get("type") not in ("node", "way", "relation"):
        return None
    if not isinstance(element.get("id"), int) or element["id"] < 1:
        return None
    tags = element.get("tags", {})
    urls = {}
    for key in WEBSITE_KEYS:
        value = tags.get(key)
        try:
            parse_url(value)
        except (ValueError, TypeError, UnicodeError):
            continue
        urls[key] = value
    if not urls:
        return None
    return {"type": element["type"], "id": element["id"], "urls": urls}


def download_germany(cache_dir, *, now=time.time, get=None):
    """A failed refresh preserves the previous extract and aborts generation."""
    path = Path(cache_dir) / "germany-latest.osm.pbf"
    if path.is_file() and path.stat().st_size > 0 and 0 <= now() - path.stat().st_mtime < MAX_AGE:
        return path
    temporary = path.with_suffix(path.suffix + ".part")
    session = None
    try:
        if get is None:
            session = requests.Session()
            session.trust_env = False
            get = session.get
        with get(GERMANY_PBF, stream=True, timeout=(10, 120),
                 headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            expected = int(length) if length and length.isdigit() else None
            downloaded = 0
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    downloaded += output.write(chunk)
            if not downloaded or (expected is not None and downloaded != expected):
                raise RuntimeError("Deutschland-Extrakt ist leer oder unvollständig.")
        temporary.replace(path)
        return path
    finally:
        temporary.unlink(missing_ok=True)
        if session is not None:
            session.close()


def pbf_candidates(path):
    # No location index is needed: current geometry is requested only after HTTP
    # confirmation. KeyFilter runs in C++ before objects reach Python.
    import osmium
    processor = osmium.FileProcessor(str(path)).with_filter(osmium.filter.KeyFilter(*WEBSITE_KEYS))
    for obj in processor:
        if isinstance(obj, osmium.osm.Node):
            osm_type = "node"
        elif isinstance(obj, osmium.osm.Way):
            osm_type = "way"
        elif isinstance(obj, osmium.osm.Relation):
            osm_type = "relation"
        else:
            continue
        item = candidate({"type": osm_type, "id": obj.id, "tags": dict(obj.tags)})
        if item:
            yield item


def bbox_candidates(overpass, bbox):
    south, west, north, east = bbox
    bounds = ",".join(str(value) for value in (south, west, north, east))
    query = ('[out:json][timeout:250];('
             f'nwr["website"]({bounds});nwr["contact:website"]({bounds}););out tags;')
    for element in overpass.getElementsFromQuery(query):
        item = candidate(element)
        if item:
            yield item


def current_elements(overpass, candidates):
    for start in range(0, len(candidates), CURRENT_BATCH_SIZE):
        batch = candidates[start:start + CURRENT_BATCH_SIZE]
        selectors = []
        for osm_type in ("node", "way", "relation"):
            ids = sorted({item["id"] for item in batch if item["type"] == osm_type})
            if ids:
                selectors.append(f'{osm_type}(id:{",".join(map(str, ids))});')
        query = "[out:json][timeout:250];(" + "".join(selectors) + ");out tags center;"
        for element in overpass.getElementsFromQuery(query):
            yield element


def markdown(value):
    return html.escape(str(value), quote=False).replace("|", "&#124;").replace("`", "&#96;").replace("\n", " ").replace("\r", " ")


def link(url):
    # Percent-encode characters that could escape a Markdown link destination.
    return "[" + markdown(url).replace("[", "&#91;").replace("]", "&#93;") + "](<" + quote(url, safe=":/?#[]@!$&'()*+,;=%~._-").replace("<", "%3C").replace(">", "%3E") + ">)"


def task_for(element, original, results):
    tags = element.get("tags", {})
    edits = {}
    details = []
    for key in WEBSITE_KEYS:
        old = original["urls"].get(key)
        result = results.get(old)
        # Recheck the *exact* current tag: never repair an old extract value over
        # a more recent mapper edit, and never invent a missing tag.
        if not old or tags.get(key) != old or result is None or not result.eligible:
            continue
        edits[key] = result.target
        warnings = []
        before, after = urlsplit(old), urlsplit(result.target)
        if before.scheme.lower() == "https" and after.scheme.lower() == "http":
            warnings.append("**Ziel verwendet HTTP statt HTTPS: Website und URL prüfen.**")
        if before.hostname.lower() != after.hostname.lower():
            warnings.append("**Hostname/Domain geändert: Betreiber und Standort prüfen.**")
        if before.path not in ("", "/") and after.path in ("", "/"):
            warnings.append("**Bisheriger Unterseitenpfad entfällt: Startseite statt Standort-/Filialseite?**")
        checked = datetime.fromtimestamp(result.checked_at, timezone.utc).isoformat(timespec="seconds")
        lines = [f"### `{key}`", f"| Vorher | Vorschlag |\n| --- | --- |\n| {link(old)} | {link(result.target)} |",
                 f"HTTP-Prüfung: {checked}; Zielstatus **200**."]
        if result.title:
            lines.append("Seitentitel am Ziel: " + markdown(result.title))
        lines.extend(warnings)
        lines.append("Weiterleitungskette:")
        for hop in result.hops:
            lines.append(f'- **{hop["status"]}**: {link(hop["url"])} → {link(hop["target"])}')
        details.append("\n\n".join(lines))
    if not edits:
        return None
    try:
        geometry = mrcb.getElementCenterPoint(element)
    except (KeyError, ValueError, TypeError):
        return None
    if (not isinstance(geometry, (list, tuple)) or len(geometry) != 2
            or any(isinstance(value, bool) or not isinstance(value, (int, float))
                   or not math.isfinite(value) for value in geometry)
            or not (-180 <= geometry[0] <= 180 and -90 <= geometry[1] <= 90)):
        return None
    name = tags.get("name", "Ohne Namen")
    address = ", ".join(tags[key] for key in ("addr:street", "addr:housenumber", "addr:postcode", "addr:city") if tags.get(key))
    instruction = ("## Permanente Website-Weiterleitung prüfen\n\n"
                   f'Objekt: **{markdown(name)}** (`{element["type"]}/{element["id"]}`)\n\n'
                   f'Adresse: {markdown(address or "nicht am Objekt erfasst")}\n\n'
                   "Öffne die vorgeschlagene Website und prüfe Namen, Betreiber und Standort. "
                   "301/308 bestätigen eine permanente Weiterleitung, aber nicht die Identität des Ziels. "
                   "Bei Domainparking, Anmeldung, unpassender Konzernstartseite oder einem anderen Standort "
                   "den Vorschlag nicht übernehmen. Prüfe jeden betroffenen Schlüssel. "
                   "Auch HTTPS-, www- und Slash-Weiterleitungen sind enthalten.\n\n" + "\n\n".join(details))
    feature = mrcb.GeoFeature.withId(element["type"], element["id"], geometry,
        {"task_id": f'website-redirect-{element["type"]}-{element["id"]}', "task_instruction": instruction})
    return mrcb.Task(feature, cooperativeWork=mrcb.TagFix(element["type"], element["id"], edits))


def generate(candidates, overpass, cache, checker, *, challenge=None, workers=4):
    challenge = challenge if challenge is not None else mrcb.Challenge()
    if workers not in range(1, 5):
        raise ValueError("Ein bis vier Website-Worker sind erlaubt.")
    source = iter(candidates)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        while not challenge.limit_reached:
            batch = list(islice(source, BATCH_SIZE))
            if not batch:
                break
            urls = sorted({url for item in batch for url in item["urls"].values()})
            results = {url: cache.get(url) for url in urls}
            pending = [url for url in urls if results[url] is None]
            for result in executor.map(checker.check, pending):
                results[result.source] = result
                cache.put(result)
            checker.ensure_network_worked()
            confirmed = [item for item in batch if any(results[url].eligible for url in item["urls"].values())]
            if not confirmed:
                continue
            originals = {(item["type"], item["id"]): item for item in confirmed}
            for current in current_elements(overpass, confirmed):
                if challenge.limit_reached:
                    break
                original = originals.get((current.get("type"), current.get("id")))
                if original is None:
                    continue
                task = task_for(current, original, results)
                if task is not None and not challenge.addTask(task):
                    break
    checker.ensure_network_worked()
    return challenge


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="Permanente Website-Weiterleitungen als TagFix-Challenge (Deutschland).")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--pbf", type=Path, help="Vorhandener OSM-PBF-Extrakt; keine automatische Aktualisierung.")
    source.add_argument("--bbox", type=float, nargs=4, metavar=("SÜD", "WEST", "NORD", "OST"), help="Kleine Overpass-Auswahl statt Deutschland-PBF.")
    parser.add_argument("--cache-dir", type=Path, default=SCRIPT_DIR / ".cache")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-tasks", type=int)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args(argv)
    if args.max_tasks is not None and args.max_tasks < 1:
        parser.error("--max-tasks muss positiv sein")
    if args.bbox:
        south, west, north, east = args.bbox
        if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
            parser.error("--bbox benötigt gültige Koordinaten SÜD WEST NORD OST")
    return args


def main(argv=None):
    args = arguments(argv)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    overpass = mrcb.Overpass()
    checker = RedirectChecker()
    cache = ResultCache(args.cache_dir / "redirects.sqlite3")
    try:
        if args.bbox:
            candidates = bbox_candidates(overpass, args.bbox)
        else:
            path = args.pbf if args.pbf is not None else download_germany(args.cache_dir)
            candidates = pbf_candidates(path)
        challenge = generate(candidates, overpass, cache, checker,
                             challenge=mrcb.Challenge(max_tasks=args.max_tasks), workers=args.workers)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        challenge.saveToFile(args.output)
        print(f"{len(challenge.tasks)} Aufgaben: {args.output}")
        return challenge
    finally:
        cache.close()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, requests.RequestException) as exc:
        print(f"Website-Challenge fehlgeschlagen; bisherige Ausgabe bleibt erhalten: {exc}", file=sys.stderr)
        sys.exit(1)
