import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests

from shared.challenge_builder import (
    Challenge, GeoFeature, Overpass, Task, getElementCenterPoint, getElementGeometry,
)


class GeometryTests(unittest.TestCase):
    def test_overpass_way_geometry_has_a_center_without_bounds(self):
        element = {"type": "way", "geometry": [{"lon": 8, "lat": 50}, {"lon": 10, "lat": 52}]}
        self.assertEqual(getElementCenterPoint(element), [9, 51])

    def test_geojson_polygon_center_reads_its_outer_ring(self):
        ring = [[0, 0], [4, 0], [4, 4], [0, 0]]
        element = {"geometry": {"type": "Polygon", "coordinates": [ring]}}
        self.assertEqual(getElementCenterPoint(element), [2, 1])

    def test_closed_geometry_serializes_as_a_geojson_ring(self):
        ring = [[8, 50], [9, 50], [9, 51], [8, 50]]
        feature = GeoFeature(ring)
        self.assertEqual(feature.to_dict()["geometry"], {"type": "Polygon", "coordinates": [ring]})
        feature.convertPolygonToClosedString()
        self.assertEqual(feature.to_dict()["geometry"], {"type": "LineString", "coordinates": ring})

    def test_center_only_elements_can_be_displayed(self):
        self.assertEqual(getElementGeometry({"center": {"lat": 50, "lon": 8}}), [8, 50])

    def test_missing_geometry_raises_value_error_instead_of_index_errors(self):
        for geometry in ([], [None], [{"lon": 8}]):
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                getElementCenterPoint({"geometry": geometry})
        with self.assertRaises(ValueError):
            GeoFeature([])


def response(status=200, payload=None, body="test response"):
    result = Mock(status_code=status, text=body)
    result.json.return_value = payload if payload is not None else {"elements": []}
    return result


class OverpassTests(unittest.TestCase):
    @patch("shared.challenge_builder.requests.post")
    def test_queries_use_post_and_a_timeout(self, post):
        elements = [{"type": "node", "id": 1, "lat": 50, "lon": 8}]
        post.return_value = response(payload={"elements": elements})
        self.assertEqual(Overpass().getElementsFromQuery("query"), elements)
        self.assertEqual(post.call_args.kwargs["data"], {"data": "query"})
        self.assertEqual(post.call_args.kwargs["timeout"], (10, 300))
        self.assertIn("maproulette-tagfixes", post.call_args.kwargs["headers"]["User-Agent"])

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_temporary_failures_retry(self, post, sleep):
        for failure in (requests.Timeout("timeout"), response(429), response(504)):
            with self.subTest(failure=failure):
                post.reset_mock()
                post.side_effect = [failure, response()]
                self.assertEqual(Overpass().getElementsFromQuery("query"), [])
                self.assertEqual(post.call_count, 2)

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_partial_data_after_timeout_is_retried(self, post, sleep):
        post.side_effect = [
            response(payload={"elements": [{"id": 1}], "remark": "runtime error: Query timed out"}),
            response(payload={"elements": [{"id": 2}]}),
        ]
        self.assertEqual(Overpass().getElementsFromQuery("query"), [{"id": 2}])

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_retry_count_is_bounded(self, post, sleep):
        post.return_value = response(503)
        with self.assertRaisesRegex(ValueError, "HTTP 503"):
            Overpass().getElementsFromQuery("query")
        self.assertEqual(post.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_invalid_query_is_not_retried(self, post, sleep):
        post.return_value = response(400, body="parse error")
        with self.assertRaisesRegex(ValueError, "parse error"):
            Overpass().getElementsFromQuery("query")
        self.assertEqual(post.call_count, 1)
        sleep.assert_not_called()

    @patch("shared.challenge_builder.sleep")
    @patch("shared.challenge_builder.requests.post")
    def test_invalid_json_and_elements_are_rejected(self, post, sleep):
        post.return_value = response()
        post.return_value.json.side_effect = ValueError("html")
        with self.assertRaisesRegex(ValueError, "Invalid Overpass JSON"):
            Overpass().getElementsFromQuery("query")
        for payload in ([], {"elements": {}}, {"remark": "error"}):
            with self.subTest(payload=payload):
                post.return_value = response(payload=payload)
                with self.assertRaises(ValueError):
                    Overpass().getElementsFromQuery("query")


class ChallengeFileTests(unittest.TestCase):
    def test_task_limit_preserves_exactly_fifty_thousand_tasks(self):
        challenge = Challenge()
        challenge.tasks = list(range(50001))
        challenge.cap()
        self.assertEqual(len(challenge.tasks), 50000)
        self.assertEqual(challenge.tasks[0], 0)
        self.assertEqual(challenge.tasks[-1], 49999)

    def test_serialization_failure_preserves_previous_challenge(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            filename.write_text("previous output", encoding="utf-8")
            challenge = Challenge()
            task = Task(GeoFeature([8, 50]))
            challenge.addTask(task)
            # addTask already validates serialization. A later mutation must
            # still fail atomically instead of damaging the previous output.
            task.mainFeature.properties["invalid"] = object()
            with self.assertRaises(TypeError):
                challenge.saveToFile(filename)
            self.assertEqual(filename.read_text(encoding="utf-8"), "previous output")
            self.assertEqual(list(Path(directory).iterdir()), [filename])

    def test_valid_challenge_replaces_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            filename.write_text("previous output", encoding="utf-8")
            challenge = Challenge()
            challenge.addTask(Task(GeoFeature([8, 50], {"name": "Straße"})))
            challenge.saveToFile(filename)
            contents = filename.read_text(encoding="utf-8")
            self.assertTrue(contents.startswith("\x1e"))
            task = json.loads(contents[1:])
            self.assertEqual(task["features"][0]["properties"]["name"], "Straße")


class StopAreaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "challenges/add_objects_to_stop_area/generate.py"
        spec = importlib.util.spec_from_file_location("stop_area_generator", path)
        cls.generator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.generator)

    def test_incomplete_overpass_geometry_is_skipped(self):
        self.assertIsNone(self.generator.get_geometry({"type": "way", "geometry": [None]}))

    def test_output_path_is_in_the_generator_directory(self):
        self.assertEqual(self.generator.OUTPUT_FILE.parent, self.generator.SCRIPT_DIR)


if __name__ == "__main__":
    unittest.main()
