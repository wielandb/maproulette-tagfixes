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

MAX_JUNCTION_DISTANCE_METERS = 60
CONTEXT_RADIUS_METERS = 120
MIN_DISTANCE_ADVANTAGE_METERS = 10
MIN_DISTANCE_RATIO = 2
CONTEXT_BATCH_SIZE = 100
ROAD_HIGHWAYS = frozenset({
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "motorway_link", "trunk_link", "primary_link", "secondary_link",
    "tertiary_link", "unclassified", "residential", "living_street",
    "service", "road", "track",
})
MINOR_SERVICES = frozenset({"driveway", "parking_aisle", "drive-through", "emergency_access"})
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
    def __init__(self, json_data, candidate_node_ids=None):
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
        self.candidate_node_ids = (
            None if candidate_node_ids is None else set(candidate_node_ids)
        )
        self.road_neighbors = {}
        self.road_way_ids = {}
        self.incomplete_road_nodes = set()
        for way in self.get_ways():
            node_ids = way.get("nodes", [])
            tags = way.get("tags", {})
            # A driveway cannot establish a priority-road junction, but a sign
            # shared with that driveway still has an ambiguous way direction.
            if tags.get("highway") in ROAD_HIGHWAYS and tags.get("area") != "yes":
                for node_id in set(node_ids):
                    self.road_way_ids.setdefault(node_id, set()).add(way["id"])
            if not self.is_road(way):
                continue
            for first, second in zip(node_ids, node_ids[1:]):
                if not self.has_coordinates(first) or not self.has_coordinates(second):
                    self.incomplete_road_nodes.update((first, second))
                    continue
                if first != second:
                    self.road_neighbors.setdefault(first, set()).add(second)
                    self.road_neighbors.setdefault(second, set()).add(first)

    @staticmethod
    def is_road(way):
        tags = way.get("tags", {})
        return (
            tags.get("highway") in ROAD_HIGHWAYS and tags.get("area") != "yes"
            and not (tags.get("highway") == "service" and tags.get("service") in MINOR_SERVICES)
        )

    def has_coordinates(self, node_id):
        node = self.nodes.get(node_id, {})
        return all(
            isinstance(node.get(key), (int, float)) and math.isfinite(node[key])
            for key in ("lat", "lon")
        )
    
    def get_nodes(self):
        return [element for element in self.elements if element["type"] == "node"]
    
    def get_ways(self):
        return [element for element in self.elements if element["type"] == "way"]

    def _calculate_node_way_counts(self):
        counts = {}
        for way in self.get_ways():
            for node_id in set(way.get("nodes", [])):
                counts[node_id] = counts.get(node_id, 0) + 1
        return counts
    
    def find_node_by_id(self, node_id):
        return self.nodes.get(node_id, None)
    
    def find_way_by_id(self, way_id):
        return self.ways.get(way_id, None)

    def determine_give_way_direction(self, give_way_node_id, way_id):
        """Infer travel towards a clearly nearer road junction, or abstain.

        The context query must supply every road within CONTEXT_RADIUS_METERS
        of the sign. Way endpoints and node density are not junction evidence.
        """
        way = self.find_way_by_id(way_id)
        if not way:
            raise ValueError(f"Way {way_id} not found.")
        node_ids = way["nodes"]
        if give_way_node_id not in node_ids:
            raise ValueError("Given node ID not found in any way.")
        if (not self.is_road(way) or len(node_ids) < 3
                or node_ids[0] == node_ids[-1]
                or len(node_ids) != len(set(node_ids))
                or self.road_way_ids.get(give_way_node_id) != {way_id}
                or len(self.road_neighbors.get(give_way_node_id, ())) != 2
                or not all(self.has_coordinates(node_id) for node_id in node_ids)):
            return None
        index = node_ids.index(give_way_node_id)
        if index == 0 or index == len(node_ids) - 1:
            return None
        before = self._trace_to_junction(give_way_node_id, node_ids[index - 1])
        after = self._trace_to_junction(give_way_node_id, node_ids[index + 1])
        if before[0] is not None and before[0] == after[0]:
            return None  # A loop reaches the same junction from both sides.
        for direction, nearer, farther in (
            ("backward", before, after), ("forward", after, before),
        ):
            if nearer[0] is None or nearer[1] > MAX_JUNCTION_DISTANCE_METERS:
                continue
            required_distance = max(
                nearer[1] * MIN_DISTANCE_RATIO,
                nearer[1] + MIN_DISTANCE_ADVANTAGE_METERS,
            )
            if farther[1] >= required_distance:
                return direction
        return None

    def _trace_to_junction(self, sign_id, next_node_id):
        """Return (junction id or None, measured distance/lower bound).

        An incomplete/dead-end branch gives only the distance traversed, never
        infinity. It cannot beat a closer junction without enough evidence.
        """
        previous, current = sign_id, next_node_id
        visited = {sign_id}
        distance = 0.0
        while current not in visited:
            distance += haversine_distance(
                *self.get_node_coordinates(previous), *self.get_node_coordinates(current)
            )
            if distance > CONTEXT_RADIUS_METERS:
                return None, float(CONTEXT_RADIUS_METERS)
            if current in self.incomplete_road_nodes:
                return None, distance
            neighbors = self.road_neighbors.get(current, set())
            if len(neighbors) >= 3:
                return current, distance
            # Do not look past another stopping point to a different junction.
            if self.nodes[current].get("tags", {}).get("highway") in {"stop", "give_way"}:
                return None, distance
            if len(neighbors) != 2:
                return None, distance
            visited.add(current)
            following = neighbors - {previous}
            if len(following) != 1:
                return None, distance
            previous, current = current, following.pop()
        return None, distance

    def determine_direction_by_way_intersections(self, give_way_node_id, way_id):
        return self.determine_give_way_direction(give_way_node_id, way_id)

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

    def calculate_rotation_angle(self, give_way_node_id, way_id, direction=None):
        if direction is None:
            direction = self.determine_give_way_direction(give_way_node_id, way_id)
        if direction not in {"forward", "backward"}:
            return None
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
        if not self.is_road({"tags": tags}):
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
    return challenge.addTask(t)


