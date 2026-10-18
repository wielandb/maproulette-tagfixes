import requests
from time import sleep
import random
import sys
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from shared import challenge_builder as mrcb
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x, *args, **kwargs):
        return x

import re

if __package__:
    from . import valueFinder as vf
    from . import appStrings
else:
    import valueFinder as vf
    import appStrings
import json

import hashlib

HTTP_ATTEMPTS = 3


def _get_with_retries(url, *, timeout=60):
    """Retry transport failures and temporary service/rate-limit responses."""
    for attempt in range(HTTP_ATTEMPTS):
        response = None
        try:
            response = requests.get(url, timeout=timeout)
            if response.status_code not in (408, 429) and response.status_code < 500:
                return response
            error = ValueError(f"HTTP {response.status_code} for {url}")
        except requests.RequestException as exc:
            error = exc
        if attempt + 1 < HTTP_ATTEMPTS:
            sleep(30 if getattr(response, "status_code", None) == 429 else 5 * (2 ** attempt))
    raise ValueError(f"Request failed after {HTTP_ATTEMPTS} attempts: {url}: {error}") from error


def _image_id_is_missing(image_id, availability_cache=None):
    if availability_cache is not None and image_id in availability_cache:
        return availability_cache[image_id]
    response = _get_with_retries(f"https://api.imgur.com/oembed.json?url=https://imgur.com/{image_id}")
    if response.status_code == 200:
        if availability_cache is not None:
            availability_cache[image_id] = False
        return False
    # 403 also means authentication, access restrictions, and over-capacity on
    # Imgur. Only this specific oEmbed JSON response identifies an invalid ID.
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None
    if (response.status_code == 403 and isinstance(payload, dict)
            and payload.get("success") is False and payload.get("status") == 403
            and isinstance(payload.get("data"), dict)
            and payload["data"].get("error") == "Invalid URL - forbidden"):
        if availability_cache is not None:
            availability_cache[image_id] = True
        return True
    raise ValueError(f"Cannot determine image availability for {image_id}: HTTP {response.status_code}")

def check_imgur_404(link: str, availability_cache=None) -> bool:
    print("Checking imgur link: ", link)
    imgur_link = extract_imgur_id_from_link(link)
    missing = _image_id_is_missing(imgur_link, availability_cache)
    # Imgur's documented thumbnails append s/b/t/m/l/h to the original ID.
    # oEmbed accepts the original ID, but rejects its thumbnail ID. Check both
    # rather than truncating genuine image IDs that happen to end in a suffix.
    if missing and len(imgur_link) > 1 and imgur_link[-1] in "sbtmlh":
        missing = _image_id_is_missing(imgur_link[:-1], availability_cache)
    print("Image is not available" if missing else "Image is available")
    return missing


_DIRECT_IMGUR_PATTERN = re.compile(
    r'(?<![\w./?=&%-])(?:https?://)?(?:i\.)?imgur\.com/[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)?(?:\?[^\s;<>]*)?'
)


def extract_imgur_links_from_string(string):
    links = [match.group(0) for match in _DIRECT_IMGUR_PATTERN.finditer(string)]
    return [link if "://" in link else "https://" + link for link in links]


def _contains_only_direct_imgur_links(value):
    # Whole-tag removal is safe only for a list made exclusively of these URLs.
    # Preserve prose, archive URLs, and links to other image providers.
    return not _DIRECT_IMGUR_PATTERN.sub("", value).strip(" \t\r\n;,")


def extract_imgur_link_from_string(string: str) -> str:
    """
    Extracts the imgur link (which looks like e.g http://i.imgur.com/PCPiL7xl.jpg or http://i.imgur.com/PCPiL7xl.jpeg or https://imgur.com/PCPiL7xl) from a string.
    Returns the first direct image link, or raises ValueError if none is found.
    """
    # Do not extract an embedded Imgur URL from a Wayback/archive URL, another
    # hostname, or a URL query parameter. Those links can still be reachable.
    links = extract_imgur_links_from_string(string)
    if not links:
        raise ValueError("No direct imgur image link found")
    return links[0]



def extract_imgur_id_from_link(link: str) -> str:
    """
    Extracts the imgur id from a link.
    The id is the part between the last / and the .jpg, or, if there is no .jpg, after the last /.
    """
    parsed = urlsplit(link if "://" in link else "https://" + link)
    image_id = parsed.path.rstrip("/").split("/")[-1].split(".")[0]
    if parsed.hostname not in ("imgur.com", "i.imgur.com") or not re.fullmatch(r"[a-zA-Z0-9]+", image_id):
        raise ValueError(f"Invalid imgur image link: {link}")
    return image_id


