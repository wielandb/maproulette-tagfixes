import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "challenges" / "stopsign-directions" / "directions.py"
)
spec = importlib.util.spec_from_file_location("stopsign_directions", SCRIPT_PATH)
directions = importlib.util.module_from_spec(spec)
# Importing the generator must neither download data nor overwrite its output.
with patch("requests.get", side_effect=AssertionError("Network request during import")), \
        patch("requests.post", side_effect=AssertionError("Network request during import")):
    spec.loader.exec_module(directions)


def node(node_id, longitude, **tags):
    return {
        "type": "node", "id": node_id, "lat": 50.0,
        "lon": longitude, "tags": tags,
    }


def way(way_id, nodes, **tags):
    return {
        "type": "way", "id": way_id, "nodes": nodes,
        "tags": {"highway": "residential", **tags},
    }


def point(node_id, east_meters, north_meters=0, **tags):
    """Use local meter offsets so regressions do not depend on node density."""
    return {
        "type": "node", "id": node_id,
        "lat": 50.0 + math.degrees(north_meters / 6371000),
        "lon": 10.0 + math.degrees(east_meters / (6371000 * math.cos(math.radians(50)))),
        "tags": tags,
    }


def sign_elements(sign_type, **tags):
    return [
        point(1, -150), point(2, 0, highway=sign_type, **tags),
        point(3, 7), way(10, [1, 2, 3]),
        point(4, 7, -50), point(5, 7, 50), way(20, [4, 3, 5]),
    ]


