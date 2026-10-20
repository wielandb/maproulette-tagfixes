import sys
import math
import random
import copy
import argparse
import json
import re
from bisect import bisect_left, bisect_right
from time import sleep
from pathlib import Path
from typing import Any, Dict, List

from tqdm import tqdm
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from shared import challenge_builder as mrcb  # noqa: E402


# Area id for Germany to keep the query reasonably sized. Adjust if needed.
SEARCH_AREA_ID = 3600051477
# Independently mapped equipment and access infrastructure described in:
# https://wiki.openstreetmap.org/wiki/DE:Leitfaden_-_Barrierefreiheit_an_Haltestellen
# Values are either exact strings or regular expressions shared by Overpass and
# the local matcher. These are review candidates, not proof of station ownership.
TARGET_TAG_SETS = [
    {"amenity": "shelter"},
    {"amenity": "bench"},
    {"amenity": "waste_basket"},
    {"amenity": "vending_machine", "vending": re.compile(r"(^|;)[ ]*public_transport_tickets[ ]*(;|$)")},
    {"highway": "elevator"},
    {"departures_board": re.compile(r"^(yes|timetable|realtime|delay)$")},
    {"passenger_information_display": "yes"},
    {"tourism": "information", "information": "board", "board_type": "public_transport"},
    {"tourism": "information", "information": re.compile(r"^(phone|office)$"), "information:public_transport": "yes"},
    {"tourism": "information", "information": "map", "map_type": "public_transport"},
    {"tourism": "information", "information": "tactile_map"},
    {"emergency": "phone"},
    {"tickets:public_transport": re.compile(r"^(yes|only)$")},
    {"amenity": "taxi"},
    {"amenity": "toilets"},
    {"amenity": "locker", "locker": re.compile(r"^(luggage|handbag)$")},
    {"amenity": "trolley_bay"},
    {"amenity": "parking"},
    {"amenity": "bicycle_parking"},
    # Ramps use footway/path; steps also cover escalators and stair lifts.
    # Portable boarding aids are platform attributes, not additional objects.
    {"highway": re.compile(r"^(footway|path|corridor|steps|crossing)$")},
    {"railway": re.compile(r"^(subway_entrance|train_station_entrance|crossing|tram_crossing)$")},
    {"indoor": "door"},
    {"entrance": re.compile(r"^(yes|main|secondary|service|emergency|exit|staircase)$")},
    {"barrier": re.compile(r"^(step|kerb|cycle_barrier)$")},
    {"tactile_paving": re.compile(r"^(yes|contrasted|incorrect|primitive)$")},
]
# Displays and boarding aids can be attributes of a platform or station. Never
# append those carriers as empty-role equipment, including lifecycle variants.
EXCLUDED_TAG_SETS = [
    {prefix + key: re.compile(pattern)}
    for prefix in ("", "disused:", "abandoned:", "construction:", "proposed:")
    for key, pattern in (
        ("public_transport", r"^(platform|station|stop_position|stop_area|stop_area_group)$"),
        ("railway", r"^(platform|station|halt|stop|tram_stop)$"),
        ("highway", r"^(bus_stop|platform)$"),
    )
]
# Radius to look for candidate objects around stations (meters)
OBJECT_TO_STATION_RADIUS = 200
# Radius to look for a stop_area relation around a candidate object (meters)
STOP_AREA_SEARCH_RADIUS = 300
# Radius to collect stop_area relations around stations (meters)
STOP_AREA_AROUND_STATION_RADIUS = 400
STATION_BATCH_SIZE = 100
OUTPUT_FILE = SCRIPT_DIR / "add_objects_to_stop_area.json"

# Simple styling so objects-to-add and the relation are visually distinct
OBJECT_STYLE = {"marker-color": "#d14334", "marker-size": "medium", "marker-symbol": "star"}
STOP_AREA_STYLE = {"stroke": "#2563eb", "stroke-width": 3, "stroke-opacity": 0.85, "fill": "#93c5fd", "fill-opacity": 0.2}


def apply_style(properties: Dict[str, Any], style: Dict[str, str]) -> Dict[str, Any]:
    styled = dict(properties)
    styled.update(style)
    return styled


