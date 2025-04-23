import os
import json
import requests
import osmium
import sys

GEOFABRIK_JSON = 'geofabrik_leafs.json'
MATCHES_FILE = 'matches.txt'
SEARCH_SEQUENCE = 'i.imgur.com'

class ValueFinderHandler(osmium.SimpleHandler):
    def __init__(self, search_sequence, matches_file):
        super().__init__()
        self.search_sequence = search_sequence
        self.matches_file = matches_file
    
    def check_tags(self, osm_type, obj):
        for tag in obj.tags:
            if self.search_sequence in tag.v:
                with open(self.matches_file, 'a', encoding='utf-8') as f:
                    f.write(f"{osm_type},{obj.id}\n")
                break

    def node(self, n):
        self.check_tags('node', n)

    def way(self, w):
        self.check_tags('way', w)

    def relation(self, r):
        self.check_tags('relation', r)

def download_file(url, local_filename):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

def main():
    # Load list of .osm.pbf files from geofabrik_leafs.json
    with open(GEOFABRIK_JSON, 'r', encoding='utf-8') as f:
        leafs = json.load(f)    # The JSON is a list of URLs as strings
    for pbf_url in leafs:
        local_filename = os.path.basename(pbf_url)
        print(f"Downloading {pbf_url} ...")
        download_file(pbf_url, local_filename)
        print(f"Processing {local_filename} ...")
        handler = ValueFinderHandler(SEARCH_SEQUENCE, MATCHES_FILE)
        handler.apply_file(local_filename)
        print(f"Deleting {local_filename} ...")
        os.remove(local_filename)
    print("Done.")

if __name__ == '__main__':
    main()