class StopsignDirectionsTests(unittest.TestCase):
    def test_incomplete_mirror_way_does_not_abort_valid_sign_tasks(self):
        elements = sign_elements("stop") + [way(999, [100, 101, 102])]
        challenge = self.populate(elements)
        self.assertEqual(len(challenge.tasks), 1)
        self.assertEqual(challenge.tasks[0].mainFeature.properties["@id"], "node/2")

    def populate(self, elements, sign_type="stop"):
        challenge = directions.mrcb.Challenge()
        handler = directions.OSMDataHandler({"elements": elements})
        directions.populate_challenge(challenge, handler, sign_type)
        return challenge

    def determine(self, elements):
        handler = directions.OSMDataHandler({"elements": elements})
        return handler.determine_give_way_direction(2, 10)

    def test_short_way_points_toward_junction_instead_of_away_from_it(self):
        elements = sign_elements("stop")
        elements[0] = point(1, -30)

        self.assertEqual(self.determine(elements), "forward")
        self.assertEqual(
            self.populate(elements).tasks[0].cooperativeWork.tagsToSet,
            {"direction": "forward"},
        )

    def test_distance_uses_meters_instead_of_number_of_way_nodes(self):
        elements = sign_elements("stop") + [
            point(6, 1), point(7, 2), point(8, 3), point(9, 4),
        ]
        elements[3] = way(10, [1, 2, 6, 7, 8, 9, 3])

        self.assertEqual(self.determine(elements), "forward")

    def test_degree_two_way_split_does_not_hide_nearby_junction(self):
        elements = sign_elements("stop") + [point(6, 2), way(11, [6, 3])]
        elements[3] = way(10, [1, 2, 6])

        self.assertEqual(self.determine(elements), "forward")

    def test_close_way_split_is_not_mistaken_for_junction(self):
        elements = sign_elements("stop") + [point(6, -3), way(11, [1, 6])]
        elements[3] = way(10, [6, 2, 3])

        self.assertEqual(self.determine(elements), "forward")

    def test_pedestrian_branches_do_not_reverse_motorroad_direction(self):
        for highway in ("footway", "path", "cycleway"):
            with self.subTest(highway=highway):
                elements = sign_elements("stop") + [
                    point(6, -1), point(7, -1, 30),
                    way(11, [6, 7], highway=highway),
                ]
                elements[3] = way(10, [1, 6, 2, 3])
                self.assertEqual(self.determine(elements), "forward")

    def test_minor_service_access_does_not_reverse_motorroad_direction(self):
        for service in ("driveway", "parking_aisle", "drive-through", "emergency_access"):
            with self.subTest(service=service):
                elements = sign_elements("stop") + [
                    point(6, -5), point(7, -5, 30),
                    way(11, [6, 7], highway="service", service=service),
                ]
                elements[2] = point(3, 25)
                elements[3] = way(10, [1, 6, 2, 3])

                self.assertEqual(self.determine(elements), "forward")

    def test_highway_area_does_not_create_junction(self):
        elements = sign_elements("stop") + [
            point(6, -1), point(7, -2, 30), point(8, -3, 30),
            way(11, [6, 7, 8, 6], area="yes"),
        ]
        elements[3] = way(10, [1, 6, 2, 3])

        self.assertEqual(self.determine(elements), "forward")

    def test_duplicate_road_edges_do_not_create_junction(self):
        elements = sign_elements("stop") + [point(6, -1), way(11, [1, 6])]
        elements[3] = way(10, [1, 6, 2, 3])

        self.assertEqual(self.determine(elements), "forward")

    def test_ambiguous_junction_distances_are_skipped(self):
        # Both the ratio and the absolute distance margin must be convincing.
        for near_meters, far_meters in ((7, 10), (5, 14), (20, 30)):
            with self.subTest(near=near_meters, far=far_meters):
                elements = sign_elements("stop") + [
                    point(6, -far_meters), point(7, -far_meters, -50),
                    point(8, -far_meters, 50), way(11, [7, 6, 8]),
                ]
                elements[2] = point(3, near_meters)
                elements[3] = way(10, [1, 6, 2, 3])

                self.assertIsNone(self.determine(elements))
                self.assertEqual(self.populate(elements).tasks, [])

    def test_junction_too_far_from_sign_is_skipped(self):
        for reverse in (False, True):
            with self.subTest(reverse=reverse):
                elements = sign_elements("stop")
                elements[2] = point(3, 65)
                if reverse:
                    elements[3] = way(10, [3, 2, 1])

                self.assertIsNone(self.determine(elements))
                self.assertEqual(self.populate(elements).tasks, [])

    def test_two_long_dead_ends_do_not_produce_direction(self):
        elements = [
            point(1, -150), point(2, 0, highway="stop"),
            point(3, 150), way(10, [1, 2, 3]),
        ]

        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_incomplete_continuation_cannot_prove_farther_side(self):
        elements = sign_elements("stop") + [point(6, -3), way(11, [100, 6])]
        elements[3] = way(10, [6, 2, 3])

        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_far_side_lower_bound_must_exceed_required_distance(self):
        for far_meters, expected in ((16.9, None), (17.1, "forward")):
            for reverse in (False, True):
                with self.subTest(far_meters=far_meters, reverse=reverse):
                    elements = sign_elements("stop") + [
                        point(6, -far_meters), way(11, [100, 6]),
                    ]
                    elements[3] = way(10, [3, 2, 6] if reverse else [6, 2, 3])
                    result = self.determine(elements)
                    if reverse and expected is not None:
                        self.assertEqual(result, "backward")
                    else:
                        self.assertEqual(result, expected)

    def test_missing_host_way_node_is_skipped(self):
        elements = sign_elements("stop")[1:]

        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_sign_on_junction_has_no_safe_direction(self):
        elements = sign_elements("stop") + [point(6, 0, 30), way(11, [2, 6])]

        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_closed_host_way_is_skipped(self):
        elements = sign_elements("stop")
        elements[3] = way(10, [1, 2, 3, 1])

        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_split_loop_reaching_same_junction_on_both_sides_is_skipped(self):
        elements = sign_elements("stop") + [
            point(6, -30, 15), point(7, 7, 15), way(11, [1, 6, 7, 3]),
        ]
        elements[0] = point(1, -30)

        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_repeated_sign_node_is_skipped(self):
        elements = sign_elements("stop") + [point(6, -2, 20)]
        elements[3] = way(10, [1, 2, 6, 2, 3])

        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_reversing_host_way_reverses_tag_and_preserves_visual_direction(self):
        elements = sign_elements("stop")
        original = directions.OSMDataHandler({"elements": elements})
        original_angle = original.calculate_rotation_angle(2, 10)
        elements[3] = way(10, [3, 2, 1])
        reversed_handler = directions.OSMDataHandler({"elements": elements})

        self.assertEqual(reversed_handler.determine_give_way_direction(2, 10), "backward")
        self.assertAlmostEqual(reversed_handler.calculate_rotation_angle(2, 10), original_angle)

    def test_only_requested_candidates_are_generated_from_context(self):
        elements = sign_elements("stop") + [
            point(101, 0, 200), point(102, 0, 50, highway="stop"),
            point(103, 7, 50), way(110, [101, 102, 103]),
            point(104, 7, 0), point(105, 7, 100), way(120, [104, 103, 105]),
        ]
        handler = directions.OSMDataHandler({"elements": elements}, candidate_node_ids={2})
        challenge = directions.mrcb.Challenge()
        directions.populate_challenge(challenge, handler, "stop")

        self.assertEqual(len(challenge.tasks), 1)
        self.assertEqual(challenge.tasks[0].mainFeature.properties["@id"], "node/2")

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_legacy_overpass_adapter_uses_shared_server_failover(self, post, sleep):
        first_url = "https://first.example.invalid/api/interpreter"
        second_url = "https://second.example.invalid/api/interpreter"
        unavailable = Mock(status_code=406, text="<h1>Service unavailable</h1>")
        available = Mock(status_code=200)
        available.json.return_value = {"elements": sign_elements("stop")}
        post.side_effect = [unavailable, available]
        overpass = directions.mrcb.Overpass(overpass_urls=[first_url, second_url])

        elements = overpass.queryElementsRaw(directions.create_overpass_query("stop"))

        self.assertEqual(elements, sign_elements("stop"))
        self.assertEqual([item.args[0] for item in post.call_args_list], [first_url, second_url])
        sleep.assert_called_once_with(30)

    def test_stop_is_generated_without_any_give_way_nodes(self):
        challenge = self.populate(sign_elements("stop"))
        self.assertEqual(len(challenge.tasks), 1)
        task = challenge.tasks[0].toGeoJSON()
        self.assertEqual(task["features"][0]["properties"]["@id"], "node/2")
        self.assertIn("icon_stop_90", task["features"][0]["properties"]["task_instruction"])
        self.assertEqual(
            task["cooperativeWork"]["operations"][0]["data"]["operations"][0]["data"],
            {"direction": "forward"},
        )

    def test_shared_builder_import_cannot_replace_the_local_builder(self):
        from shared import challenge_builder as shared_builder

        spec = importlib.util.spec_from_file_location("stopsign_with_shared_builder", SCRIPT_PATH)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {"challenge_builder": shared_builder}):
            spec.loader.exec_module(module)
            challenge = module.mrcb.Challenge()
            module.populate_challenge(
                challenge, module.OSMDataHandler({"elements": sign_elements("stop")}), "stop"
            )
            self.assertIs(sys.modules["challenge_builder"], shared_builder)
        self.assertIsNot(module.mrcb, shared_builder)
        self.assertEqual(len(challenge.tasks), 1)
        self.assertEqual(
            challenge.tasks[0].toGeoJSON()["features"][0]["properties"]["@id"], "node/2"
        )

    def test_stop_at_way_endpoint_is_skipped(self):
        elements = [
            node(1, 10.0, highway="stop"), node(2, 10.001),
            node(3, 10.002), way(10, [1, 2, 3]),
        ]
        self.assertEqual(self.populate(elements).tasks, [])

    def test_stop_in_multiple_ways_is_skipped(self):
        elements = sign_elements("stop") + [
            node(4, 10.003), node(5, 10.004), way(11, [4, 2, 5]),
        ]
        self.assertEqual(self.populate(elements).tasks, [])

    def test_existing_direction_is_preserved_for_both_sign_types(self):
        for sign_type in ("stop", "give_way"):
            with self.subTest(sign_type=sign_type):
                challenge = self.populate(
                    sign_elements(sign_type, direction="backward"), sign_type,
                )
                self.assertEqual(challenge.tasks, [])

    def test_existing_stop_direction_is_preserved(self):
        challenge = self.populate(sign_elements("stop", **{"stop:direction": "backward"}))
        self.assertEqual(challenge.tasks, [])

    def test_sign_shared_with_driveway_remains_ambiguous(self):
        elements = sign_elements("stop") + [
            point(6, 0, 30), way(11, [2, 6], highway="service", service="driveway"),
        ]
        self.assertIsNone(self.determine(elements))
        self.assertEqual(self.populate(elements).tasks, [])

    def test_non_motorroad_host_is_skipped(self):
        for highway in ("footway", "path", "cycleway"):
            with self.subTest(highway=highway):
                elements = sign_elements("stop")
                elements[3] = way(10, [1, 2, 3], highway=highway)
                self.assertEqual(self.populate(elements).tasks, [])

    def test_minor_service_access_host_is_skipped(self):
        for service in ("driveway", "parking_aisle", "drive-through", "emergency_access"):
            with self.subTest(service=service):
                elements = sign_elements("stop")
                elements[3] = way(10, [1, 2, 3], highway="service", service=service)

                self.assertIsNone(self.determine(elements))
                self.assertEqual(self.populate(elements).tasks, [])

    def test_give_way_keeps_its_direction_and_yield_icon(self):
        challenge = self.populate(sign_elements("give_way"), "give_way")
        self.assertEqual(len(challenge.tasks), 1)
        task = challenge.tasks[0]
        self.assertEqual(task.cooperativeWork.tagsToSet, {"direction": "forward"})
        self.assertIn("icon_yield_90", task.mainFeature.properties["task_instruction"])

    def test_duplicate_elements_do_not_remove_or_duplicate_task(self):
        elements = sign_elements("stop")
        challenge = self.populate(elements + elements)
        self.assertEqual(len(challenge.tasks), 1)

    def test_query_combines_all_areas_and_outputs_once(self):
        query = directions.create_overpass_query("stop")
        for area_id in directions.SEARCH_AREAS:
            self.assertIn(f'(area:{area_id})', query)
        self.assertEqual(query.count('node["highway"="stop"][!"direction"]'), 3)
        self.assertEqual(query.count("out body;"), 1)
        self.assertNotIn("way(bn)", query)
        self.assertNotIn(">;", query)

    def test_context_query_loads_complete_nearby_road_ways(self):
        query = directions.create_context_query([2, 102])

        self.assertIn("2,102", query)
        self.assertIn(".signs", query)
        self.assertIn("way(bn.signs)", query)
        self.assertIn('way(around.signs:120)["highway"]', query)
        self.assertIn(">;", query)
        self.assertEqual(query.count("out body;"), 1)

    def test_main_serializes_tasks_and_does_not_accumulate_them(self):
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [
            [], [point(2, 0, highway="stop")], sign_elements("stop"),
        ] * 2
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "challenge.json"
            for _ in range(2):
                challenge = directions.main(output, overpass)
                self.assertEqual(len(challenge.tasks), 1)
                records = [item for item in output.read_text(encoding="utf-8").split("\x1e") if item.strip()]
                self.assertEqual(len(records), 1)
                self.assertEqual(json.loads(records[0])["type"], "FeatureCollection")
        self.assertEqual(overpass.getElementsFromQuery.call_count, 6)

    def test_main_skips_context_download_for_empty_candidates(self):
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = []
        with tempfile.TemporaryDirectory() as directory:
            challenge = directions.main(Path(directory) / "challenge.json", overpass)

        self.assertEqual(challenge.tasks, [])
        self.assertEqual(overpass.getElementsFromQuery.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in overpass.getElementsFromQuery.call_args_list],
            [directions.create_overpass_query("give_way"), directions.create_overpass_query("stop")],
        )

    def test_main_default_output_belongs_to_script_from_any_working_directory(self):
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = []
        previous_directory = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as directory, \
                    patch.object(directions.mrcb, "Challenge") as builder:
                os.chdir(directory)
                directions.main(overpass=overpass)
                builder.return_value.saveToFile.assert_called_once_with(
                    SCRIPT_PATH.parent / "stop_give_way_sign_direction_challenge.json"
                )
                os.chdir(previous_directory)
        finally:
            os.chdir(previous_directory)

    def test_failed_download_preserves_previous_output(self):
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [[], ValueError("Overpass unavailable")]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "challenge.json"
            output.write_text("previous challenge", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Overpass unavailable"):
                directions.main(output, overpass)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge")

    def test_failed_context_download_preserves_previous_output(self):
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [
            [], [point(2, 0, highway="stop")], ValueError("Context unavailable"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "challenge.json"
            output.write_text("previous challenge", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Context unavailable"):
                directions.main(output, overpass)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge")


if __name__ == "__main__":
    unittest.main()
