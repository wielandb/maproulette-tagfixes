import os
import json
import requests
import osmium
import sys
from typing import Dict, List, Optional, Literal
from dataclasses import dataclass, asdict
from tqdm import tqdm
from enum import Enum
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
from shared.challenge_builder import Overpass

if __package__:
    from . import procPercent as pp
else:
    import procPercent as pp
import random
from time import sleep

GEOFABRIK_JSON = SCRIPT_DIR / 'geofabrik_leafs.json'
MATCHES_FILE = SCRIPT_DIR / 'matches.json'
PROCESSED_URLS_FILE = SCRIPT_DIR / 'processed_urls.json'
SEARCH_SEQUENCE = 'i.imgur.com'
PROCCESSED_URLS = []
OVERPASS_RETRY_DELAY = 5
OVERPASS_RETRY_COUNT = 6
_overpass_client: Optional[Overpass] = None


def post_overpass_query(query: str) -> Optional[dict]:
    """Use shared retries and fallbacks while retaining optional center lookup."""
    global _overpass_client
    try:
        if _overpass_client is None:
            _overpass_client = Overpass(
                max_attempts=OVERPASS_RETRY_COUNT,
                retry_delay=OVERPASS_RETRY_DELAY,
            )
        return {"elements": _overpass_client.getElementsFromQuery(query)}
    except ValueError as exc:
        print(f"Could not fetch Overpass elements: {exc}")
        return None


class MatchType(str, Enum):
    CONTAINS = "contains"
    EXACT = "exact"

@dataclass
class Center:
    lat: float
    lon: float

@dataclass
class OSMObject:
    type: str
    id: int
    tags: Dict[str, str]
    lat: Optional[float] = None
    lon: Optional[float] = None
    center: Optional[Center] = None

class ValueFinderHandler(osmium.SimpleHandler):    
    def __init__(self, search_sequence: str, matches_file: str, match_type: MatchType = MatchType.CONTAINS):
        super().__init__()
        self.search_sequence = search_sequence
        self.matches_file = matches_file
        self.match_type = match_type
        self.location_handler = osmium.geom.WKBFactory()    

    def get_center_coordinates(self, osm_type: str, osm_id: int, visited=None) -> Optional[Center]:
        """Fetch center coordinates for ways and relations using Overpass API"""
        if visited is None:
            visited = set()
        object_key = (osm_type, osm_id)
        if object_key in visited:
            return None
        visited.add(object_key)
        query = f"""
        [out:json];
        {osm_type}({osm_id});
        out center;
        """
        data = post_overpass_query(query)
        if not data:
            return None
        if data["elements"]:
            element = data["elements"][0]
            if "center" in element:
                return Center(lat=element["center"]["lat"], lon=element["center"]["lon"])
            elif "lat" in element:
                return Center(lat=element["lat"], lon=element["lon"])
            elif "members" in element:
                # if there are no coordinates, then its a relation of relations where overpass cannot find a center.
                # In this case, we recursively call the function for each member until we find something that we can use as a display center.
                center = None
                for member in element["members"]:
                    if "lat" in member and "lon" in member:
                        center = Center(lat=member["lat"], lon=member["lon"])
                        break
                    elif member["type"] in ["node", "way", "relation"]:
                        center = self.get_center_coordinates(member["type"], member["ref"], visited)
                        if center:
                            break
                return center
        return None


    def create_overpass_element(self, osm_type: str, obj) -> Dict:
        """Create an Overpass API style element dictionary"""
        # Basic element structure
        element = {
            "type": osm_type,
            "id": obj.id,
            "tags": {tag.k: tag.v for tag in obj.tags}
        }

        if osm_type == 'node':
            element["lat"] = obj.location.lat
            element["lon"] = obj.location.lon
        elif osm_type in ['way', 'relation']:
            # Get center coordinates using Overpass API
            print("Creating center coordinates for way/relation")
            center = self.get_center_coordinates(osm_type, obj.id)
            print("Center coordinates: ", center)
            if center:
                element["center"] = asdict(center)
            else:
                # Fallback to using the first node's coordinates if available
                if osm_type == 'way' and obj.nodes and obj.nodes[0].location.valid():
                    first_node = obj.nodes[0]
                    element["lat"] = first_node.location.lat
                    element["lon"] = first_node.location.lon
                else:
                    element["lat"] = None
                    element["lon"] = None
        else:
            raise ValueError(f"Unsupported OSM type: {osm_type}")
        return element

    def check_tags(self, osm_type, obj):
        for tag in obj.tags:
            matches = (
                self.search_sequence == tag.v 
                if self.match_type == MatchType.EXACT 
                else self.search_sequence in tag.v
            )
            if matches:
                # Create Overpass-style element directly
                element = self.create_overpass_element(osm_type, obj)
                
                try:
                    with open(self.matches_file, 'r', encoding='utf-8') as f:
                        MATCHES = json.load(f)
                except FileNotFoundError:
                    MATCHES = []
                
                MATCHES.append(element)
                
                with open(self.matches_file, 'w', encoding='utf-8') as f:
                    json.dump(MATCHES, f, ensure_ascii=False, indent=4)
                print(f"Found {self.search_sequence} in {osm_type} {obj.id}")
                break
    
    def display_progress(self, osm_type, osm_id):
        if random.randint(1, 100000) == 42:
            try:
                max_values = pp.get_latest_created_ids()
                max_id = max_values.get(osm_type)
                if max_id is None or max_id <= 0:
                    return
                if osm_id > max_id:
                    print(f"Warning: {osm_type} ID {osm_id} is greater than current max {max_id}.")
                    return
                percentile = osm_id / max_id * 100
                print(f"{percentile:.2f}% of {osm_type} searched.")
            except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
                print(f"Could not update scan progress: {exc}")

    def node(self, n):
        self.check_tags('node', n)
        self.display_progress('node', n.id)

    def way(self, w):
        self.check_tags('way', w)
        self.display_progress('way', w.id)

    def relation(self, r):
        self.check_tags('relation', r)
        self.display_progress('relation', r.id)


