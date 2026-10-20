import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import geojson


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "challenges" / "stopsign-directions" / "directions.py"
)
spec = importlib.util.spec_from_file_location("stopsign_limits", SCRIPT_PATH)
directions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(directions)


def data_handler():
    handler = Mock(candidate_node_ids=None)
    handler.get_ways.return_value = [
        {"id": 10, "nodes": [1, 2, 3]},
        {"id": 20, "nodes": [4, 5, 6]},
    ]
    handler.get_give_way_nodes.return_value = [2, 3, 4]
    handler.discardWayForTags.return_value = False
    handler.find_node_by_id.return_value = {"lat": 50.0, "lon": 10.0, "tags": {}}
    handler.isFirstOrLastNodeInWay.return_value = False
    handler.determine_give_way_direction.return_value = "forward"
    handler.calculate_rotation_angle.return_value = 90
    handler.get_node_coordinates.return_value = (50.0, 10.0)
    return handler


class StopsignLimitTests(unittest.TestCase):
    def test_task_adapter_preserves_geojson_and_cooperative_work(self):
        task = directions.mrcb.Task(
            directions.mrcb.GeoFeature(geojson.Point((10, 50)), {"name": "Füße"}),
            cooperativeWork=directions.mrcb.TagFix("node", 2, {"direction": "forward"}),
        )

        self.assertEqual(task.to_dict(), task.toGeoJSON())
        self.assertIn("cooperativeWork", task.to_dict())

    def test_task_limit_stops_before_more_direction_calculations(self):
        challenge = directions.mrcb.Challenge(max_tasks=1)
        handler = data_handler()

        directions.populate_challenge(challenge, handler, "give_way")

        self.assertEqual(len(challenge.tasks), 1)
        self.assertTrue(challenge.limit_reached)
        handler.determine_give_way_direction.assert_called_once_with(2, 10)
        handler.discardWayForTags.assert_called_once()

    def test_reached_limit_skips_handler_processing(self):
        challenge = directions.mrcb.Challenge(max_tasks=1)
        directions.populate_challenge(challenge, data_handler(), "give_way")
        handler = data_handler()

        directions.populate_challenge(challenge, handler, "give_way")

        handler.get_ways.assert_not_called()
        handler.determine_give_way_direction.assert_not_called()

    def test_byte_limit_stops_after_first_record_that_would_overflow(self):
        sample = directions.mrcb.Challenge(max_tasks=1)
        directions.populate_challenge(sample, data_handler(), "give_way")
        record = (
            "\x1e" + json.dumps(sample.tasks[0].to_dict(), ensure_ascii=False) + os.linesep
        ).encode("utf-8")
        challenge = directions.mrcb.Challenge(max_output_bytes=len(record) + 1)
        handler = data_handler()

        directions.populate_challenge(challenge, handler, "give_way")

        self.assertEqual(len(challenge.tasks), 1)
        self.assertTrue(challenge.limit_reached)
        self.assertEqual(handler.determine_give_way_direction.call_count, 2)
        handler.discardWayForTags.assert_called_once()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "challenge.json"
            challenge.saveToFile(output)
            self.assertEqual(output.read_bytes(), record)
            self.assertEqual(output.stat().st_size, challenge.output_size_bytes)
            self.assertLessEqual(output.stat().st_size, challenge.max_output_bytes)

    def test_main_skips_further_context_batches_and_sign_type_download(self):
        challenge = directions.mrcb.Challenge(max_tasks=1)
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [
            [
                {"type": "node", "id": node_id, "tags": {"highway": "give_way"}}
                for node_id in (2, 102)
            ],
            [],
        ]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(directions.mrcb, "Challenge", return_value=challenge), \
                patch.object(directions, "OSMDataHandler", return_value=data_handler()), \
                patch.object(directions, "CONTEXT_BATCH_SIZE", 1):
            output = Path(directory) / "challenge.json"
            result = directions.main(output, overpass)
            self.assertEqual(output.stat().st_size, result.output_size_bytes)

        self.assertIs(result, challenge)
        self.assertEqual(len(result.tasks), 1)
        self.assertEqual(
            [call.args[0] for call in overpass.getElementsFromQuery.call_args_list],
            [directions.create_overpass_query("give_way"), directions.create_context_query([2])],
        )


if __name__ == "__main__":
    unittest.main()
