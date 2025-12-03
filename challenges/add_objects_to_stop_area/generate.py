import sys
import math
import random
import copy
from typing import Any, Dict, List

from tqdm import tqdm

sys.path.append("../../shared")
import challenge_builder as mrcb  # noqa: E402


# Area id for Germany to keep the query reasonably sized. Adjust if needed.
SEARCH_AREA_ID = 3600051477
# Tags that should be added to stop_area relations (extend as needed)
TARGET_TAG_SETS = [
    {"amenity": "shelter"},
    {"amenity": "bench"},
    {"amenity":"waste_basket"},
]
# Radius to look for candidate objects around stations (meters)
OBJECT_TO_STATION_RADIUS = 200
# Radius to look for a stop_area relation around a candidate object (meters)
STOP_AREA_SEARCH_RADIUS = 300
# Radius to collect stop_area relations around stations (meters)
STOP_AREA_AROUND_STATION_RADIUS = 400
OUTPUT_FILE = "add_objects_to_stop_area.json"

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


def build_overpass_query():
    if not TARGET_TAG_SETS:
        raise ValueError("TARGET_TAG_SETS must contain at least one tag set")

    tag_filters = []
    for tag_set in TARGET_TAG_SETS:
        filter_str = "".join(f'["{k}"="{v}"]' for k, v in tag_set.items())
        tag_filters.append(filter_str)

    object_queries = []
    for filter_str in tag_filters:
        object_queries.append(f'  node{filter_str}(around.stations:{OBJECT_TO_STATION_RADIUS});')
        object_queries.append(f'  way{filter_str}(around.stations:{OBJECT_TO_STATION_RADIUS});')
        object_queries.append(f'  relation{filter_str}(around.stations:{OBJECT_TO_STATION_RADIUS});')

    object_query_block = "\n".join(object_queries)

    return f"""
[out:json][timeout:180];
area(id:{SEARCH_AREA_ID})->.searchArea;
nwr["railway"="station"](area.searchArea)->.stations;
relation["public_transport"="stop_area"](around.stations:{STOP_AREA_AROUND_STATION_RADIUS})->.stop_areas;
(
{object_query_block}
)->.candidate_objects;
(
  rel.stop_areas(bn.candidate_objects);
  rel.stop_areas(bw.candidate_objects);
  rel.stop_areas(br.candidate_objects);
)->.objects_with_stop_area;
(.candidate_objects; - .objects_with_stop_area;)->.objects_without_stop_area;
(
  .objects_without_stop_area;
  .stop_areas;
);
out body geom;
"""


def ensure_lat_lon(element):
    try:
        return mrcb.createElementCenterPoint(element)
    except ValueError:
        return None


def get_geometry(element):
    # Prefer full geometry when available; otherwise fall back to center/latlon.
    if "geometry" in element:
        tmp = dict(element)
        tmp.pop("lat", None)
        tmp.pop("lon", None)
        return mrcb.getElementGeometry(tmp)
    try:
        mrcb.createElementCenterPoint(element)
    except ValueError:
        return None
    return mrcb.getElementGeometry(element)


def find_nearest_stop_area(obj, stop_areas):
    ensure_lat_lon(obj)
    lat = obj.get("lat")
    lon = obj.get("lon")
    if lat is None or lon is None:
        return None, None
    best = None
    best_distance = None
    for sa in stop_areas:
        ensure_lat_lon(sa)
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

    members = list(base_relation.get("members", []))
    updated_members = list(members)
    additions = 0
    for obj in objects:
        obj_type = obj["type"]
        obj_id = obj["id"]
        if any(m.get("type") == obj_type and m.get("ref") == obj_id for m in members):
            continue
        updated_members.append({"type": obj_type, "ref": obj_id, "role": ""})
        additions += 1

    if additions == 0:
        raise ValueError(f"No new members to add to relation {relation_id}")

    updated_relation = copy.deepcopy(base_relation)
    updated_relation["members"] = updated_members

    osc_builder = mrcb.OscBuilder()
    osc_builder.modify_elems.append(osc_builder._element_to_xml(updated_relation))
    return osc_builder.to_osc_change()


def matches_target_tags(tags: Dict[str, str]) -> bool:
    for tag_set in TARGET_TAG_SETS:
        if all(tags.get(k) == v for k, v in tag_set.items()):
            return True
    return False