def haversine_distance(lat1, lon1, lat2, lon2):
    # Calculate great-circle distance between two points on Earth
    r = 6371000  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def station_selection(station_bbox=None, stations=None):
    if stations is not None:
        if station_bbox is not None:
            raise ValueError("Specify station IDs or a bounding box, not both")
        ids = {kind: set() for kind in ("node", "way", "relation")}
        for station in stations:
            kind, osm_id = station.get("type"), station.get("id")
            if kind not in ids or isinstance(osm_id, bool) or not isinstance(osm_id, int) or osm_id < 1:
                raise ValueError("Station selection contains an invalid type or OSM ID")
            ids[kind].add(osm_id)
        selectors = [f"{kind}(id:{','.join(map(str, sorted(values)))});" for kind, values in ids.items() if values]
        return "(\n" + "\n".join(selectors or ["node(id:0);"]) + "\n)->.stations;"
    if station_bbox is None:
        return f'area(id:{SEARCH_AREA_ID})->.searchArea;\nnwr["railway"="station"](area.searchArea)->.stations;'
    if len(station_bbox) != 4:
        raise ValueError("Station bounding box must be south, west, north, east")
    south, west, north, east = station_bbox
    if (any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in station_bbox)
            or not (-90 <= south < north <= 90 and -180 <= west < east <= 180)):
        raise ValueError("Station bounding box must be south, west, north, east within valid coordinates")
    coordinates = ",".join(str(value) for value in station_bbox)
    return f'nwr["railway"="station"]({coordinates})->.stations;'


def build_station_query():
    return f"[out:json][timeout:180];\n{station_selection()}\n.stations out center;"


def tag_set_filters(tag_set):
    """Render the same exact/regex conditions that tag_set_matches evaluates."""
    filters = []
    for key, value in tag_set.items():
        operator = "~" if isinstance(value, re.Pattern) else "="
        expected = value.pattern if isinstance(value, re.Pattern) else value
        filters.append(f"[{json.dumps(key)}{operator}{json.dumps(expected)}]")
    return "".join(filters)


def tag_set_matches(tags, tag_set):
    for key, expected in tag_set.items():
        value = tags.get(key)
        if isinstance(expected, re.Pattern):
            if not isinstance(value, str) or expected.search(value) is None:
                return False
        elif value != expected:
            return False
    return True


def matching_target_tag_set(tags):
    if any(tag_set_matches(tags, tag_set) for tag_set in EXCLUDED_TAG_SETS):
        return None
    return next((tag_set for tag_set in TARGET_TAG_SETS if tag_set_matches(tags, tag_set)), None)


def build_overpass_query(station_bbox=None, stations=None):
    if not TARGET_TAG_SETS:
        raise ValueError("TARGET_TAG_SETS must contain at least one tag set")

    object_queries = []
    for tag_set in TARGET_TAG_SETS:
        filter_str = tag_set_filters(tag_set)
        object_queries.append(f'  node{filter_str}(around.stations:{OBJECT_TO_STATION_RADIUS});')
        object_queries.append(f'  way{filter_str}(around.stations:{OBJECT_TO_STATION_RADIUS});')
        object_queries.append(f'  relation{filter_str}(around.stations:{OBJECT_TO_STATION_RADIUS});')

    object_query_block = "\n".join(object_queries)
    excluded_query_block = "\n".join(
        f"  nwr.candidate_objects{tag_set_filters(tag_set)};"
        for tag_set in EXCLUDED_TAG_SETS
    )

    return f"""
[out:json][timeout:180];
{station_selection(station_bbox=station_bbox, stations=stations)}
relation["public_transport"="stop_area"](around.stations:{STOP_AREA_AROUND_STATION_RADIUS})->.stop_areas;
(
{object_query_block}
)->.candidate_objects;
(
{excluded_query_block}
)->.attribute_carriers;
(.candidate_objects; - .attribute_carriers;)->.candidate_objects;
(
  node(r.stop_areas);
  way(r.stop_areas);
  relation(r.stop_areas);
)->.objects_with_stop_area;
(.candidate_objects; - .objects_with_stop_area;)->.objects_without_stop_area;
(
  .objects_without_stop_area;
  .stop_areas;
);
out body geom;
"""