def create_overpass_query(sign_type):
    if sign_type not in ("give_way", "stop"):
        raise ValueError(f"Unsupported sign type: {sign_type}")
    areas = "\n".join(
        f'    node["highway"="{sign_type}"][!"direction"](area:{area_id});'
        for area_id in SEARCH_AREAS
    )
    return f"[out:json][timeout:250];\n(\n{areas}\n);\nout body;"


def create_context_query(node_ids):
    """Load complete road topology within the inference search radius.

    Only loading parents of sign ways misses junctions beyond a way split.
    Keep all immediate parents too, so separately drawn signs can be rejected.
    """
    ids = ",".join(str(int(node_id)) for node_id in sorted(set(node_ids)))
    if not ids:
        raise ValueError("At least one sign node is required")
    return (
        f"[out:json][timeout:250];\nnode(id:{ids})->.signs;\n(\n"
        "  way(bn.signs);\n"
        f'  way(around.signs:{CONTEXT_RADIUS_METERS})["highway"];\n'
        ");\n(._;>;);\nout body;"
    )


def populate_challenge(challenge, data_handler, sign_type):
    if sign_type not in ("give_way", "stop"):
        raise ValueError(f"Unsupported sign type: {sign_type}")
    if challenge.limit_reached:
        return
    get_sign_nodes = (
        data_handler.get_give_way_nodes if sign_type == "give_way"
        else data_handler.get_stop_nodes
    )
    icon_type = "yield" if sign_type == "give_way" else "stop"
    for way in tqdm(data_handler.get_ways()):
        if challenge.limit_reached:
            return
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
            if challenge.limit_reached:
                return
            # Recursing from a way also returns signs that were not selected.
            if (data_handler.candidate_node_ids is not None
                    and sign_node not in data_handler.candidate_node_ids):
                continue
            tags = data_handler.find_node_by_id(sign_node).get("tags", {})
            if "direction" in tags or "stop:direction" in tags:
                continue
            if data_handler.isFirstOrLastNodeInWay(sign_node, way_id):
                continue
            direction = data_handler.determine_give_way_direction(sign_node, way_id)
            if direction is None:
                continue
            angle = data_handler.calculate_rotation_angle(sign_node, way_id, direction)
            if angle is None:
                continue
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
            if challenge.limit_reached:
                return


def main(output_path=None, overpass=None):
    challenge = mrcb.Challenge()
    overpass = overpass if overpass is not None else Overpass()
    for sign_type in ("give_way", "stop"):
        if challenge.limit_reached:
            break
        print(f"Downloading {sign_type} data from Overpass API...")
        candidates = overpass.getElementsFromQuery(create_overpass_query(sign_type))
        candidate_ids = sorted({
            element["id"] for element in candidates
            if element["type"] == "node"
            and element.get("tags", {}).get("highway") == sign_type
            and "direction" not in element.get("tags", {})
            and "stop:direction" not in element.get("tags", {})
        })
        for offset in range(0, len(candidate_ids), CONTEXT_BATCH_SIZE):
            if challenge.limit_reached:
                break
            batch = candidate_ids[offset:offset + CONTEXT_BATCH_SIZE]
            elements = overpass.getElementsFromQuery(create_context_query(batch))
            data_handler = OSMDataHandler({"elements": elements}, candidate_node_ids=batch)
            print("Sorting ways...")
            populate_challenge(challenge, data_handler, sign_type)
    # A reached limit is a successful partial run; download errors still leave
    # the previous output untouched.
    challenge.saveToFile(DEFAULT_OUTPUT_PATH if output_path is None else output_path)
    return challenge


if __name__ == "__main__":
    main()
