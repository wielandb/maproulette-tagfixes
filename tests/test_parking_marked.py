import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "parking_marked_regressions", ROOT / "challenges/parking_converter/parking_converter.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class MarkedParkingTests(unittest.TestCase):
    def convert(self, tags):
        with contextlib.redirect_stdout(io.StringIO()):
            return generator.convert_base_parking_tags(copy.deepcopy(tags))

    def test_explicit_marked_positions_convert_completely_for_every_side(self):
        for side in ("right", "left", "both"):
            for old_position, new_position in (
                ("on_street", "lane"),
                ("half_on_kerb", "half_on_kerb"),
                ("on_kerb", "on_kerb"),
                ("street_side", "street_side"),
                ("lay_by", "street_side"),
            ):
                with self.subTest(side=side, old_position=old_position):
                    tags = {f"parking:lane:{side}": "marked", f"parking:lane:{side}:marked": old_position}
                    changes = self.convert(tags)
                    self.assertEqual(changes, {
                        f"parking:{side}": new_position,
                        f"parking:{side}:markings": "yes",
                        f"parking:lane:{side}": None,
                        f"parking:lane:{side}:marked": None,
                    })
                    self.assertEqual(generator.are_all_old_parking_tags_gone(tags, changes), {})

    def test_unknown_positions_retain_both_old_tags_for_manual_conversion(self):
        for side in ("right", "left", "both"):
            for position in ("unknown", "on_street;on_kerb", ""):
                with self.subTest(side=side, position=position):
                    tags = {f"parking:lane:{side}": "marked", f"parking:lane:{side}:marked": position}
                    changes = self.convert(tags)
                    self.assertEqual(changes, {})
                    self.assertEqual(generator.are_all_old_parking_tags_gone(tags, changes), tags)

    def test_marked_without_detail_retains_the_generic_conversion(self):
        for side in ("right", "left", "both"):
            with self.subTest(side=side):
                self.assertEqual(self.convert({f"parking:lane:{side}": "marked"}), {
                    f"parking:{side}": "yes",
                    f"parking:{side}:markings": "yes",
                    f"parking:lane:{side}": None,
                })

    def test_matching_left_and_right_positions_can_merge_without_old_tags(self):
        tags = {
            "parking:lane:left": "marked", "parking:lane:left:marked": "on_street",
            "parking:lane:right": "marked", "parking:lane:right:marked": "on_street",
        }
        changes = self.convert(tags)
        self.assertEqual(changes["parking:both"], "lane")
        self.assertEqual(changes["parking:both:markings"], "yes")
        self.assertIsNone(changes["parking:left"])
        self.assertIsNone(changes["parking:right"])
        self.assertEqual(generator.are_all_old_parking_tags_gone(tags, changes), {})

    def test_unknown_detail_on_one_side_does_not_prevent_converting_the_other(self):
        tags = {
            "parking:lane:left": "marked", "parking:lane:left:marked": "unknown",
            "parking:lane:right": "marked", "parking:lane:right:marked": "on_kerb",
        }
        changes = self.convert(tags)
        self.assertEqual(changes["parking:right"], "on_kerb")
        self.assertEqual(changes["parking:right:markings"], "yes")
        self.assertNotIn("parking:lane:left", changes)
        self.assertNotIn("parking:lane:left:marked", changes)
        self.assertEqual(generator.are_all_old_parking_tags_gone(tags, changes), {
            "parking:lane:left": "marked", "parking:lane:left:marked": "unknown",
        })


if __name__ == "__main__":
    unittest.main()
