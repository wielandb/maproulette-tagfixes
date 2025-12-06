import xml.etree.ElementTree as ET
import math
import requests
from tqdm import tqdm
import geojson
import challenge_builder as mrcb
from time import sleep

import json

SHORT_WAY_LENGTH_THRESHOLD_METERS = 50


def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


class OSMDataHandler:
    def __init__(self, json_data):
        self.data = json.loads(json_data)
        self.elements = self.data.get("elements", [])
        # Create a dictionary for the ways for faster access
        self.ways = {way["id"]: way for way in self.get_ways()}
        # Create a dictionary for the nodes for faster access
        self.nodes = {node["id"]: node for node in self.get_nodes()}
        self.node_way_counts = self._calculate_node_way_counts()
    
    def get_nodes(self):
        return [element for element in self.elements if element["type"] == "node"]
    
    def get_ways(self):
        return [element for element in self.elements if element["type"] == "way"]

    def _calculate_node_way_counts(self):
        counts = {}
        for way in self.get_ways():
            for node_id in way.get("nodes", []):
                counts[node_id] = counts.get(node_id, 0) + 1
        return counts
    
    def find_node_by_id(self, node_id):
        return self.nodes.get(node_id, None)
    
    def find_way_by_id(self, way_id):
        return self.ways.get(way_id, None)

    def determine_give_way_direction(self, give_way_node_id, way_id, short_way_threshold_meters=SHORT_WAY_LENGTH_THRESHOLD_METERS):
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found.")
        node_ids = way["nodes"]
        if give_way_node_id not in node_ids:
            raise ValueError("Given node ID not found in any way.")
        way_length_meters = self.calculate_way_length_meters(way_id)
        if way_length_meters < short_way_threshold_meters:
            return self.determine_direction_by_way_intersections(give_way_node_id, way_id)
        return self._determine_direction_by_node_position(give_way_node_id, node_ids)

    def _determine_direction_by_node_position(self, node_id, node_ids):
        node_index = node_ids.index(node_id)
        distance_to_start = node_index
        distance_to_end = len(node_ids) - 1 - node_index
        if distance_to_start == distance_to_end:
            length_to_start = self._calculate_path_length_meters(node_ids[:node_index + 1])
            length_to_end = self._calculate_path_length_meters(node_ids[node_index:])
            return "backward" if length_to_start < length_to_end else "forward"
        return "backward" if distance_to_start < distance_to_end else "forward"

    def determine_direction_by_way_intersections(self, give_way_node_id, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found.")
        node_ids = way["nodes"]
        if give_way_node_id not in node_ids:
            raise ValueError("Given node ID not found in any way.")
        give_way_index = node_ids.index(give_way_node_id)
        nodes_before = node_ids[:give_way_index]
        nodes_after = node_ids[give_way_index + 1:]
        before_connections = self.count_additional_way_memberships(nodes_before)
        after_connections = self.count_additional_way_memberships(nodes_after)
        return "forward" if before_connections > after_connections else "backward"

    def count_additional_way_memberships(self, node_ids):
        total = 0
        for node_id in node_ids:
            total += max(0, self.getNumberOfWaysNodeIsPartOf(node_id) - 1)
        return total

    def calculate_way_length_meters(self, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found.")
        node_ids = way["nodes"]
        if len(node_ids) < 2:
            return 0.0
        return self._calculate_path_length_meters(node_ids)

    def _calculate_path_length_meters(self, node_ids):
        if len(node_ids) < 2:
            return 0.0
        total_length = 0.0
        prev_lat, prev_lon = self.get_node_coordinates(node_ids[0])
        for node_id in node_ids[1:]:
            lat, lon = self.get_node_coordinates(node_id)
            total_length += haversine_distance(prev_lat, prev_lon, lat, lon)
            prev_lat, prev_lon = lat, lon
        return total_length

    def calculate_rotation_angle(self, give_way_node_id, way_id):
        way = self.find_way_by_id(way_id)
        if give_way_node_id in way["nodes"]:
            node_ids = way["nodes"]
            # Get all the node elements, but only for the nodes that are part of the way
            nodes = {}
            for node_id in node_ids:
                node = self.find_node_by_id(node_id)
                if node:
                    nodes[node_id] = (node["lat"], node["lon"])
            give_way_index = node_ids.index(give_way_node_id)
            prev_node_id = node_ids[give_way_index - 1] if give_way_index > 0 else node_ids[give_way_index + 1]
            lat1, lon1 = nodes[prev_node_id]
            lat2, lon2 = nodes[give_way_node_id]
            angle = math.degrees(math.atan2(lon2 - lon1, lat2 - lat1))
            direction = self.determine_give_way_direction(give_way_node_id, way_id)
            if direction == "backward":
                angle = (angle + 180) % 360
            if angle < 0:
                angle += 360
            return angle
        raise ValueError("Given node ID not found in any way.")
    
    def get_give_way_nodes(self, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found")
        return [node for node in way["nodes"] if self.find_node_by_id(node) and 
                self.find_node_by_id(node).get("tags", {}).get("highway") == "give_way"]
    
    def get_stop_nodes(self, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found")
        return [node for node in way["nodes"] if self.find_node_by_id(node) and 
                self.find_node_by_id(node).get("tags", {}).get("highway") == "stop"]
    
    def get_node_coordinates(self, node_id):
        node = self.find_node_by_id(node_id)
        if node:
            return node["lat"], node["lon"]
        raise ValueError("Node ID not found.")

    def isFirstOrLastNodeInWay(self, node_id, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found")
        nodes = way["nodes"]
        return node_id == nodes[0] or node_id == nodes[-1]
    
    def getWayTags(self, way_id):
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found")
        return way.get("tags", {})

    def getNumberOfWaysNodeIsPartOf(self, node_id):
        return self.node_way_counts.get(node_id, 0)

    def discardWayForTags(self, tags):
        # Determines if a way should be discarded based on its tags
        if not "highway" in tags:
            return True
        if "oneway" in tags and (tags["oneway"] == "yes" or tags["oneway"] == "-1"):
            for tag in tags:
                if "oneway:" in tag and tags[tag] == "no":
                    return False 
            return True
        return False

stop_give_way_sign_direction_challenge = mrcb.Challenge()
#stop_give_way_sign_direction_challenge.loadFromFile("stop_give_way_sign_direction_challenge.json")

INSTRUCTIONS = """
(Klappe dieses Feld auf, um die Visualisierung zu sehen!)
![](IMAGE_URL_PLACEHOLDER)
Ist die Richtung korrekt?

Für dieses SIGNTYPEPLACEHOLDER gibt es keine Angabe darüber, in welche Richtung es im Verhältnis zur Verlaufsrichtung des Weges zeigt.
Mit einem simplen Algorithmus konnte ein wahrscheinlicher Wert ermittelt werden.
Der vorgeschlagene Wert ist in diesem Fall: `direction=DIRECTION_VALUE_PLACEHOLDER`.
Dieser wird auf dem gezeigten Bild visualisiert.
Bitte überprüfe, ob die Richtung korrekt ist. (Und überprüfe natürlich gerne auch, ob der Standort des Schildes sinnvoll scheint!)
- Wenn ja, klicke auf "JA". 
- Ansonsten
   - klicke auf "NEIN", 
   - oder passe die Richtung an und klicke dann "JA"
- oder klicke auf "ÜBERSPRINGEN", wenn du dir unsicher bist und jemand anderes das überprüfen soll.

"""

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
        geometry=geojson.Point((data["sign_long"], data["sign_lat"])),
        properties={"task_instruction" : INSTRUCTIONS.replace("SIGNTYPEPLACEHOLDER", SIGNTYPE_MAP[data["sign_type"]]).replace("DIRECTION_VALUE_PLACEHOLDER", data["direction"]).replace("IMAGE_URL_PLACEHOLDER", data["img_url"])}
    )
    t = mrcb.Task(
        mainFeature,
        additionalFeatures=[],
        cooperativeWork=cooperativeWork
    )
    stop_give_way_sign_direction_challenge.addTask(t)


import requests, os, json

static_map_size = "480x312"

# Get all the way ids from ways that contain a highway=give_way node by getting https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%5Btimeout%3A250%5D%3B%0Aarea%28id%3A3600051477%29-%3E.searchArea%3B%0Anode%5B%22highway%22%3D%22give_way%22%5D%5B%21%22direction%22%5D%28area.searchArea%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B
print("Downloading data from Overpass API...")
response = requests.get("https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%5Btimeout%3A250%5D%3B%0Aarea%28id%3A3600051477%29-%3E.searchArea%3B%0Anode%5B%22highway%22%3D%22give_way%22%5D%5B%21%22direction%22%5D%28area.searchArea%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B%0Aarea%28id%3A3600016239%29-%3E.searchArea2%3B%0Anode%5B%22highway%22%3D%22give_way%22%5D%5B%21%22direction%22%5D%28area.searchArea2%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B%0Aarea%28id%3A3600051701%29-%3E.searchArea3%3B%0Anode%5B%22highway%22%3D%22give_way%22%5D%5B%21%22direction%22%5D%28area.searchArea3%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B")
print(f"Overpass response status: {response.status_code} {response.reason}")
print(f"Response URL: {response.url}")
print(f"Response headers: {dict(response.headers)}")
print(f"Response body length: {len(response.text)}")
snippet = response.text[:1000].replace('\n', ' ') if response.text else ''
print(f"Response body snippet (first 1000 chars): {snippet!r}")
data_handler = OSMDataHandler(response.text)
ways = data_handler.get_ways()
print("Sorting ways...")
# For each of those ways, get the full way xml by calling osm.org/api/0.6/way/way_id/full
for way in tqdm(ways):
    way_id = way["id"]
    # Guard clause to skip *ways* that are problematic
    if data_handler.discardWayForTags(data_handler.getWayTags(way_id)):
        continue
    give_way_nodes = data_handler.get_give_way_nodes(way_id)
    for give_way_node in give_way_nodes:
        # Guard clauses to skip *nodes in a way* that are problematic (first or last node in a way, part of more than one way)
        if data_handler.isFirstOrLastNodeInWay(give_way_node, way_id):
            continue
        if data_handler.getNumberOfWaysNodeIsPartOf(give_way_node) > 1:
            continue
        direction = data_handler.determine_give_way_direction(give_way_node, way_id)
        angle = data_handler.calculate_rotation_angle(give_way_node, way_id)
        int_angle = int(angle)
        sign_lat, sign_long = data_handler.get_node_coordinates(give_way_node)
        #print(f"Way ID: {way_id}, Give Way Node: {give_way_node}, Direction: {direction}, Angle: {angle}")
        lat, lon = data_handler.get_node_coordinates(give_way_node)
        url = f"https://haukauntrie.de/online/api/staticmaps/staticmap.php?center={lat},{lon}&zoom=19&size={static_map_size}&maptype=mapnikde&markers={lat},{lon},icon_yield_{int_angle}"
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

## Now, we do the same for highway=stop

# Get all the way ids from ways that contain a highway=stop node by getting https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%5Btimeout%3A250%5D%3B%0Aarea%28id%3A3600051477%29-%3E.searchArea%3B%0Anode%5B%22highway%22%3D%22stop%22%5D%5B%21%22direction%22%5D%28area.searchArea%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B
print("Downloading data from Overpass API...")
response = requests.get("https://overpass-api.de/api/interpreter?data=%5Bout%3Ajson%5D%5Btimeout%3A250%5D%3B%0Aarea%28id%3A3600051477%29-%3E.searchArea%3B%0Anode%5B%22highway%22%3D%22stop%22%5D%5B%21%22direction%22%5D%28area.searchArea%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B%0Aarea%28id%3A3600016239%29-%3E.searchArea2%3B%0Anode%5B%22highway%22%3D%22stop%22%5D%5B%21%22direction%22%5D%28area.searchArea2%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B%0Aarea%28id%3A3600051701%29-%3E.searchArea3%3B%0Anode%5B%22highway%22%3D%22stop%22%5D%5B%21%22direction%22%5D%28area.searchArea3%29%3B%0Away%28bn%29%3B%0A%28._%3B%3E%3B%29%3B%0Aout%20body%3B")
data_handler = OSMDataHandler(response.text)
ways = data_handler.get_ways()
print("Sorting ways...")

# For each of those ways, get the full way xml by calling osm.org/api/0.6/way/way_id/full
for way in tqdm(ways):
    way_id = way["id"]
    # Guard clause to skip ways that are problematic
    if data_handler.discardWayForTags(data_handler.getWayTags(way_id)):
        continue
    stop_nodes = data_handler.get_stop_nodes(way_id)
    for stop_node in stop_nodes:
        # Guard clauses to skip *nodes in a way* that are problematic (first or last node in a way, part of more than one way)
        if data_handler.isFirstOrLastNodeInWay(give_way_node, way_id):
            continue
        if data_handler.getNumberOfWaysNodeIsPartOf(give_way_node) > 1:
            continue
        direction = data_handler.determine_give_way_direction(stop_node, way_id)
        angle = data_handler.calculate_rotation_angle(stop_node, way_id)
        int_angle = int(angle)
        sign_lat, sign_long = data_handler.get_node_coordinates(stop_node)
        #print(f"Way ID: {way_id}, Stop Node: {stop_node}, Direction: {direction}, Angle: {angle}")
        lat, lon = data_handler.get_node_coordinates(stop_node)
        url = f"https://haukauntrie.de/online/api/staticmaps/staticmap.php?center={lat},{lon}&zoom=19&size={static_map_size}&maptype=mapnikde&markers={lat},{lon},icon_stop_{int_angle}"
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


stop_give_way_sign_direction_challenge.saveToFile("stop_give_way_sign_direction_challenge.json")




