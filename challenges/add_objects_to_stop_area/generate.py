import sys
import math
import random
import copy

from tqdm import tqdm

sys.path.append("../../shared")
import challenge_builder as mrcb  # noqa: E402


# Area id for Germany to keep the query reasonably sized. Adjust if needed.
SEARCH_AREA_ID = 3600051477
# Radius to look for shelters around stations (meters)
SHELTER_TO_STATION_RADIUS = 200
# Radius to look for a stop_area relation around a shelter (meters)
STOP_AREA_SEARCH_RADIUS = 300
# Radius to collect stop_area relations around stations (meters)
STOP_AREA_AROUND_STATION_RADIUS = 400
OUTPUT_FILE = "add_objects_to_stop_area.json"


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
    return f"""
[out:json][timeout:180];
area(id:{SEARCH_AREA_ID})->.searchArea;
nwr["railway"="station"](area.searchArea)->.stations;
relation["public_transport"="stop_area"](around.stations:{STOP_AREA_AROUND_STATION_RADIUS})->.stop_areas;
(
  node["amenity"="shelter"](around.stations:{SHELTER_TO_STATION_RADIUS});
  way["amenity"="shelter"](around.stations:{SHELTER_TO_STATION_RADIUS});
  relation["amenity"="shelter"](around.stations:{SHELTER_TO_STATION_RADIUS});
)->.shelters;
(
  rel.stop_areas(bn.shelters);
  rel.stop_areas(bw.shelters);
  rel.stop_areas(br.shelters);
)->.shelters_with_stop_area;
(.shelters; - .shelters_with_stop_area;)->.candidate_shelters;
(
  .candidate_shelters;
  .stop_areas;
);
out body center;
"""


def ensure_lat_lon(element):
    try:
        return mrcb.createElementCenterPoint(element)
    except ValueError:
        return None


def get_geometry(element):
    ensure_lat_lon(element)
    return mrcb.getElementGeometry(element)


def find_nearest_stop_area(shelter, stop_areas):
    ensure_lat_lon(shelter)
    lat = shelter.get("lat")
    lon = shelter.get("lon")
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


def build_osc_add_member(fetch_helper, relation_cache, shelter, stop_area):
    shelter_type = shelter["type"]
    shelter_id = shelter["id"]
    relation_id = stop_area["id"]

    if relation_id not in relation_cache:
        relation_cache[relation_id] = fetch_helper._fetch_current_element("relation", relation_id)
    base_relation = relation_cache[relation_id]

    members = list(base_relation.get("members", []))
    # Skip if already member in fresh relation data (shouldn't happen after Overpass filter)
    if any(m.get("type") == shelter_type and m.get("ref") == shelter_id for m in members):
        raise ValueError(f"{shelter_type}/{shelter_id} already in relation {relation_id}")

    updated_relation = copy.deepcopy(base_relation)
    updated_members = list(updated_relation.get("members", []))
    updated_members.append({"type": shelter_type, "ref": shelter_id, "role": ""})
    updated_relation["members"] = updated_members

    osc_builder = mrcb.OscBuilder()
    osc_builder.modify_elems.append(osc_builder._element_to_xml(updated_relation))
    return osc_builder.to_osc_change()


def main():
    op = mrcb.Overpass()
    print("[main] Running Overpass query...")
    elements = op.getElementsFromQuery(build_overpass_query())
    print(f"[main] Retrieved {len(elements)} elements")

    shelters = []
    stop_areas = []
    for el in elements:
        tags = el.get("tags", {})
        if tags.get("amenity") == "shelter":
            shelters.append(el)
        elif el.get("type") == "relation" and tags.get("public_transport") == "stop_area":
            stop_areas.append(el)

    print(f"[main] Candidate shelters: {len(shelters)}, stop_area relations: {len(stop_areas)}")
    random.shuffle(shelters)

    challenge = mrcb.Challenge()
    fetch_helper = mrcb.OscBuilder()
    relation_cache = {}

    for shelter in tqdm(shelters):
        nearest_sa, distance = find_nearest_stop_area(shelter, stop_areas)
        if nearest_sa is None:
            continue
        try:
            cooperative_work = build_osc_add_member(fetch_helper, relation_cache, shelter, nearest_sa)
        except Exception as exc:
            print(f"[warn] Could not build OSC for shelter {shelter['type']}/{shelter['id']}: {exc}")
            continue

        main_geom = get_geometry(shelter)
        main_feature = mrcb.GeoFeature.withId(
            shelter["type"],
            shelter["id"],
            main_geom,
            properties={
                "task_instruction": f"Füge diesen shelter zur Stop-Area-Relation {nearest_sa['id']} hinzu (als letztes Element).",
                "target_stop_area": str(nearest_sa["id"]),
                "distance_to_stop_area_m": round(distance) if distance is not None else None,
            },
        )

        additional_features = []
        try:
            sa_geom = get_geometry(nearest_sa)
            additional_features.append(
                mrcb.GeoFeature.withId(
                    "relation",
                    nearest_sa["id"],
                    sa_geom,
                    properties={
                        "public_transport": "stop_area",
                        "name": nearest_sa.get("tags", {}).get("name", ""),
                    },
                )
            )
        except Exception:
            pass

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
