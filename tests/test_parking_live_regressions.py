import contextlib
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
        "parking_live_regressions", ROOT / "challenges/parking_converter/parking_converter.py"
    )
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    return generator


class ParkingLiveRegressionTests(unittest.TestCase):
    def test_live_entry_point_can_save_all_three_sides_without_ai_calls(self):
        generator = load_generator()
        elements = [
            {
                "type": "way", "id": osm_id,
                "tags": {f"parking:lane:{side}": "no"},
                "geometry": [{"lat": 52, "lon": 13}, {"lat": 52.1, "lon": 13.1}],
            }
            for osm_id, side in enumerate(("right", "both", "left"), start=1)
        ]
        overpass = Mock()
        overpass.getElementsFromQuery.return_value = elements
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            output_path = Path(temporary) / "parking.json"
            with patch.object(generator, "ai_conversion_available", side_effect=AssertionError("AI enabled")):
                challenge = generator.main(output_path=output_path, overpass=overpass, use_ai=False)
            tasks = [json.loads(record) for record in output_path.read_text(encoding="utf-8").split("\x1e") if record.strip()]
        self.assertEqual(len(challenge.tasks), 3)
        self.assertEqual({task["features"][0]["properties"]["@id"] for task in tasks}, {"way/1", "way/2", "way/3"})
        operations = {
            key
            for task in tasks
            for key in task["cooperativeWork"]["operations"][0]["data"]["operations"][0]["data"]
        }
        self.assertTrue({"parking:right", "parking:both", "parking:left"}.issubset(operations))
        self.assertEqual(overpass.getElementsFromQuery.call_count, 3)
        for call, side in zip(overpass.getElementsFromQuery.call_args_list, ("right", "both", "left")):
            query = call.args[0]
            self.assertIn(f'way["parking:lane:{side}"];', query)
            self.assertEqual(query.count('way["parking:lane:'), 1)

    def test_failed_side_does_not_replace_previous_challenge(self):
        generator = load_generator()
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [[], ValueError("Query timed out")]
        with tempfile.TemporaryDirectory() as temporary, contextlib.redirect_stdout(io.StringIO()):
            output_path = Path(temporary) / "parking.json"
            output_path.write_text("previous output", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Query timed out"):
                generator.main(output_path=output_path, overpass=overpass, use_ai=False)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "previous output")


if __name__ == "__main__":
    unittest.main()
