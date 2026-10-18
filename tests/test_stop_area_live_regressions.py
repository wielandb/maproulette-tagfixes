import base64
import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

import requests


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stop_area_live_regressions", ROOT / "challenges/add_objects_to_stop_area/generate.py")
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class StopAreaRegressionTests(unittest.TestCase):
    def relation(self):
        return {
            "type": "relation", "id": 500, "version": 7,
            "bounds": {"minlat": 52.0, "maxlat": 52.001, "minlon": 13.0, "maxlon": 13.001},
            "tags": {"public_transport": "stop_area", "name": "Test station"},
            "members": [{"type": "node", "ref": 1, "role": "platform", "lat": 52.0, "lon": 13.0}],
        }

    def test_query_subtracts_members_instead_of_parent_relations(self):
        query = generator.build_overpass_query()
        self.assertIn("node(r.stop_areas);", query)
        self.assertIn("way(r.stop_areas);", query)
        self.assertIn("relation(r.stop_areas);", query)
        self.assertNotIn("bn.candidate_objects", query)

    def test_country_batches_merge_duplicates_and_exclude_members_across_batches(self):
        first_relation = self.relation()
        first_relation["members"].append({"type": "node", "ref": 2, "role": ""})
        second_relation = dict(self.relation(), id=501, members=[])
        stations = [{"type": "node", "id": 100, "lat": 52, "lon": 13}, {"type": "way", "id": 200, "center": {"lat": 53, "lon": 13}}]
        already_assigned = {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}
        candidate = dict(already_assigned, id=3)
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [stations, [first_relation, candidate], [second_relation, candidate, already_assigned]]
        with patch.object(generator, "STATION_BATCH_SIZE", 1), contextlib.redirect_stdout(io.StringIO()):
            elements = generator.collect_challenge_elements(overpass)
        self.assertEqual([(element["type"], element["id"]) for element in elements], [("relation", 500), ("node", 3), ("relation", 501)])
        queries = [call.args[0] for call in overpass.getElementsFromQuery.call_args_list]
        self.assertIn("area(id:3600051477)", queries[0])
        self.assertIn("out center;", queries[0])
        self.assertIn("node(id:100)", queries[1])
        self.assertIn("way(id:200)", queries[2])
        self.assertNotIn("area(", queries[1])

    def test_country_batch_failure_preserves_existing_output_before_api_enrichment(self):
        relation = self.relation()
        stations = [{"type": "node", "id": 100, "lat": 52, "lon": 13}, {"type": "node", "id": 200, "lat": 53, "lon": 13}]
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [stations, [relation, {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}], requests.Timeout("Second station batch timed out")]
        with tempfile.TemporaryDirectory() as temporary, patch.object(generator, "STATION_BATCH_SIZE", 1), contextlib.redirect_stdout(io.StringIO()), patch.object(generator.mrcb.OscBuilder, "_fetch_current_element") as fetch:
            output = Path(temporary) / "existing.json"
            output.write_text("previous challenge must remain", encoding="utf-8")
            with self.assertRaises(requests.Timeout):
                generator.main(overpass=overpass, output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge must remain")
            fetch.assert_not_called()

    def test_bbox_replaces_country_filter_and_rejects_invalid_coordinates(self):
        query = generator.build_overpass_query((52.0, 13.0, 52.1, 13.1))
        self.assertIn('nwr["railway"="station"](52.0,13.0,52.1,13.1)', query)
        self.assertNotIn("area(", query)
        for bbox in [(52, 13, 51, 14), (float("nan"), 13, 53, 14), (52, 13, 53), (52, 13, 53, 181)]:
            with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                generator.build_overpass_query(bbox)

    def test_latitude_index_keeps_nearest_results_and_ignores_missing_centers(self):
        areas = [
            {"id": 1, "lat": 52.0, "lon": 13.001},
            {"id": 2, "lat": 52.001, "lon": 13.0},
            {"id": 3, "lat": 53.0, "lon": 13.0},
            {"id": 4}, {"id": 5, "lat": float("nan"), "lon": 13},
        ]
        obj = {"lat": 52.0, "lon": 13.0}
        expected = generator.find_nearest_stop_area(obj, areas)
        index = generator.StopAreaIndex(areas)
        self.assertEqual(generator.find_nearest_stop_area(obj, index), expected)
        self.assertEqual([area["id"] for area in index.near_latitude(52)], [1, 2])
        self.assertEqual(generator.find_nearest_stop_area({"lat": None, "lon": 13}, index), (None, None))

    def test_duplicate_candidates_are_added_once_preserving_current_relation(self):
        relation = self.relation()
        original = copy.deepcopy(relation)
        fetcher = Mock()
        fetcher._fetch_current_element.return_value = relation
        objects = [{"type": "node", "id": 1}, {"type": "node", "id": 2}, {"type": "node", "id": 2}]
        change = generator.build_osc_add_members(fetcher, {}, objects, relation).to_dict()
        document = ET.fromstring(base64.b64decode(change["file"]["content"]))
        modified = document.find("modify/relation")
        self.assertEqual(modified.attrib, {"id": "500", "version": "7"})
        self.assertEqual([member.attrib for member in modified.findall("member")], [
            {"type": "node", "ref": "1", "role": "platform"},
            {"type": "node", "ref": "2", "role": ""},
        ])
        self.assertEqual(relation, original)

    def test_inline_member_geometry_avoids_extra_overpass_queries(self):
        relation = self.relation()
        relation["members"].append({"type": "way", "ref": 20, "role": "platform", "geometry": [{"lat": 52, "lon": 13}, {"lat": 52.01, "lon": 13.01}]})
        overpass = Mock()
        features = generator.build_relation_member_features(overpass, 500, stop_area=relation)
        self.assertEqual([feature.properties["@id"] for feature in features], ["node/1", "way/20"])
        self.assertEqual(features[1].geometryType, "LineString")
        overpass.getElementsFromQuery.assert_not_called()

    def test_member_geometry_fallback_selects_requested_relation(self):
        relation = self.relation()
        missing = copy.deepcopy(relation)
        missing["members"][0].pop("lat")
        missing["members"][0].pop("lon")
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [
            {"type": "relation", "id": 499, "members": []},
            relation, {"type": "node", "id": 1, "lat": 52, "lon": 13},
        ]
        features = generator.build_relation_member_features(overpass, 500, stop_area=missing)
        self.assertEqual([feature.properties["@id"] for feature in features], ["node/1"])
        overpass.getElementsFromQuery.assert_called_once()

    def test_current_members_are_excluded_from_instruction_features_and_osc(self):
        relation = self.relation()
        current = copy.deepcopy(relation)
        current["members"].append({"type": "node", "ref": 2, "role": ""})
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, *[
            {"type": "node", "id": node_id, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}
            for node_id in (2, 3)
        ]]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", return_value=current):
            output = Path(temporary) / "test.json"
            challenge = generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=output)
            self.assertTrue(output.exists())
        self.assertEqual(len(challenge.tasks), 1)
        task = challenge.tasks[0].to_dict()
        main = task["features"][0]["properties"]
        self.assertEqual(main["objects_count"], 1)
        self.assertIn("node/3", main["task_instruction"])
        self.assertNotIn("node/2", main["task_instruction"])
        object_features = [feature["properties"]["@id"] for feature in task["features"] if feature["properties"].get("object_type")]
        self.assertEqual(object_features, ["node/3"])
        overpass.getElementsFromQuery.assert_called_once()

    def test_relation_that_is_no_longer_a_stop_area_is_skipped(self):
        relation = self.relation()
        current = copy.deepcopy(relation)
        current["tags"] = {"public_transport": "stop_area_group"}
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()) as output, patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", return_value=current):
            challenge = generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=Path(temporary) / "test.json")
        self.assertEqual(challenge.tasks, [])
        self.assertIn("no longer an existing stop_area", output.getvalue())

    def test_individual_current_relation_failure_preserves_existing_output(self):
        relation = self.relation()
        cases = [requests.Timeout("Current relation timed out"), ValueError("Malformed editing API response")]
        for error in cases:
            with self.subTest(error=error):
                overpass = Mock()
                overpass.getElementsFromQuery.return_value = [copy.deepcopy(relation), {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}]
                with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", side_effect=error):
                    output = Path(temporary) / "existing.json"
                    output.write_text("previous challenge must remain", encoding="utf-8")
                    with self.assertRaises(type(error)):
                        generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=output)
                    self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge must remain")

    def test_invalid_individual_relation_identity_preserves_existing_output(self):
        relation = self.relation()
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", return_value=dict(relation, id=999)):
            output = Path(temporary) / "existing.json"
            output.write_text("previous challenge must remain", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "different or invalid relation"):
                generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge must remain")

    def test_missing_batch_id_timeout_does_not_save_partially_generated_tasks(self):
        relation = self.relation()
        second_relation = self.relation()
        second_relation.update(id=501, bounds={"minlat": 52.02, "maxlat": 52.021, "minlon": 13, "maxlon": 13.001})
        second_relation["members"][0].update(ref=20, lat=52.02)
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, second_relation,
            {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}},
            {"type": "node", "id": 3, "lat": 52.02, "lon": 13, "tags": {"amenity": "bench"}},
        ]
        response = Mock(status_code=200)
        response.json.return_value = {"elements": [relation]}
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), patch.object(generator.random, "shuffle"), patch.object(generator.requests, "get", return_value=response), patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", side_effect=requests.Timeout("Missing relation timed out")) as fetch:
            output = Path(temporary) / "existing.json"
            output.write_text("previous challenge must remain", encoding="utf-8")
            with self.assertRaises(requests.Timeout):
                generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge must remain")
            fetch.assert_called_once_with("relation", 501)

    def test_deleted_individual_relation_is_explicitly_skipped(self):
        relation = self.relation()
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()) as log, patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", side_effect=generator.mrcb.OSMElementNotFoundError("HTTP 410")):
            challenge = generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=Path(temporary) / "test.json")
        self.assertEqual(challenge.tasks, [])
        self.assertIn("Skipping missing relation/500", log.getvalue())

    def test_multi_fetch_uses_bounded_batches_and_allows_missing_ids_to_fall_back(self):
        relations = [dict(self.relation(), id=relation_id) for relation_id in range(1, 102)]
        response1 = Mock(status_code=200)
        response1.json.return_value = {"elements": relations[:99]}
        response2 = Mock(status_code=200)
        response2.json.return_value = {"elements": relations[100:]}
        cache = {}
        with patch.object(generator.requests, "get", side_effect=[response1, response2]) as get, contextlib.redirect_stdout(io.StringIO()):
            generator.prefetch_current_relations(range(1, 102), cache)
        self.assertEqual(len(cache), 100)
        self.assertNotIn(100, cache)
        self.assertEqual(len(get.call_args_list[0].kwargs["params"]["relations"].split(",")), 100)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["relations"], "101")
        self.assertEqual(get.call_args_list[0].kwargs["timeout"], (10, 30))

    def test_multi_fetch_rejects_mismatched_or_malformed_relations(self):
        missing_members = dict(self.relation(), id=1)
        missing_members.pop("members")
        invalid_elements = [
            [{"type": "node", "id": 1, "version": 1}],
            [dict(self.relation(), id=999)],
            [dict(self.relation(), id=1, version=True)],
            [dict(self.relation(), id=1), dict(self.relation(), id=1)],
            [missing_members],
            [dict(self.relation(), id=1, members=None)],
        ]
        for elements in invalid_elements:
            with self.subTest(elements=elements):
                response = Mock(status_code=200)
                response.json.return_value = {"elements": elements}
                cache = {}
                with patch.object(generator.requests, "get", return_value=response), self.assertRaises(ValueError):
                    generator.prefetch_current_relations([1, 2], cache)
                self.assertEqual(cache, {})

    def test_missing_member_list_preserves_existing_output(self):
        relation = self.relation()
        current = copy.deepcopy(relation)
        current.pop("members")
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, {"type": "node", "id": 2, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), patch.object(generator.mrcb.OscBuilder, "_fetch_current_element", return_value=current):
            output = Path(temporary) / "existing.json"
            output.write_text("previous challenge must remain", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no complete members list"):
                generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge must remain")

    def test_missing_multi_fetch_member_list_preserves_existing_output(self):
        relation = self.relation()
        second_relation = dict(self.relation(), id=501)
        current = dict(relation)
        current.pop("members")
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = [relation, second_relation, *[
            {"type": "node", "id": node_id, "lat": 52, "lon": 13, "tags": {"amenity": "bench"}}
            for node_id in (2, 3)
        ]]
        response = Mock(status_code=200)
        response.json.return_value = {"elements": [current, second_relation]}
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()), patch.object(generator.random, "shuffle"), patch.object(generator, "find_nearest_stop_area", side_effect=[(relation, 0), (second_relation, 0)]), patch.object(generator.requests, "get", return_value=response):
            output = Path(temporary) / "existing.json"
            output.write_text("previous challenge must remain", encoding="utf-8")
            with self.assertRaises(ValueError):
                generator.main(station_bbox=(51, 12, 53, 14), overpass=overpass, output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous challenge must remain")

    def test_multi_fetch_retries_transient_failures_before_returning_current_relations(self):
        unavailable = Mock(status_code=503)
        available = Mock(status_code=200)
        available.json.return_value = {"elements": [dict(self.relation(), id=1), dict(self.relation(), id=2)]}
        cache = {}
        with patch.object(generator.requests, "get", side_effect=[requests.Timeout("Read timed out"), unavailable, available]) as get, patch.object(generator, "sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
            generator.prefetch_current_relations([1, 2], cache)
        self.assertEqual(get.call_count, 3)
        self.assertEqual(set(cache), {1, 2})
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5, 10])


if __name__ == "__main__":
    unittest.main()