def collect_challenge_elements(overpass_client, station_bbox=None):
    if station_bbox is not None:
        return overpass_client.getElementsFromQuery(build_overpass_query(station_bbox=station_bbox))

    stations = overpass_client.getElementsFromQuery(build_station_query())
    # Validate every returned ID, including stations without a usable center.
    station_selection(stations=stations)

    def position(station):
        located = ensure_lat_lon(station)
        return (located["lat"], located["lon"], station["type"], station["id"]) if located else (91, 181, station["type"], station["id"])

    unique_stations = {(station["type"], station["id"]): station for station in stations}
    stations = sorted(unique_stations.values(), key=position)
    print(f"[main] Selected {len(stations)} stations inside Germany")
    elements = {}
    batches = math.ceil(len(stations) / STATION_BATCH_SIZE)
    for first in range(0, len(stations), STATION_BATCH_SIZE):
        batch = stations[first:first + STATION_BATCH_SIZE]
        print(f"[main] Querying station batch {first // STATION_BATCH_SIZE + 1}/{batches} ({len(batch)} stations)")
        result = overpass_client.getElementsFromQuery(build_overpass_query(stations=batch))
        for element in result:
            elements.setdefault((element["type"], element["id"]), element)

    # A member excluded in one batch can occur again in another. Only the
    # global union of all collected stop areas gives the original difference.
    assigned = set()
    for element in elements.values():
        if element.get("type") == "relation" and element.get("tags", {}).get("public_transport") == "stop_area":
            if not isinstance(element.get("members"), list):
                raise ValueError(f"Overpass stop_area {element['id']} has no complete members list")
            assigned.update((member["type"], member["ref"]) for member in element["members"])
    return [element for key, element in elements.items()
            if key not in assigned or (element.get("type") == "relation" and element.get("tags", {}).get("public_transport") == "stop_area")]


def ensure_lat_lon(element):
    try:
        positioned = mrcb.createElementCenterPoint(element)
        lat, lon = positioned["lat"], positioned["lon"]
        if (any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (lat, lon))
                or not (-90 <= lat <= 90 and -180 <= lon <= 180)):
            return None
        return positioned
    except (ValueError, KeyError, TypeError):
        return None


def get_geometry(element):
    # Prefer full geometry when available; otherwise fall back to center/latlon.
    try:
        if "geometry" in element:
            tmp = dict(element)
            tmp.pop("lat", None)
            tmp.pop("lon", None)
            return mrcb.getElementGeometry(tmp)
        mrcb.createElementCenterPoint(element)
    except (ValueError, KeyError, TypeError):
        return None
    return mrcb.getElementGeometry(element)


class StopAreaIndex:
    """Only inspect relation centers within the latitude span of the search radius."""

    def __init__(self, stop_areas):
        positioned = [area for area in stop_areas if ensure_lat_lon(area) is not None]
        positioned.sort(key=lambda area: area["lat"])
        self.stop_areas = positioned
        self.latitudes = [area["lat"] for area in positioned]

    def near_latitude(self, latitude):
        latitude_span = math.degrees(STOP_AREA_SEARCH_RADIUS / 6371000)
        first = bisect_left(self.latitudes, latitude - latitude_span)
        last = bisect_right(self.latitudes, latitude + latitude_span)
        return self.stop_areas[first:last]


def find_nearest_stop_area(obj, stop_areas):
    if ensure_lat_lon(obj) is None:
        return None, None
    lat = obj.get("lat")
    lon = obj.get("lon")
    if lat is None or lon is None:
        return None, None
    best = None
    best_distance = None
    nearby = stop_areas.near_latitude(lat) if isinstance(stop_areas, StopAreaIndex) else stop_areas
    for sa in nearby:
        if ensure_lat_lon(sa) is None:
            continue
        sa_lat = sa.get("lat")
        sa_lon = sa.get("lon")
        if sa_lat is None or sa_lon is None:
            continue
        distance = haversine_distance(lat, lon, sa_lat, sa_lon)
        if distance > STOP_AREA_SEARCH_RADIUS:
            continue
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best = sa
    return best, best_distance