def download_file(url, local_filename):
    local_filename = Path(local_filename)
    partial = local_filename.with_name(local_filename.name + '.part')
    for attempt in range(3):
        try:
            with requests.get(url, stream=True, timeout=(10, 120)) as response:
                response.raise_for_status()
                with tqdm(total=int(response.headers.get('content-length', 0)),
                          unit='iB', unit_scale=True,
                          desc=f'Downloading {local_filename.name}') as progress_bar:
                    with open(partial, 'wb') as output:
                        for chunk in response.iter_content(chunk_size=65536):
                            progress_bar.update(output.write(chunk))
            partial.replace(local_filename)
            return
        except requests.RequestException as exc:
            partial.unlink(missing_ok=True)
            status = getattr(exc.response, 'status_code', None)
            if attempt == 2 or (status is not None and status < 500 and status not in (408, 429)):
                raise
            sleep(30 if status == 429 else 5 * (2 ** attempt))

def main():
    # A successful scan without matches still needs a readable result file.
    if not os.path.exists(MATCHES_FILE):
        with open(MATCHES_FILE, 'w', encoding='utf-8') as f:
            json.dump([], f)
    # Load processed URLs from file if it exists
    if os.path.exists(PROCESSED_URLS_FILE):
        with open(PROCESSED_URLS_FILE, 'r', encoding='utf-8') as f:
            try:
                PROCCESSED_URLS = json.load(f)
            except json.JSONDecodeError:
                PROCCESSED_URLS = []
    else:
        PROCCESSED_URLS = []
    # Load list of .osm.pbf files from geofabrik_leafs.json
    try:
        with open(GEOFABRIK_JSON, 'r', encoding='utf-8') as f:
            leafs = json.load(f)
    except FileNotFoundError:
        print(f"File {GEOFABRIK_JSON} not found.")
        sys.exit(1)
    for pbf_url in tqdm(leafs):
        # Skip URLs that have already been processed
        if pbf_url in PROCCESSED_URLS:
            print(f"Skipping already processed URL: {pbf_url}")
            continue
        local_filename = SCRIPT_DIR / os.path.basename(pbf_url)
        print(f"Downloading {pbf_url} ...")
        # Only download the file if local_filename does not exist
        download_file(pbf_url, local_filename)
        handler = ValueFinderHandler(SEARCH_SEQUENCE, MATCHES_FILE)
        handler.apply_file(str(local_filename))
        print(f"Deleting {local_filename} ...")
        os.remove(local_filename)
        # Add the downloaded URL to the processed URLs list
        PROCCESSED_URLS.append(pbf_url)
        # Save the processed URLs to a file
        with open(PROCESSED_URLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(PROCCESSED_URLS, f, ensure_ascii=False, indent=4)
    print("Done.")

def find_value_objects(
    search_sequence: str = SEARCH_SEQUENCE,
    match_type: MatchType = MatchType.CONTAINS
) -> List[Dict]:
    """
    Scans Geofabrik extracts for objects with matching tag values.
    
    Args:
        search_sequence: The string to search for in tag values (default: SEARCH_SEQUENCE)
        match_type: MatchType.CONTAINS to search within values, or MatchType.EXACT for exact matches
    
    Returns:
        List of OSM objects that match the search criteria
    """
    # Reset results even when this scan finds no matching objects.
    with open(MATCHES_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)
    
    # Set up global search sequence
    global SEARCH_SEQUENCE
    SEARCH_SEQUENCE = search_sequence
    
    # Run the main scanning process with the specified match type
    try:
        with open(GEOFABRIK_JSON, 'r', encoding='utf-8') as f:
            leafs = json.load(f)
    except FileNotFoundError:
        print(f"File {GEOFABRIK_JSON} not found.")
        return []

    for pbf_url in tqdm(leafs):
        local_filename = SCRIPT_DIR / os.path.basename(pbf_url)
        print(f"Downloading {pbf_url} ...")
        download_file(pbf_url, local_filename)

        handler = ValueFinderHandler(search_sequence, MATCHES_FILE, match_type)
        handler.apply_file(str(local_filename))
        print(f"Deleting {local_filename} ...")
        os.remove(local_filename)
    
    # Return the results in Overpass format
    with open(MATCHES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def get_center_coordinates(osm_type: str, osm_id: int) -> Optional[Center]:
    """Fetch center coordinates for ways and relations using Overpass API"""
    query = f"""
    [out:json];
    {osm_type}({osm_id});
    out center;
    """
    data = post_overpass_query(query)
    if not data:
        return None
    if data["elements"]:
        element = data["elements"][0]
        if "center" in element:
            return Center(lat=element["center"]["lat"], lon=element["center"]["lon"])
        elif "lat" in element:
            return Center(lat=element["lat"], lon=element["lon"])
    return None





if __name__ == '__main__':
    main()
