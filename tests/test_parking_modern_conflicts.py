import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "parking_modern_conflict_tests", ROOT / "challenges/parking_converter/parking_converter.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class ModernParkingConflictTests(unittest.TestCase):
    def convert(self, tags):
        working = copy.deepcopy(tags)
        with contextlib.redirect_stdout(io.StringIO()):
            changes = generator.convert_base_parking_tags(working)
        return changes, generator.find_conflicting_modern_parking_tags(tags, changes)

    def conflicting_tags(self):
        return {
            "parking:lane:left": "parallel", "parking:lane:left:parallel": "on_street",
            "parking:lane:right": "diagonal", "parking:lane:right:diagonal": "on_street",
            "parking:left": "lane", "parking:right": "street_side",
        }

    def test_live_street_side_conflict_is_detected_after_merging_to_both(self):
        tags = self.conflicting_tags()
        changes, conflicts = self.convert(tags)
        self.assertEqual(generator.are_all_old_parking_tags_gone(tags, changes), {})
        self.assertIsNone(changes["parking:right"])
        self.assertEqual(changes["parking:both"], "lane")
        self.assertEqual(conflicts, {"parking:right": "street_side"})

    def test_specific_modern_lane_value_cannot_be_replaced_with_generic_yes(self):
        tags = {
            "parking:lane:left": "parallel", "parking:lane:right": "parallel",
            "parking:left": "lane", "parking:right": "lane",
        }
        changes, conflicts = self.convert(tags)
        self.assertEqual(changes["parking:both"], "yes")
        self.assertEqual(conflicts, {"parking:left": "lane", "parking:right": "lane"})

    def test_existing_fee_is_checked_against_inherited_both_fee(self):
        tags = {
            "parking:lane:left": "no", "parking:lane:right": "no",
            "parking:condition:left": "free", "parking:condition:right": "free",
            "parking:right:fee": "yes",
        }
        changes, conflicts = self.convert(tags)
        self.assertIsNone(changes["parking:right:fee"])
        self.assertEqual(changes["parking:both:fee"], "no")
        self.assertEqual(conflicts, {"parking:right:fee": "yes"})

    def test_equivalent_inherited_modern_value_is_allowed(self):
        tags = {"parking:lane:left": "no", "parking:lane:right": "no", "parking:right": "no"}
        changes, conflicts = self.convert(tags)
        self.assertIsNone(changes["parking:right"])
        self.assertEqual(changes["parking:both"], "no")
        self.assertEqual(conflicts, {})

    def test_lay_by_and_street_side_are_equivalent(self):
        tags = {
            "parking:lane:left": "marked", "parking:lane:left:marked": "street_side",
            "parking:lane:right": "marked", "parking:lane:right:marked": "street_side",
            "parking:right": "lay_by",
        }
        changes, conflicts = self.convert(tags)
        self.assertIsNone(changes["parking:right"])
        self.assertEqual(changes["parking:both"], "street_side")
        self.assertEqual(conflicts, {})

    def test_conflicts_never_enter_auto_or_ai_conversion(self):
        conflicting = self.conflicting_tags()
        already_manual = {"parking:lane:right": "no", "parking:right": "separate"}
        safe = {"parking:lane:right": "no"}
        elements = [
            {"type": "way", "id": i, "tags": tags,
             "geometry": [{"lat": 52, "lon": 13}, {"lat": 52.1, "lon": 13.1}]}
            for i, tags in enumerate((conflicting, already_manual, safe), 1)
        ]
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [elements, [], []]
        helper = Mock()
        quota = Mock()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(generator, "ai_conversion_available", return_value=True))
            stack.enter_context(patch.object(generator, "aihelper", helper))
            stack.enter_context(patch.object(generator, "free_tokens", quota))
            stack.enter_context(patch.object(generator, "ONLY_AUTO_TASKS", True))
            stack.enter_context(patch.object(generator.mrcb.Challenge, "saveToFile"))
            challenge = generator.main(overpass=overpass, use_ai=True)
        self.assertEqual([task.mainFeature.properties["@id"] for task in challenge.tasks], ["way/3"])
        quota.get_model_with_kontingent_from_list.assert_not_called()
        helper.request_ai_parking_conversion.assert_not_called()


if __name__ == "__main__":
    unittest.main()