def get_osm_history(osmtype: str, osmid: int) -> list:
    """Fetch full history of an OSM element"""
    base_url = "https://api.openstreetmap.org/api/0.6"
    url = f"{base_url}/{osmtype}/{osmid}/history"
    try:
        response = _get_with_retries(url)
    except ValueError as exc:
        print(f"Failed to get history for {osmtype}/{osmid}: {exc}")
        return []
    if response.status_code != 200:
        print(f"Failed to get history for {osmtype}/{osmid}")
        return []
    return response.text


def get_current_element(osmtype, osmid):
    response = _get_with_retries(f"https://api.openstreetmap.org/api/0.6/{osmtype}/{osmid}.json")
    if response.status_code in (404, 410):
        return None
    if response.status_code != 200:
        raise ValueError(f"Could not verify current {osmtype}/{osmid}: HTTP {response.status_code}")
    try:
        elements = response.json()["elements"]
        return next(element for element in elements if element["type"] == osmtype and element["id"] == osmid)
    except (KeyError, TypeError, StopIteration, ValueError) as exc:
        raise ValueError(f"Invalid current OSM element response for {osmtype}/{osmid}") from exc

def find_tag_setter(osmtype: str, osmid: int, key: str, value: str) -> tuple:
    """
    Find who set a specific tag value and in which version.
    Returns (username, version) or (None, None) if not found.
    """
    history_xml = get_osm_history(osmtype, osmid)
    if not history_xml:
        return None, None
    
    try:
        elements = ET.fromstring(history_xml).findall(osmtype)
    except ET.ParseError:
        return None, None
    
    # Find the beginning of the current uninterrupted run of this value.
    setter = (None, None)
    for element in sorted(elements, key=lambda item: int(item.get("version")), reverse=True):
        version = int(element.get("version"))
        username = element.get("user")
        tags = {tag.get("k"): tag.get("v") for tag in element.findall("tag")}
        if tags.get(key) != value:
            break
        setter = username, version
    return setter


def _report_filename(username):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", username).rstrip(". ")
    if not cleaned or cleaned.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        cleaned = "user_" + cleaned
    if cleaned != username or len(cleaned) > 100:
        cleaned = cleaned[:100] + "-" + hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]
    return cleaned + ".txt"

def create_user_reports(user_edits):
        (SCRIPT_DIR / "user_reports").mkdir(exist_ok=True)
        used_names = set()
        # Create per-user files
        for username, edits in user_edits.items():
            name = _report_filename(username)
            if name.casefold() in used_names:
                name = Path(name).stem[:100] + "-" + hashlib.sha256(username.encode("utf-8")).hexdigest()[:12] + ".txt"
            used_names.add(name.casefold())
            filename = SCRIPT_DIR / "user_reports" / name
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(str(appStrings.USER_REPORT_MESSAGE_START_DE))
                for edit in edits:
                    # Create OSM web link to the specific version
                    osm_link = f"https://www.openstreetmap.org/{edit['type']}/{edit['id']}/history#{edit['version']}"
                    f.write(f"{osm_link} - `{edit['key']}={edit['value']}`\n")
                f.write(str(appStrings.USER_REPORT_MESSAGE_END_DE))
                f.write("\n\n")
                f.write(str(appStrings.USER_REPORT_MESSAGE_START_EN))
                for edit in edits:
                    # Create OSM web link to the specific version
                    osm_link = f"https://www.openstreetmap.org/{edit['type']}/{edit['id']}/history#{edit['version']}"
                    f.write(f"{osm_link} - `{edit['key']}={edit['value']}`\n")
                f.write(str(appStrings.USER_REPORT_MESSAGE_END_EN))


