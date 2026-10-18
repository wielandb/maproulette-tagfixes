import importlib.util
import json
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


def sign_elements(sign_type, **tags):
    return [
        node(1, 10.0), node(2, 10.002, highway=sign_type, **tags),
        node(3, 10.003), way(10, [1, 2, 3]),
    ]


class StopsignDirectionsTests(unittest.TestCase):
    def test_incomplete_mirror_way_does_not_abort_valid_sign_tasks(self):
        elements = sign_elements("stop") + [way(20, [100, 101, 102])]
        challenge = self.populate(elements)
        self.assertEqual(len(challenge.tasks), 1)
        self.assertEqual(challenge.tasks[0].mainFeature.properties["@id"], "node/2")

    def populate(self, elements, sign_type="stop"):
        challenge = directions.mrcb.Challenge()
        handler = directions.OSMDataHandler({"elements": elements})
        directions.populate_challenge(challenge, handler, sign_type)
        return challenge

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

    def test_main_serializes_tasks_and_does_not_accumulate_them(self):
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [[], sign_elements("stop")] * 2
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "challenge.json"
            for _ in range(2):
                challenge = directions.main(output, overpass)
                self.assertEqual(len(challenge.tasks), 1)
                records = [item for item in output.read_text(encoding="utf-8").split("\x1e") if item.strip()]
                self.assertEqual(len(records), 1)
                self.assertEqual(json.loads(records[0])["type"], "FeatureCollection")

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


if __name__ == "__main__":
    unittest.main()