def build_osc_add_members(fetch_helper, relation_cache, objects: List[Dict], stop_area):
    relation_id = stop_area["id"]

    if relation_id not in relation_cache:
        relation_cache[relation_id] = fetch_helper._fetch_current_element("relation", relation_id)
    base_relation = relation_cache[relation_id]

    if not isinstance(base_relation.get("members"), list):
        raise ValueError(f"Current relation {relation_id} has no complete members list")
    members = list(base_relation["members"])
    member_ids = {(member.get("type"), member.get("ref")) for member in members}
    updated_members = list(members)
    additions = 0
    for obj in objects:
        obj_type = obj["type"]
        obj_id = obj["id"]
        if (obj_type, obj_id) in member_ids:
            continue
        updated_members.append({"type": obj_type, "ref": obj_id, "role": ""})
        member_ids.add((obj_type, obj_id))
        additions += 1

    if additions == 0:
        raise ValueError(f"No new members to add to relation {relation_id}")

    updated_relation = copy.deepcopy(base_relation)
    updated_relation["members"] = updated_members

    osc_builder = mrcb.OscBuilder()
    osc_builder.modify_elems.append(osc_builder._element_to_xml(updated_relation))
    return osc_builder.to_osc_change()


def prefetch_current_relations(relation_ids, relation_cache):
    """Use the editing API's multi-fetch endpoint, retaining individual fallbacks."""
    ids = [relation_id for relation_id in relation_ids if relation_id not in relation_cache]
    if len(ids) < 2:
        return
    for first in range(0, len(ids), 100):
        batch = ids[first:first + 100]
        for attempt in range(3):
            try:
                response = requests.get(
                    "https://api.openstreetmap.org/api/0.6/relations.json",
                    params={"relations": ",".join(str(relation_id) for relation_id in batch)},
                    headers=mrcb.Overpass.REQUEST_HEADERS,
                    timeout=(10, 30),
                )
            except requests.RequestException:
                if attempt == 2:
                    raise
            else:
                if response.status_code != 429 and response.status_code < 500:
                    break
                if attempt == 2:
                    response.raise_for_status()
            delay = 5 * 2 ** attempt
            print(f"[warn] Current-relation multi-fetch failed, retrying in {delay}s")
            sleep(delay)
        if response.status_code in (400, 404, 414):
            print(f"[warn] Relation multi-fetch returned HTTP {response.status_code}; falling back to individual reads for {len(batch)} relations")
            continue
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
            raise ValueError("OSM relation multi-fetch returned an invalid response")
        fetched = {}
        for element in data["elements"]:
            if (not isinstance(element, dict) or element.get("type") != "relation"
                    or not isinstance(element.get("id"), int) or isinstance(element.get("id"), bool)
                    or element.get("id") not in batch or not isinstance(element.get("version"), int)
                    or isinstance(element.get("version"), bool) or element["version"] < 1
                    or (element.get("visible") is not False and not isinstance(element.get("members"), list))
                    or element["id"] in fetched):
                raise ValueError("OSM relation multi-fetch returned an invalid or duplicate relation")
            fetched[element["id"]] = element
        relation_cache.update(fetched)
        if len(fetched) != len(batch):
            print(f"[warn] Relation multi-fetch omitted {len(batch) - len(fetched)} relations; these will be read individually")
        print(f"[main] Loaded current relations: {min(first + len(batch), len(ids))}/{len(ids)}")


def matches_target_tags(tags: Dict[str, str]) -> bool:
    return matching_target_tag_set(tags) is not None


def describe_object(obj: Dict[str, str]) -> str:
    tags = obj.get("tags", {})
    matching = matching_target_tag_set(tags)
    if matching:
        tag_desc = ", ".join(f"{key}={tags[key]}" for key in matching)
    else:
        tag_desc = ", ".join(f"{k}={v}" for k, v in list(tags.items())[:3])
    return f"{obj['type']}/{obj['id']} ({tag_desc})"


