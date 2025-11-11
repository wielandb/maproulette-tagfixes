import os
import json
import requests
import osmium
import sys
import time
from typing import Dict, List, Optional, Literal
from dataclasses import dataclass, asdict
from tqdm import tqdm
from enum import Enum

import procPercent as pp
import random

GEOFABRIK_JSON = 'geofabrik_leafs.json'
MATCHES_FILE = 'matches.json'
SEARCH_SEQUENCE = 'i.imgur.com'
OVERPASS_API = "https://overpass-api.de/api/interpreter"
PROCCESSED_URLS = []
OVERPASS_RETRY_DELAY = 10
OVERPASS_RETRY_COUNT = 5


def post_overpass_query(query: str) -> Optional[dict]:
    """Post an Overpass query with retry delay on failure."""
    for attempt in range(1, OVERPASS_RETRY_COUNT + 1):
        try:
            response = requests.post(OVERPASS_API, data={"data": query}, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            print(f"Overpass request failed (attempt {attempt}/{OVERPASS_RETRY_COUNT}): {exc}")
            if attempt < OVERPASS_RETRY_COUNT:
                print(f"Retrying in {OVERPASS_RETRY_DELAY} seconds...")
                time.sleep(OVERPASS_RETRY_DELAY)
    print("Giving up after multiple Overpass request failures.")
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

    def get_center_coordinates(self, osm_type: str, osm_id: int) -> Optional[Center]:
        """Fetch center coordinates for ways and relations using Overpass API"""
        query = f"""
        [out:json];
        {osm_type}({osm_id});
        out center;
        """
        data = post_overpass_query(query)
        if not data:
            return None
        print(data)
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
                    if member["type"] == "node":
                        center = Center(lat=member["lat"], lon=member["lon"])
                        break
                    elif member["type"] in ["way", "relation"]:
                        center = self.get_center_coordinates(member["type"], member["ref"])
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
                if obj.nodes:
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
            max_values = pp.get_latest_created_ids()
            if osm_type in max_values:
                max_id = max_values[osm_type]
                if osm_id > max_id:
                    print(f"Warning: {osm_type} ID {osm_id} is greater than current max {max_id}.")
                    return
                percentile = pp.get_id_percentile(osm_type, osm_id)
                print(f"{percentile:.2f}% of {osm_type} searched.")

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
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        # Get file size from headers
        total_size = int(r.headers.get('content-length', 0))
        # Set up progress bar
        progress_bar = tqdm(
            total=total_size,
            unit='iB',
            unit_scale=True,
            desc=f'Downloading {local_filename}'
        )
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                size = f.write(chunk)
                progress_bar.update(size)
        progress_bar.close()

def main():
    # Load processed URLs from file if it exists
    if os.path.exists('processed_urls.json'):
        with open('processed_urls.json', 'r', encoding='utf-8') as f:
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
        local_filename = os.path.basename(pbf_url)
        print(f"Downloading {pbf_url} ...")
        # Only download the file if local_filename does not exist
        download_file(pbf_url, local_filename)
        handler = ValueFinderHandler(SEARCH_SEQUENCE, MATCHES_FILE)
        handler.apply_file(local_filename)
        print(f"Deleting {local_filename} ...")
        os.remove(local_filename)
        # Add the downloaded URL to the processed URLs list
        PROCCESSED_URLS.append(pbf_url)
        # Save the processed URLs to a file
        with open('processed_urls.json', 'w', encoding='utf-8') as f:
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
    # Delete the matches file if it exists
    if os.path.exists(MATCHES_FILE):
        os.remove(MATCHES_FILE)
    
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
        local_filename = os.path.basename(pbf_url)
        print(f"Downloading {pbf_url} ...")
        download_file(pbf_url, local_filename)

        handler = ValueFinderHandler(search_sequence, MATCHES_FILE, match_type)
        handler.apply_file(local_filename)
        print(f"Deleting {local_filename} ...")
        os.remove(local_filename)
    
    # Return the results in Overpass format
    return get_overpass_style_elements()

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