def describe_object(obj: Dict[str, str]) -> str:
    tags = obj.get("tags", {})
    matching = None
    for tag_set in TARGET_TAG_SETS:
        if all(tags.get(k) == v for k, v in tag_set.items()):
            matching = tag_set
            break
    if matching:
        tag_desc = ", ".join(f"{k}={v}" for k, v in matching.items())
    else:
        tag_desc = ", ".join(f"{k}={v}" for k, v in list(tags.items())[:3])
    return f"{obj['type']}/{obj['id']} ({tag_desc})"


def build_relation_member_features(overpass_client, relation_id: int) -> List[mrcb.GeoFeature]:
    query = f"""
    [out:json][timeout:180];
    relation({relation_id});
    (._;>;);
    out body geom;
    """
    try:
        elements = overpass_client.getElementsFromQuery(query)
    except Exception as exc:
        print(f"[warn] Overpass fetch for members of relation {relation_id} failed: {exc}")
        return []

    nodes = {e["id"]: e for e in elements if e.get("type") == "node"}
    ways = {e["id"]: e for e in elements if e.get("type") == "way"}
    rel = next((e for e in elements if e.get("type") == "relation"), None)
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


def main():
    op = mrcb.Overpass()
    print("[main] Running Overpass query...")
    elements = op.getElementsFromQuery(build_overpass_query())
    print(f"[main] Retrieved {len(elements)} elements")

    candidate_objects = []
    stop_areas = []
    for el in elements:
        tags = el.get("tags", {})
        if el.get("type") == "relation" and tags.get("public_transport") == "stop_area":
            stop_areas.append(el)
        elif matches_target_tags(tags):
            candidate_objects.append(el)

    print(f"[main] Candidate objects: {len(candidate_objects)}, stop_area relations: {len(stop_areas)}")
    random.shuffle(candidate_objects)

    challenge = mrcb.Challenge()
    fetch_helper = mrcb.OscBuilder()
    relation_cache = {}

    grouped = {}
    for obj in tqdm(candidate_objects):
        nearest_sa, distance = find_nearest_stop_area(obj, stop_areas)
        if nearest_sa is None:
            continue
        grouped.setdefault(nearest_sa["id"], {"stop_area": nearest_sa, "objects": []})
        grouped[nearest_sa["id"]]["objects"].append({"element": obj, "distance": distance})

    for sa_id, info in tqdm(grouped.items(), total=len(grouped)):
        stop_area = info["stop_area"]
        objects = info["objects"]
        try:
            cooperative_work = build_osc_add_members(
                fetch_helper,
                relation_cache,
                [o["element"] for o in objects],
                stop_area,
            )
        except Exception as exc:
            print(f"[warn] Could not build OSC for stop_area {sa_id}: {exc}")
            continue

        try:
            sa_geom = get_geometry(stop_area)
        except Exception as exc:
            print(f"[warn] Could not fetch geometry for stop_area {sa_id}: {exc}")
            continue

        member_features = build_relation_member_features(op, sa_id)
        relation_display_geom = member_features[0].geometry if member_features else sa_geom

        object_lines = "\n".join(f"- {describe_object(o['element'])}" for o in objects)
        task_instruction = (
            f"Füge alle markierten Objekte (insgesamt {len(objects)}) als letzte Mitglieder "
            f"zur Stop-Area-Relation {sa_id} hinzu:\n{object_lines}"
        )

        main_feature = mrcb.GeoFeature.withId(
            "relation",
            sa_id,
            relation_display_geom,
            properties=apply_style(
                {
                    "public_transport": "stop_area",
                    "name": stop_area.get("tags", {}).get("name", ""),
                    "task_instruction": task_instruction,
                    "objects_count": len(objects),
                    "target_stop_area": str(sa_id),
                    "tags": stop_area.get("tags", {}),
                },
                STOP_AREA_STYLE,
            ),
        )

        additional_features = list(member_features)
        for obj_entry in objects:
            obj = obj_entry["element"]
            distance = obj_entry["distance"]
            try:
                obj_geom = get_geometry(obj)
            except Exception as exc:
                print(f"[warn] Could not fetch geometry for {obj['type']}/{obj['id']}: {exc}")
                continue
            additional_features.append(
                mrcb.GeoFeature.withId(
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
            )

        if not additional_features:
            continue

        challenge.addTask(
            mrcb.Task(
                mainFeature=main_feature,
                additionalFeatures=additional_features,
                cooperativeWork=cooperative_work,
            )
        )

    challenge.cap()
    challenge.saveToFile(OUTPUT_FILE)
    print(f"[main] Saved {len(challenge.tasks)} tasks to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
