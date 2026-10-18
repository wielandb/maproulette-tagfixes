import contextlib
import importlib.util
import io
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