def main(*, availability_cache=None):
    # Load the elements from the JSON file matches.json
    
    vf.main()
    with open(vf.MATCHES_FILE, "r", encoding='utf-8') as f:
           elements = json.load(f)
    # Adjacent Geofabrik extracts overlap. Each OSM object needs one task.
    elements = list({(element["type"], element["id"]): element for element in elements}.values())
    # This cache belongs to one invocation only: image availability can change.
    availability_cache = {} if availability_cache is None else availability_cache
    statistics = {
        "objects": len(elements), "direct_links": 0, "missing_links": 0,
        "unclear_checks": 0, "skipped_no_center": [], "stale_candidates": [],
        "skipped_mixed_values": [], "tasks": 0,
    }
    
    # Dictionary to store user -> list of edits
    user_edits = {}

    challenge = mrcb.Challenge()
    random.shuffle(elements)

    for element in tqdm(elements):
        print("Checking element: ", element["type"], "/", element["id"])
        try:
            geom = mrcb.getElementCenterPoint(element)
            if any(coordinate is None for coordinate in geom):
                raise ValueError("missing coordinates")
        except (KeyError, TypeError, ValueError) as exc:
            print(f"Skipping {element['type']}/{element['id']} without a display center: {exc}")
            statistics["skipped_no_center"].append(f"{element['type']}/{element['id']}")
            continue
        current_element = None
        current_loaded = False
        tagChanges = {}
        offendingKeyValues = {}
        # Check all tags for imgur URLs
        for tag_key, tag_value in element["tags"].items():
            if isinstance(tag_value, str) and "i.imgur.com" in tag_value:
                imgur_links = extract_imgur_links_from_string(tag_value)
                if imgur_links and not _contains_only_direct_imgur_links(tag_value):
                    statistics["skipped_mixed_values"].append({
                        "object": f"{element['type']}/{element['id']}", "key": tag_key,
                    })
                    continue
                statistics["direct_links"] += len(imgur_links)
                try:
                    missing_links = [check_imgur_404(link, availability_cache) for link in imgur_links]
                except ValueError:
                    statistics["unclear_checks"] += 1
                    print("Imgur run incomplete: " + json.dumps(statistics, ensure_ascii=True))
                    raise
                statistics["missing_links"] += sum(missing_links)
                # Removing a whole tag must not discard another valid link.
                if imgur_links and all(missing_links):
                    # Extract scans can be resumed months later. Never generate
                    # an edit for a deleted object or a tag that has since changed.
                    if not current_loaded:
                        current_element = get_current_element(element["type"], element["id"])
                        current_loaded = True
                    if current_element is None or current_element.get("tags", {}).get(tag_key) != tag_value:
                        print("Skipping deleted object or changed image tag")
                        statistics["stale_candidates"].append({
                            "object": f"{element['type']}/{element['id']}", "key": tag_key,
                            "reason": "deleted" if current_element is None else "tag_changed",
                        })
                        continue
                    tagChanges[tag_key] = None
                    offendingKeyValues[tag_key] = tag_value
                    print(f"Found 404 imgur link in tag: {tag_key}")
                    
                    # Find who set this tag
                    username, version = find_tag_setter(element["type"], element["id"], tag_key, tag_value)
                    if username:
                        if username not in user_edits:
                            user_edits[username] = []
                        # Store the relevant edit with all relevant info
                        user_edits[username].append({
                            'type': element["type"],
                            'id': element["id"],
                            'version': version,
                            'key': tag_key,
                            'value': tag_value
                        })
                    else:
                        print(f"Could not find who set the tag {tag_key} for {element['type']}/{element['id']}")
        
        # Only create a task if we found tags to change
        if tagChanges:
            # Create a list of the keys and values to be changed, format the links as Reachable links, start every row with a dash and end it with a newline
            linkList = "\n".join([f"- {key}: {value}" for key, value in offendingKeyValues.items()])
            fullTagTable = mrcb.TagsAsMdTable(element["tags"])
            mainFeature = mrcb.GeoFeature.withId(
                element["type"],
                element["id"],
                geom,
                properties={"linkList": linkList, "fullTagTable": fullTagTable}
            )
            cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                tagChanges
            )
            t = mrcb.Task(
                mainFeature,
                additionalFeatures=[],
                cooperativeWork=cooperativeWork
            )
            challenge.addTask(t)
            statistics["tasks"] += 1

    # Also replace an old challenge when this run finds no broken links.
    # Do this only after every check succeeds, so an outage cannot publish a
    # partial result or destroy the previous reports.
    challenge.saveToFile(SCRIPT_DIR / "imgur404.json")
    reports_directory = SCRIPT_DIR / "user_reports"
    reports_directory.mkdir(exist_ok=True)
    for filename in reports_directory.glob("*.txt"):
        if filename.is_file():
            filename.unlink()
    with open(SCRIPT_DIR / "user_reports.json", "w", encoding='utf-8') as f:
        json.dump(user_edits, f, indent=2, ensure_ascii=False)
    create_user_reports(user_edits)
    statistics["resolved_image_ids"] = len(availability_cache)
    statistics["missing_image_ids"] = sum(availability_cache.values())
    print("Imgur run complete: " + json.dumps(statistics, ensure_ascii=True))
    return statistics


if __name__ == "__main__":
    main()
