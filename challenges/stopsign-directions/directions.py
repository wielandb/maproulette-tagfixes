import importlib.util
import json
import math
from pathlib import Path
import sys
from tqdm import tqdm
import geojson


def _load_local_challenge_builder():
    # Other generators have a different builder with an incompatible API.
    module_name = "stopsign_directions_challenge_builder"
    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).resolve().with_name("challenge_builder.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mrcb = _load_local_challenge_builder()

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from shared.challenge_builder import Overpass

SHORT_WAY_LENGTH_THRESHOLD_METERS = 50
DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parent / "stop_give_way_sign_direction_challenge.json"
SEARCH_AREAS = (3600051477, 3600016239, 3600051701)
STATIC_MAP_SIZE = "480x312"


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
        self.data = json.loads(json_data) if isinstance(json_data, str) else json_data
        # An element can occur more than once in the Overpass response.
        self.elements = list({
            (element["type"], element["id"]): element
            for element in self.data.get("elements", [])
        }.values())
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

def addToChallenge(data, challenge):
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
    challenge.addTask(t)


def create_overpass_query(sign_type):
    if sign_type not in ("give_way", "stop"):
        raise ValueError(f"Unsupported sign type: {sign_type}")
    areas = "\n".join(
        f'    node["highway"="{sign_type}"][!"direction"](area:{area_id});'
        for area_id in SEARCH_AREAS
    )
    return f"[out:json][timeout:250];\n(\n{areas}\n);\nway(bn);\n(._;>;);\nout body;"


def populate_challenge(challenge, data_handler, sign_type):
    if sign_type not in ("give_way", "stop"):
        raise ValueError(f"Unsupported sign type: {sign_type}")
    get_sign_nodes = (
        data_handler.get_give_way_nodes if sign_type == "give_way"
        else data_handler.get_stop_nodes
    )
    icon_type = "yield" if sign_type == "give_way" else "stop"
    for way in tqdm(data_handler.get_ways()):
        way_id = way["id"]
        if data_handler.discardWayForTags(data_handler.getWayTags(way_id)):
            continue
        if len(way.get("nodes", [])) < 2 or any(
            data_handler.find_node_by_id(node_id) is None
            or not isinstance(data_handler.find_node_by_id(node_id).get("lat"), (int, float))
            or not isinstance(data_handler.find_node_by_id(node_id).get("lon"), (int, float))
            for node_id in way.get("nodes", [])
        ):
            print(f"Skipping way/{way_id} with incomplete node coordinates", file=sys.stderr)
            continue
        for sign_node in get_sign_nodes(way_id):
            # Recursing from a way also returns signs that were not selected.
            if "direction" in data_handler.find_node_by_id(sign_node).get("tags", {}):
                continue
            if data_handler.isFirstOrLastNodeInWay(sign_node, way_id):
                continue
            if data_handler.getNumberOfWaysNodeIsPartOf(sign_node) > 1:
                continue
            direction = data_handler.determine_give_way_direction(sign_node, way_id)
            angle = data_handler.calculate_rotation_angle(sign_node, way_id)
            lat, lon = data_handler.get_node_coordinates(sign_node)
            url = (
                "https://haukauntrie.de/online/api/staticmaps/staticmap.php"
                f"?center={lat},{lon}&zoom=19&size={STATIC_MAP_SIZE}&maptype=mapnikde"
                f"&markers={lat},{lon},icon_{icon_type}_{int(angle)}"
            )
            addToChallenge({
                "way_id": way_id,
                "node_id": sign_node,
                "direction": direction,
                "angle": angle,
                "img_url": url,
                "sign_type": sign_type,
                "sign_lat": lat,
                "sign_long": lon,
            }, challenge)


def main(output_path=None, overpass=None):
    challenge = mrcb.Challenge()
    overpass = overpass if overpass is not None else Overpass()
    for sign_type in ("give_way", "stop"):
        print(f"Downloading {sign_type} data from Overpass API...")
        elements = overpass.getElementsFromQuery(create_overpass_query(sign_type))
        data_handler = OSMDataHandler({"elements": elements})
        print("Sorting ways...")
        populate_challenge(challenge, data_handler, sign_type)
    # Save only once both downloads and all task generation have succeeded.
    challenge.saveToFile(DEFAULT_OUTPUT_PATH if output_path is None else output_path)
    return challenge


if __name__ == "__main__":
    main()