def build_relation_member_features(overpass_client, relation_id: int, stop_area=None) -> List[mrcb.GeoFeature]:
    # out geom already includes direct member coordinates. Reuse them instead
    # of running an additional Overpass query for every generated task.
    elements = []
    inline_members = []
    if stop_area is not None:
        for member in stop_area.get("members", []):
            if member.get("type") not in ("node", "way"):
                continue
            source = dict(member, id=member.get("ref"))
            if get_geometry(source) is None:
                break
            inline_members.append(source)
        else:
            elements = [stop_area, *inline_members]

    query = f"""
    [out:json][timeout:180];
    relation({relation_id});
    (._;>;);
    out body geom;
    """
    if not elements:
        try:
            elements = overpass_client.getElementsFromQuery(query)
        except Exception as exc:
            print(f"[warn] Overpass fetch for members of relation {relation_id} failed: {exc}")
            return []

    nodes = {e["id"]: e for e in elements if e.get("type") == "node"}
    ways = {e["id"]: e for e in elements if e.get("type") == "way"}
    rel = next((e for e in elements if e.get("type") == "relation" and e.get("id") == relation_id), None)
    if not rel:
        return []

    member_features: List[mrcb.GeoFeature] = []
    for member in rel.get("members", []):
        mtype = member.get("type")
        ref = member.get("ref")
        role = member.get("role", "")
        source_el = None
        if mtype == "node":
            source_el = nodes.get(ref)
        elif mtype == "way":
            source_el = ways.get(ref)
        else:
            continue
        if not source_el:
            continue
        geom = get_geometry(source_el)
        if not geom:
            continue
        try:
            member_features.append(
                mrcb.GeoFeature.withId(
                    mtype,
                    ref,
                    geom,
                    properties=apply_style(
                        {
                            "role": role,
                            "public_transport": "stop_area_member",
                            "tags": source_el.get("tags", {}),
                        },
                        STOP_AREA_STYLE,
                    ),
                )
            )
        except Exception as exc:
            print(f"[warn] Failed to build feature for {mtype}/{ref} in relation {relation_id}: {exc}")
            continue
    return member_features


