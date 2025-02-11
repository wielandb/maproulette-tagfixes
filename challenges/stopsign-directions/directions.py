import xml.etree.ElementTree as ET
import math
import requests
from tqdm import tqdm
import geojson
import challenge_builder as mrcb
from time import sleep
import json

class OSMDataHandler:
    def __init__(self, json_data):
        self.data = json.loads(json_data)
        self.elements = self.data.get("elements", [])
    
    def get_nodes(self):
        return [element for element in self.elements if element["type"] == "node"]
    
    def get_ways(self):
        return [element for element in self.elements if element["type"] == "way"]
    
    def find_node_by_id(self, node_id):
        return next((node for node in self.get_nodes() if node["id"] == node_id), None)
    
    def find_way_by_id(self, way_id):
        return next((way for way in self.get_ways() if way["id"] == way_id), None)
    
    def determine_give_way_direction(self, give_way_node_id):
        for way in self.get_ways():
            if give_way_node_id in way["nodes"]:
                node_ids = way["nodes"]
                give_way_index = node_ids.index(give_way_node_id)
                distance_to_start = give_way_index
                distance_to_end = len(node_ids) - 1 - give_way_index
                return "backward" if distance_to_start < distance_to_end else "forward"
        raise ValueError("Given node ID not found in any way.")
    
    def calculate_rotation_angle(self, give_way_node_id):
        nodes = {node["id"]: (node["lat"], node["lon"]) for node in self.get_nodes()}
        for way in self.get_ways():
            if give_way_node_id in way["nodes"]:
                node_ids = way["nodes"]
                give_way_index = node_ids.index(give_way_node_id)
                prev_node_id = node_ids[give_way_index - 1] if give_way_index > 0 else node_ids[give_way_index + 1]
                lat1, lon1 = nodes[prev_node_id]
                lat2, lon2 = nodes[give_way_node_id]
                angle = math.degrees(math.atan2(lon2 - lon1, lat2 - lat1))
                direction = self.determine_give_way_direction(give_way_node_id)
                if direction == "backward":
                    angle = (angle + 180) % 360
                if angle < 0:
                    angle += 360
                return angle
        raise ValueError("Given node ID not found in any way.")
    
    def get_give_way_nodes(self, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            return []
        return [
            node["id"] for node in self.get_nodes() 
            if node["id"] in way["nodes"] 
            and "tags" in node 
            and node["tags"].get("highway") == "give_way"
        ]
    
    def get_stop_nodes(self, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            return []
        return [
            node["id"] for node in self.get_nodes() 
            if node["id"] in way["nodes"] 
            and "tags" in node 
            and node["tags"].get("highway") == "stop"
        ]
    
    def get_node_coordinates(self, node_id):
        node = self.find_node_by_id(node_id)
        if node:
            return node["lat"], node["lon"]
        raise ValueError("Node ID not found.")

stop_give_way_sign_direction_challenge = mrcb.Challenge()
stop_give_way_sign_direction_challenge.loadFromFile("stop_give_way_sign_direction_challenge.json")

INSTRUCTIONS = """
Für dieses SIGNTYPEPLACEHOLDER gibt es keine Angabe darüber, in welche Richtung es im Verhältnis zur Verlaufsrichtung des Weges zeigt.
Mit einem simplen Algorithmus konnte ein wahrscheinlicher Wert ermittelt werden.
Der vorgeschlagene Wert ist in diesem Fall: `direction=DIRECTION_VALUE_PLACEHOLDER`.
Dieser wird auf dem gezeigten Bild visualisiert. Bitte überprüfe, ob die Richtung korrekt ist.
Wenn ja, klicke auf "JA", ansonsten auf "NEIN" oder auf "ÜBERSPRINGEN".
Hier ist das Bild:

![](IMAGE_URL_PLACEHOLDER)

Ist die Richtung korrekt?"""

def addToChallenge(data):
    global stop_give_way_sign_direction_challenge
    SIGNTYPE_MAP = {
        "give_way": "Vorfahrt gewähren-Schild",
        "stop": "Stoppschild"
        }
    cooperativeWork = mrcb.TagFix(
        "node",
        data["node_id"],
        {"direction": data["direction"]}
    )
    mainFeature = mrcb.GeoFeature.withId(
        osmType="node",
        osmId=data["node_id"],
        geometry=geojson.Point((data["sign_lat"], data["sign_long"])),
        properties={"task_instruction" : INSTRUCTIONS.replace("SIGNTYPEPLACEHOLDER", SIGNTYPE_MAP[data["sign_type"]]).replace("DIRECTION_VALUE_PLACEHOLDER", data["direction"]).replace("IMAGE_URL_PLACEHOLDER", data["img_url"])}
    )
    t = mrcb.Task(
        mainFeature,
        additionalFeatures=[],
        cooperativeWork=cooperativeWork
    )
    stop_give_way_sign_direction_challenge.addTask(t)


import requests, os, json

CHALLENGE_RAW_DATA = []

static_map_size = "480x312"

print("Downloading data from Overpass API...")
# Get give_way nodes and their ways
response = requests.get("https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%5Btimeout%3A250%5D%3B%0Aarea%28id%3A3600051477%29-%3E.searchArea%3B%0Anode%5B%22highway%22%3D%22give_way%22%5D%5B%21%22direction%22%5D%28area.searchArea%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B")
osm_data = OSMDataHandler(json.dumps(response.json()))
ways = osm_data.get_ways()
total_ways = len(ways)
for way in tqdm(ways):
    way_id = way["id"]
    give_way_nodes = osm_data.get_give_way_nodes(way_id)
    print(f"Processing way {way_id} ({ways.index(way) + 1}/{total_ways}," + str(((ways.index(way) + 1) / total_ways * 100)) + "%)")
    for give_way_node in give_way_nodes:
        try:
            direction = osm_data.determine_give_way_direction(give_way_node)
            angle = osm_data.calculate_rotation_angle(give_way_node)
            int_angle = int(angle)
            sign_long, sign_lat = osm_data.get_node_coordinates(give_way_node)
            
            print(f"Way ID: {way_id}, Give Way Node: {give_way_node}, Direction: {direction}, Angle: {angle}")
            
            lat, lon = osm_data.get_node_coordinates(give_way_node)
            url = f"https://haukauntrie.de/online/api/staticmaps/staticmap.php?center={lat},{lon}&zoom=19&size={static_map_size}&maptype=mapnikde&markers={lat},{lon},icon_yield_{int_angle}"
            print(url)
            print("")
            
            datatoappend = {
                "way_id": way_id,
                "node_id": give_way_node,
                "direction": direction,
                "angle": angle,
                "img_url": url,
                "sign_type": "give_way",
                "sign_lat": sign_lat,
                "sign_long": sign_long
            }
            addToChallenge(datatoappend)
        except Exception as e:
            print(f"Error processing give_way node {give_way_node}: {str(e)}")
            continue

## Now for highway=stop nodes
print("Downloading data from Overpass API...")
response = requests.get("https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%5Btimeout%3A250%5D%3B%0Aarea%28id%3A3600051477%29-%3E.searchArea%3B%0Anode%5B%22highway%22%3D%22stop%22%5D%5B%21%22direction%22%5D%28area.searchArea%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B")
osm_data = OSMDataHandler(json.dumps(response.json()))
ways = osm_data.get_ways()

for way in tqdm(ways):
    way_id = way["id"]
    stop_nodes = osm_data.get_stop_nodes(way_id)
    
    for stop_node in stop_nodes:
        try:
            direction = osm_data.determine_give_way_direction(stop_node)
            angle = osm_data.calculate_rotation_angle(stop_node)
            int_angle = int(angle)
            sign_long, sign_lat = osm_data.get_node_coordinates(stop_node)
            
            print(f"Way ID: {way_id}, Stop Node: {stop_node}, Direction: {direction}, Angle: {angle}")
            
            lat, lon = osm_data.get_node_coordinates(stop_node)
            url = f"https://haukauntrie.de/online/api/staticmaps/staticmap.php?center={lat},{lon}&zoom=19&size={static_map_size}&maptype=mapnikde&markers={lat},{lon},icon_stop_{int_angle}"
            print(url)
            print("")
            
            toadddata = {
                "way_id": way_id,
                "node_id": stop_node,
                "direction": direction,
                "angle": angle,
                "img_url": url,
                "sign_type": "stop",
                "sign_lat": sign_lat,
                "sign_long": sign_long
            }
            addToChallenge(toadddata)
        except Exception as e:
            print(f"Error processing stop node {stop_node}: {str(e)}")
            continue

stop_give_way_sign_direction_challenge.saveToFile("stop_give_way_sign_direction_challenge.json")






