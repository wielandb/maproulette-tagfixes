import base64
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stop_area_equipment", ROOT / "challenges/add_objects_to_stop_area/generate.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class StopAreaEquipmentTests(unittest.TestCase):
    def test_equipment_and_access_infrastructure_are_candidates(self):
        cases = [
            {"amenity": value}
            for value in (
                "bench", "shelter", "waste_basket", "taxi", "toilets",
                "parking", "bicycle_parking", "trolley_bay",
            )
        ] + [
            {"amenity": "vending_machine", "vending": value}
            for value in (
                "public_transport_tickets", "public_transport_tickets;parking_tickets",
                "parking_tickets;public_transport_tickets", "parking_tickets; public_transport_tickets ;snacks",
            )
        ] + [
            {"highway": value}
            for value in ("elevator", "footway", "path", "corridor", "steps", "crossing")
        ] + [
            {"departures_board": value}
            for value in ("yes", "timetable", "realtime", "delay")
        ] + [
            {"passenger_information_display": "yes"},
            {"tourism": "information", "information": "board", "board_type": "public_transport"},
            {"tourism": "information", "information": "map", "map_type": "public_transport"},
            {"tourism": "information", "information": "tactile_map"},
            {"emergency": "phone"},
            {"shop": "ticket", "tickets:public_transport": "yes"},
            {"shop": "ticket", "tickets:public_transport": "only"},
            {"shop": "kiosk", "tickets:public_transport": "yes"},
            {"tickets:public_transport": "only"},
            {"indoor": "door"},
        ] + [
            {"tourism": "information", "information": value, "information:public_transport": "yes"}
            for value in ("phone", "office")
        ] + [
            {"amenity": "locker", "locker": value}
            for value in ("luggage", "handbag")
        ] + [
            {"railway": value}
            for value in ("train_station_entrance", "subway_entrance", "crossing", "tram_crossing")
        ] + [
            {"entrance": value}
            for value in ("yes", "main", "secondary", "service", "emergency", "exit", "staircase")
        ] + [
            {"tactile_paving": value}
            for value in ("yes", "contrasted", "incorrect", "primitive")
        ] + [
            {"barrier": value}
            for value in ("step", "kerb", "cycle_barrier")
        ]
        for tags in cases:
            with self.subTest(tags=tags):
                self.assertTrue(generator.matches_target_tags(tags))
                description = generator.describe_object({"type": "node", "id": 20, "tags": tags})
                for key, value in tags.items():
                    if key == "shop":
                        # The public-transport ticket service identifies the
                        # candidate independently of the surrounding shop type.
                        continue
                    self.assertIn(f"{key}={value}", description)
                self.assertNotIn("re.compile", description)

    def test_attributes_negative_values_and_unrelated_objects_are_not_candidates(self):
        cases = [
            {}, {"departures_board": "no"}, {"passenger_information_display": "no"},
            {"speech_output": "yes"}, {"wheelchair": "yes"}, {"bench": "yes"},
            {"ramp": "yes", "ramp:portable": "yes"},
            {"platform_lift": "vertical", "platform_lift:portable": "yes"},
            {"platform_lift": "no", "platform_lift:portable": "yes"},
            {"public_transport": "platform", "ramp": "yes", "ramp:portable": "yes"},
            {"amenity": "vending_machine", "vending": "snacks"},
            {"amenity": "vending_machine", "vending": "not_public_transport_tickets"},
            {"amenity": "vending_machine", "vending": "public_transport_tickets_extra"},
            {"shop": "ticket"}, {"shop": "ticket", "tickets:public_transport": "no"},
            {"tickets:public_transport": "no"},
            {"tourism": "information", "information": "board"},
            {"tourism": "information", "information": "map"},
            {"tourism": "information", "information": "phone"},
            {"tourism": "information", "information": "office", "information:public_transport": "no"},
            {"amenity": "locker", "locker": "bicycle"}, {"entrance": "no"},
            {"tactile_paving": "no"}, {"departures_board": None},
        ]
        for tags in cases:
            with self.subTest(tags=tags):
                self.assertFalse(generator.matches_target_tags(tags))

    def test_platform_and_station_attributes_do_not_become_equipment(self):
        carrier_values = {
            "public_transport": ("platform", "station", "stop_position", "stop_area", "stop_area_group"),
            "railway": ("platform", "station", "halt", "stop", "tram_stop"),
            "highway": ("bus_stop", "platform"),
        }
        for prefix in ("", "disused:", "abandoned:", "construction:", "proposed:"):
            for key, values in carrier_values.items():
                for value in values:
                    tags = {prefix + key: value, "departures_board": "yes", "tactile_paving": "yes"}
                    with self.subTest(tags=tags):
                        self.assertFalse(generator.matches_target_tags(tags))

    def test_overpass_selects_equipment_for_all_osm_types_and_excludes_attribute_carriers(self):
        query = generator.build_overpass_query()
        for osm_type in ("node", "way", "relation"):
            for selector in (
                '["amenity"="vending_machine"]["vending"~',
                '["highway"="elevator"]',
                '["departures_board"~',
                '["passenger_information_display"="yes"]',
                '["tourism"="information"]["information"="board"]["board_type"="public_transport"]',
                '["tourism"="information"]["information"="tactile_map"]',
                '["tickets:public_transport"~',
                '["emergency"="phone"]',
                '["amenity"="bicycle_parking"]',
                '["amenity"="trolley_bay"]',
            ):
                with self.subTest(osm_type=osm_type, selector=selector):
                    self.assertIn(osm_type + selector, query)

        vending_filter = re.search(r'\["vending"~("(?:\\.|[^"\\])*")\]', query)
        self.assertIsNotNone(vending_filter)
        vending_pattern = json.loads(vending_filter.group(1))
        self.assertRegex("parking_tickets;public_transport_tickets", vending_pattern)
        self.assertIsNone(re.search(vending_pattern, "not_public_transport_tickets"))
        for prefix in ("", "disused:", "abandoned:", "construction:", "proposed:"):
            for key in ("public_transport", "railway", "highway"):
                with self.subTest(prefix=prefix, key=key):
                    self.assertIn(f'nwr.candidate_objects["{prefix + key}"~', query)
        self.assertIn("(.candidate_objects; - .attribute_carriers;)", query)

    def test_generated_task_proposes_new_equipment_and_only_appends_new_members(self):
        relation = {
            "type": "relation", "id": 500, "version": 7,
            "bounds": {"minlat": 52.0, "maxlat": 52.001, "minlon": 13.0, "maxlon": 13.001},
            "tags": {"type": "public_transport", "public_transport": "stop_area", "name": "Test station"},
            "members": [
                {"type": "node", "ref": 1, "role": "stop", "lat": 52.0, "lon": 13.0},
                {"type": "way", "ref": 8, "role": "platform", "geometry": [
                    {"lat": 52.0, "lon": 13.0}, {"lat": 52.001, "lon": 13.001},
                ]},
            ],
        }
        current = copy.deepcopy(relation)
        current["version"] = 8
        current["tags"]["operator"] = "Current operator"
        current["members"].append({"type": "node", "ref": 21, "role": "ticket_machine"})
        original_current = copy.deepcopy(current)

        def node(osm_id, tags):
            return {"type": "node", "id": osm_id, "lat": 52.0, "lon": 13.0, "tags": tags}

        new_objects = [
            node(20, {"amenity": "vending_machine", "vending": "parking_tickets;public_transport_tickets"}),
            {"type": "way", "id": 30, "tags": {"highway": "elevator"}, "geometry": [
                {"lat": 52.0, "lon": 13.0}, {"lat": 52.0001, "lon": 13.0001},
            ]},
            {"type": "relation", "id": 40, "tags": {"type": "multipolygon", "amenity": "toilets"},
             "bounds": copy.deepcopy(relation["bounds"]), "members": []},
            node(50, {"departures_board": "realtime"}),
        ]
        excluded_objects = [
            node(21, {"amenity": "vending_machine", "vending": "public_transport_tickets"}),
            node(60, {"departures_board": "no"}),
            node(61, {"passenger_information_display": "no"}),
            node(62, {"tourism": "information", "information": "board"}),
            node(63, {"public_transport": "platform", "departures_board": "yes"}),
            node(64, {"disused:railway": "station", "tactile_paving": "yes"}),
        ]
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, *new_objects, *excluded_objects]
        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(generator.random, "shuffle"))
            stack.enter_context(patch.object(generator.requests, "get", side_effect=AssertionError("Unexpected HTTP request")))
            stack.enter_context(patch.object(generator.requests, "post", side_effect=AssertionError("Unexpected HTTP request")))
            fetch = stack.enter_context(patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", return_value=current))
            output = Path(temporary) / "equipment.json"
            challenge = generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=output)
            self.assertTrue(output.exists())

        self.assertEqual(len(challenge.tasks), 1)
        task = challenge.tasks[0].to_dict()
        properties = task["features"][0]["properties"]
        self.assertEqual(properties["objects_count"], 4)
        object_features = [feature for feature in task["features"] if feature["properties"].get("object_type")]
        self.assertEqual([feature["properties"]["@id"] for feature in object_features], ["node/20", "way/30", "relation/40", "node/50"])
        for obj in new_objects:
            self.assertIn(f"{obj['type']}/{obj['id']}", properties["task_instruction"])
        for obj in excluded_objects:
            self.assertNotIn(f"{obj['type']}/{obj['id']}", properties["task_instruction"])

        document = ET.fromstring(base64.b64decode(task["cooperativeWork"]["file"]["content"]))
        self.assertIsNone(document.find("create"))
        self.assertIsNone(document.find("delete"))
        self.assertEqual(len(document.find("modify")), 1)
        modified = document.find("modify/relation")
        self.assertEqual(modified.attrib, {"id": "500", "version": "8"})
        self.assertEqual([member.attrib for member in modified.findall("member")], [
            {"type": "node", "ref": "1", "role": "stop"},
            {"type": "way", "ref": "8", "role": "platform"},
            {"type": "node", "ref": "21", "role": "ticket_machine"},
            {"type": "node", "ref": "20", "role": ""},
            {"type": "way", "ref": "30", "role": ""},
            {"type": "relation", "ref": "40", "role": ""},
            {"type": "node", "ref": "50", "role": ""},
        ])
        self.assertEqual({tag.attrib["k"]: tag.attrib["v"] for tag in modified.findall("tag")}, current["tags"])
        self.assertEqual(current, original_current)
        overpass.getElementsFromQuery.assert_called_once()
        fetch.assert_called_once_with("relation", 500)


if __name__ == "__main__":
    unittest.main()