def main(overpass=None, output_file=None, station_bbox=None, max_tasks=None):
    if max_tasks is not None and (isinstance(max_tasks, bool) or not isinstance(max_tasks, int) or max_tasks < 1):
        raise ValueError("max_tasks must be a positive integer")
    op = overpass if overpass is not None else mrcb.Overpass()
    output_file = Path(output_file) if output_file is not None else OUTPUT_FILE
    print("[main] Running Overpass query...")
    elements = collect_challenge_elements(op, station_bbox=station_bbox)
    print(f"[main] Retrieved {len(elements)} elements")

    candidate_objects = []
    stop_areas = []
    for el in elements:
        tags = el.get("tags", {})
        if el.get("type") == "relation" and tags.get("public_transport") == "stop_area":
            if not isinstance(el.get("members"), list):
                raise ValueError(f"Overpass stop_area {el['id']} has no complete members list")
            stop_areas.append(el)
        elif matches_target_tags(tags):
            candidate_objects.append(el)

    print(f"[main] Candidate objects: {len(candidate_objects)}, stop_area relations: {len(stop_areas)}")
    random.shuffle(candidate_objects)

    challenge = mrcb.Challenge()
    fetch_helper = mrcb.OscBuilder()
    relation_cache = {}
    stop_area_index = StopAreaIndex(stop_areas)

    grouped = {}
    for obj in tqdm(candidate_objects):
        nearest_sa, distance = find_nearest_stop_area(obj, stop_area_index)
        if nearest_sa is None:
            continue
        grouped.setdefault(nearest_sa["id"], {"stop_area": nearest_sa, "objects": []})
        grouped[nearest_sa["id"]]["objects"].append({"element": obj, "distance": distance})

    print(f"[main] Grouped candidates into {len(grouped)} stop_area relations")
    relation_ids = list(grouped)
    prefetched_through = 0
    for relation_index, (sa_id, info) in enumerate(tqdm(grouped.items(), total=len(grouped))):
        if challenge.limit_reached:
            break
        if max_tasks is not None and len(challenge.tasks) >= max_tasks:
            break
        # Fetch only the next editing-API batch. Stop requesting further batches
        # when either the task count or serialized output budget is exhausted.
        if relation_index >= prefetched_through:
            remaining = challenge.max_tasks - len(challenge.tasks)
            if max_tasks is not None:
                remaining = min(remaining, max_tasks - len(challenge.tasks))
            prefetched_through = min(len(relation_ids), relation_index + min(100, remaining))
            prefetch_current_relations(relation_ids[relation_index:prefetched_through], relation_cache)
        stop_area = info["stop_area"]
        objects = info["objects"]
        try:
            # Overpass can lag behind the editing API. Do not advertise members
            # that were already added by someone since the Overpass snapshot.
            if sa_id not in relation_cache:
                relation_cache[sa_id] = fetch_helper._fetch_current_element("relation", sa_id)
        except mrcb.OSMElementNotFoundError as exc:
            print(f"[warn] Skipping missing relation/{sa_id}: {exc}")
            continue
        current_relation = relation_cache[sa_id]
        if (current_relation.get("type") != "relation" or current_relation.get("id") != sa_id
                or isinstance(current_relation.get("version"), bool)
                or not isinstance(current_relation.get("version"), int) or current_relation["version"] < 1):
            raise ValueError(f"OSM returned a different or invalid relation for stop_area {sa_id}")
        if current_relation.get("visible") is False or current_relation.get("tags", {}).get("public_transport") != "stop_area":
            print(f"[warn] Skipping relation/{sa_id}: it is no longer an existing stop_area")
            continue
        if not isinstance(current_relation.get("members"), list):
            raise ValueError(f"Current relation {sa_id} has no complete members list")
        existing_members = {(member.get("type"), member.get("ref")) for member in current_relation["members"]}
        objects = [entry for entry in objects if (entry["element"]["type"], entry["element"]["id"]) not in existing_members]
        if not objects:
            continue

        try:
            sa_geom = get_geometry(stop_area)
        except Exception as exc:
            print(f"[warn] Could not fetch geometry for stop_area {sa_id}: {exc}")
            continue
        if sa_geom is None:
            continue

        object_features = []
        visible_objects = []
        for obj_entry in objects:
            obj = obj_entry["element"]
            distance = obj_entry["distance"]
            try:
                obj_geom = get_geometry(obj)
            except Exception as exc:
                print(f"[warn] Could not fetch geometry for {obj['type']}/{obj['id']}: {exc}")
                continue
            if obj_geom is None:
                continue
            try:
                object_feature = mrcb.GeoFeature.withId(
                    obj["type"],
                    obj["id"],
                    obj_geom,
                    properties=apply_style(
                        {
                            "distance_to_stop_area_m": round(distance) if distance is not None else None,
                            "matching_tags": describe_object(obj),
                            "tags": obj.get("tags", {}),
                            "object_type": obj.get("type"),
                        },
                        OBJECT_STYLE,
                    ),
                )
            except ValueError as exc:
                print(f"[warn] Could not build feature for {obj['type']}/{obj['id']}: {exc}")
                continue
            object_features.append(object_feature)
            visible_objects.append(obj_entry)

        if not visible_objects:
            continue

        cooperative_work = build_osc_add_members(fetch_helper, relation_cache, [entry["element"] for entry in visible_objects], stop_area)

        member_features = build_relation_member_features(op, sa_id, stop_area=stop_area)
        relation_display_geom = member_features[0].geometry if member_features else sa_geom
        object_lines = "\n".join(f"- {describe_object(entry['element'])}" for entry in visible_objects)
        task_instruction = (
            f"Prüfe die markierten Objekte (insgesamt {len(visible_objects)}) auf Zugehörigkeit "
            f"zur Stop-Area-Relation {sa_id}. Füge nur tatsächlich zu dieser Haltestelle gehörende "
            f"Objekte als letzte Mitglieder mit leerer Rolle hinzu. Nähe allein reicht nicht aus, "
            f"insbesondere bei Wegen, Zugängen, Parkplätzen und Toiletten. "
            f"Die vorbereitete Änderung enthält alle Vorschläge; entferne unpassende Objekte "
            f"vor dem Hochladen.\n{object_lines}"
        )
        main_feature = mrcb.GeoFeature.withId(
            "relation", sa_id, relation_display_geom,
            properties=apply_style({
                "public_transport": "stop_area",
                "name": stop_area.get("tags", {}).get("name", ""),
                "task_instruction": task_instruction,
                "objects_count": len(visible_objects),
                "target_stop_area": str(sa_id),
                "tags": stop_area.get("tags", {}),
            }, STOP_AREA_STYLE),
        )

        if not challenge.addTask(
            mrcb.Task(
                mainFeature=main_feature,
                additionalFeatures=[*member_features, *object_features],
                cooperativeWork=cooperative_work,
            )
        ):
            break

    challenge.cap()
    challenge.saveToFile(output_file)
    print(f"[main] Saved {len(challenge.tasks)} tasks to {output_file}")
    return challenge


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate tasks for adding nearby objects to stop areas.")
    parser.add_argument("--bbox", type=float, nargs=4, metavar=("SOUTH", "WEST", "NORTH", "EAST"), help="Restrict the selected stations to this bounding box instead of Germany.")
    parser.add_argument("--output", type=Path, help="Write the generated challenge to this file.")
    parser.add_argument("--max-tasks", type=int, help="Stop after generating this many tasks.")
    args = parser.parse_args()
    main(output_file=args.output, station_bbox=args.bbox, max_tasks=args.max_tasks)
