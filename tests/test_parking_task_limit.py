import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "parking_task_limit", ROOT / "challenges/parking_converter/parking_converter.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


class ParkingTaskLimitTests(unittest.TestCase):
    def run_generator(self, task_limit, process_limit=None, first_value="no"):
        generator = load_generator()
        elements = [
            {
                "type": "way", "id": osm_id,
                "tags": {"parking:lane:right": first_value if osm_id == 1 else "no", "name": f"Street {osm_id}"},
                "geometry": [{"lat": 52, "lon": 13}, {"lat": 52.1, "lon": 13.1}],
            }
            for osm_id in range(1, 5)
        ]
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [elements, [], []]
        original_conversion = generator.convert_base_parking_tags
        converted_names = []

        def record_conversion(tags):
            self.assertEqual(overpass.getElementsFromQuery.call_count, 3)
            converted_names.append(tags["name"])
            return original_conversion(tags)

        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(generator, "TASK_LIMIT", task_limit))
            stack.enter_context(patch.object(generator, "PROCESS_LIMIT", process_limit))
            stack.enter_context(patch.object(generator.random, "shuffle"))
            stack.enter_context(patch.object(generator, "convert_base_parking_tags", side_effect=record_conversion))
            save = stack.enter_context(patch.object(generator.mrcb.Challenge, "saveToFile"))
            challenge = generator.main(overpass=overpass, use_ai=False)
        save.assert_called_once()
        ids = [task.mainFeature.properties["@id"] for task in challenge.tasks]
        return ids, converted_names

    def test_task_limit_stops_before_converting_the_third_valid_object(self):
        ids, converted_names = self.run_generator(task_limit=2)
        self.assertEqual(ids, ["way/1", "way/2"])
        self.assertEqual(converted_names, ["Street 1", "Street 2"])

    def test_process_limit_still_stops_before_reaching_the_task_limit(self):
        ids, converted_names = self.run_generator(task_limit=3, process_limit=1)
        self.assertEqual(ids, ["way/1"])
        self.assertEqual(converted_names, ["Street 1"])

    def test_skipped_manual_objects_do_not_count_towards_the_task_limit(self):
        ids, converted_names = self.run_generator(task_limit=2, first_value="unknown")
        self.assertEqual(ids, ["way/2", "way/3"])
        self.assertEqual(converted_names, ["Street 1", "Street 2", "Street 3"])


class ParkingOutputSizeTests(unittest.TestCase):
    def elements(self, count=4):
        return [
            {
                "type": "way", "id": osm_id,
                "tags": {"parking:lane:right": "no", "name": f"Street {osm_id}"},
                "geometry": [{"lat": 52, "lon": 13}, {"lat": 52.1, "lon": 13.1}],
            }
            for osm_id in range(1, count + 1)
        ]

    def write_challenge(self, elements, byte_limit=1024 * 1024, task_limit=50000,
                        conversion_changes=None, complete_message=None):
        generator = load_generator()
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [copy.deepcopy(elements), [], []]
        with tempfile.TemporaryDirectory() as directory, contextlib.ExitStack() as stack:
            output = Path(directory) / "parking.json"
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(generator, "TASK_LIMIT", task_limit))
            stack.enter_context(patch.object(generator, "MAX_OUTPUT_BYTES", byte_limit))
            stack.enter_context(patch.object(generator, "PROCESS_LIMIT", None))
            stack.enter_context(patch.object(generator.random, "shuffle"))
            if conversion_changes is not None:
                stack.enter_context(patch.object(
                    generator, "convert_base_parking_tags", return_value=conversion_changes,
                ))
            if complete_message is not None:
                stack.enter_context(patch.object(generator, "MSG_COMPLETE", complete_message))
            challenge = generator.main(output_path=output, overpass=overpass, use_ai=False)
            contents = output.read_bytes()
            self.assertEqual(output.stat().st_size, len(contents))
            self.assertLessEqual(output.stat().st_size, byte_limit)
        return challenge, contents

    def ids(self, challenge):
        return [task.mainFeature.properties["@id"] for task in challenge.tasks]

    def test_next_task_is_rejected_if_it_would_exceed_the_limit_by_one_byte(self):
        elements = self.elements()
        _, two_records = self.write_challenge(elements, task_limit=2)
        challenge, contents = self.write_challenge(elements, byte_limit=len(two_records) - 1)
        self.assertEqual(self.ids(challenge), ["way/1"])
        self.assertEqual(contents, two_records[:two_records.index(b"\x1e", 1)])

    def test_task_is_accepted_when_output_exactly_matches_the_limit(self):
        elements = self.elements()
        _, two_records = self.write_challenge(elements, task_limit=2)
        challenge, contents = self.write_challenge(elements, byte_limit=len(two_records))
        self.assertEqual(self.ids(challenge), ["way/1", "way/2"])
        self.assertEqual(contents, two_records)

    def test_utf8_instructions_geometry_and_cooperative_work_all_count(self):
        elements = self.elements(count=1)
        elements[0]["geometry"] = [
            {"lat": 52 + index / 10000, "lon": 13 + index / 10000}
            for index in range(200)
        ]
        changes = {
            "parking:lane:right": None,
            "parking:right": "no",
            "parking:right:note": "Straße 東京 🚗",
        }
        options = {
            "conversion_changes": changes,
            "complete_message": "Grüße aus 東京 🚗\n",
        }
        _, full_record = self.write_challenge(elements, **options)
        task = json.loads(full_record[1:])
        self.assertIn("Grüße aus 東京 🚗", task["features"][0]["properties"]["task_instruction"])
        self.assertEqual(len(task["features"][0]["geometry"]["coordinates"]), 200)
        self.assertIn("Straße 東京 🚗", json.dumps(task["cooperativeWork"], ensure_ascii=False))
        self.assertGreater(len(full_record), len(full_record.decode("utf-8")))

        challenge, contents = self.write_challenge(
            elements, byte_limit=len(full_record) - 1, **options,
        )
        self.assertEqual(challenge.tasks, [])
        self.assertEqual(contents, b"")

    def test_oversized_first_task_produces_an_empty_json_sequence(self):
        challenge, contents = self.write_challenge(self.elements(), byte_limit=1)
        self.assertEqual(challenge.tasks, [])
        self.assertEqual(contents, b"")

    def test_skipped_manual_tasks_do_not_consume_the_output_budget(self):
        elements = self.elements()
        _, accepted_record = self.write_challenge([elements[1]])
        elements[0]["tags"]["parking:lane:right"] = "unknown"
        challenge, contents = self.write_challenge(elements, byte_limit=len(accepted_record))
        self.assertEqual(self.ids(challenge), ["way/2"])
        self.assertEqual(contents, accepted_record)

    def test_count_limit_still_applies_with_room_in_the_byte_budget(self):
        challenge, contents = self.write_challenge(self.elements(), task_limit=2)
        self.assertEqual(self.ids(challenge), ["way/1", "way/2"])
        self.assertLess(len(contents), 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
