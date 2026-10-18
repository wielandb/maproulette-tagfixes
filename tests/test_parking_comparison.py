import contextlib
import copy
import importlib.util
import io
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(filename, name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "challenges" / "parking_converter" / filename
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


comparison = load_script("parking_comparison.py", "parking_comparison_regressions")
generator = load_script("parking_converter.py", "parking_comparison_generator_regressions")


class ParkingEvaluationTests(unittest.TestCase):
    def assert_attributes(self, tags, schema, expected, side="left"):
        result = comparison.evaluate_side(tags, side, schema)
        for key, value in expected.items():
            with self.subTest(schema=schema, side=side, attribute=key):
                self.assertEqual(result[key], value)
        return result

    def test_new_values_inherit_both_and_override_each_property_independently(self):
        tags = {
            "parking:both": "lane",
            "parking:both:orientation": "parallel",
            "parking:both:markings": "yes",
            "parking:both:fee": "no",
            "parking:left": "street_side",
            "parking:left:markings": "no",
            "parking:right:orientation": "diagonal",
            "parking:right:fee": "yes",
        }
        self.assert_attributes(tags, "new", {
            "position": "street_side", "orientation": "parallel",
            "markings": "no", "fee": "no",
        })
        self.assert_attributes(tags, "new", {
            "position": "lane", "orientation": "diagonal",
            "markings": "yes", "fee": "yes",
        }, side="right")

    def test_old_details_and_conditions_inherit_independently(self):
        tags = {
            "parking:lane:both": "parallel",
            "parking:lane:both:parallel": "on_street",
            "parking:lane:left:parallel": "on_kerb",
            "parking:condition:both": "free",
            "parking:condition:both:maxstay": "1 hour",
            "parking:condition:left:maxstay": "2 hours",
            "parking:lane:both:capacity": "8",
            "parking:lane:left:capacity": "3",
        }
        self.assert_attributes(tags, "old", {
            "position": "on_kerb", "orientation": "parallel",
            "fee": "no", "maxstay": "2 hours", "capacity": "3",
        })
        self.assert_attributes(tags, "old", {
            "position": "lane", "orientation": "parallel",
            "fee": "no", "maxstay": "1 hour", "capacity": "8",
        }, side="right")

    def test_marked_parking_never_fabricates_an_orientation(self):
        for old_position, expected_position in (
            (None, "yes"),
            ("on_street", "lane"),
            ("half_on_kerb", "half_on_kerb"),
            ("on_kerb", "on_kerb"),
            ("street_side", "street_side"),
            ("lay_by", "street_side"),
        ):
            with self.subTest(old_position=old_position):
                tags = {"parking:lane:left": "marked"}
                if old_position is not None:
                    tags["parking:lane:left:marked"] = old_position
                self.assert_attributes(tags, "old", {
                    "position": expected_position,
                    "orientation": None,
                    "markings": "yes",
                })

    def test_painted_area_only_is_a_marked_lane_and_preserves_known_orientation(self):
        for base, expected_orientation in (("parallel", "parallel"), ("marked", None)):
            with self.subTest(base=base):
                self.assert_attributes({
                    "parking:lane:left": base,
                    f"parking:lane:left:{base}": "painted_area_only",
                }, "old", {
                    "position": "lane", "orientation": expected_orientation, "markings": "yes",
                })

    def test_lay_by_alias_has_same_interpretation_as_street_side(self):
        alias = comparison.evaluate_side({"parking:left": "lay_by"}, "left", "new")
        canonical = comparison.evaluate_side({"parking:left": "street_side"}, "left", "new")
        self.assertEqual(alias, canonical)

    def test_no_stopping_and_no_parking_remain_distinct(self):
        for restriction in ("no_parking", "no_stopping"):
            with self.subTest(restriction=restriction):
                expected = {"position": "no", "restriction": restriction}
                old = self.assert_attributes({
                    "parking:lane:left": "no",
                    "parking:condition:left": restriction,
                }, "old", expected)
                new = self.assert_attributes({
                    "parking:left": "no", "parking:left:restriction": restriction,
                }, "new", expected)
                self.assertEqual(old, new)

    def test_free_and_ticket_are_evaluated_as_fee_and_authentication(self):
        for condition, fee, authentication in (
            ("free", "no", {}),
            ("ticket", "yes", {"ticket": "yes"}),
        ):
            with self.subTest(condition=condition):
                self.assert_attributes({"parking:condition:left": condition}, "old", {
                    "fee": fee, "authentication": authentication,
                })

    def test_disc_and_maxstay_interval_keep_the_original_schedule_literal(self):
        interval = "(Mo-Fr 08:00-18:00; PH off)"
        old = comparison.evaluate_side({
            "parking:condition:both": "disc",
            "parking:condition:both:maxstay": "2 hours",
            "parking:condition:both:time_interval": interval,
        }, "left", "old")
        new = comparison.evaluate_side({
            "parking:both:authentication:disc:conditional": f"yes @ {interval}",
            "parking:both:maxstay:conditional": f"2 hours @ {interval}",
        }, "left", "new")
        self.assertEqual(old, new)
        self.assertEqual(old["authentication"], {})
        self.assertIsNone(old["maxstay"])
        self.assertEqual(old["maxstay:conditional"], f"2 hours @ {interval}")
        self.assertEqual(old["authentication:disc:conditional"], f"yes @ {interval}")

    def test_conditional_restriction_is_not_evaluated_for_the_current_time(self):
        restriction = "no_stopping @ (Mo-Fr 07:00-09:00); no_parking @ (Sa 10:00-12:00)"
        result = self.assert_attributes({
            "parking:left": "lane",
            "parking:left:restriction:conditional": restriction,
        }, "new", {
            "position": "lane", "restriction": None,
            "restriction:conditional": restriction,
        })
        self.assertFalse(result["unsupported"])

    def test_legacy_conditional_prohibition_keeps_the_physical_parking_position(self):
        interval = "(Mo-Fr 07:00-09:00)"
        old = comparison.evaluate_side({
            "parking:lane:left": "parallel",
            "parking:lane:left:parallel": "on_street",
            "parking:condition:left": "no_stopping",
            "parking:condition:left:time_interval": interval,
        }, "left", "old")
        new = comparison.evaluate_side({
            "parking:left": "lane",
            "parking:left:orientation": "parallel",
            "parking:left:restriction:conditional": f"no_stopping @ {interval}",
        }, "left", "new")
        self.assertEqual(old, new)
        self.assertEqual(old["position"], "lane")
        self.assertIsNone(old["restriction"])

    def test_missing_is_unknown_rather_than_free_unrestricted_or_unmarked(self):
        for schema in ("old", "new"):
            with self.subTest(schema=schema):
                self.assert_attributes({}, schema, {
                    "position": None, "orientation": None, "markings": None,
                    "restriction": None, "fee": None, "authentication": {},
                    "maxstay": None, "access": None, "capacity": None,
                })

    def test_unknown_tag_values_and_unhandled_tags_are_retained_as_warnings(self):
        for tags, schema in (
            ({"parking:lane:left": "unusual_position"}, "old"),
            ({"parking:left": "unusual_position"}, "new"),
            ({"parking:left:novel_rule": "some_rule"}, "new"),
        ):
            with self.subTest(schema=schema, tags=tags):
                evaluated = comparison.evaluate_side(tags, "left", schema)
                self.assertTrue(evaluated["unsupported"])
                self.assertIn(next(iter(tags.values())), " ".join(evaluated["unsupported"]))

    def test_unknown_legacy_condition_retains_its_interval_in_the_warning(self):
        tags = {
            "parking:condition:left": "unusual_condition",
            "parking:condition:left:time_interval": "(Mo-Fr 07:00-09:00)",
        }
        result = comparison.evaluate_side(tags, "left", "old")
        self.assertEqual(set(result["unsupported"]), {
            "parking:condition:left=unusual_condition",
            "parking:condition:left:time_interval=(Mo-Fr 07:00-09:00)",
        })


class ParkingComparisonMarkdownTests(unittest.TestCase):
    def render(self, old, new):
        return comparison.build_parking_comparison(
            old, new, image_base_url="https://example.test/parking"
        )

    def test_comparison_has_four_side_panels_and_reports_lost_orientation(self):
        old = {"parking:lane:both": "parallel", "parking:lane:both:parallel": "on_street"}
        new = {"parking:both": "lane", "parking:both:orientation": "diagonal"}
        markdown = self.render(old, new)
        self.assertIn("| Aspect | Old left | Old right | New left | New right |", markdown)
        self.assertGreaterEqual(markdown.count("!["), 4)
        self.assertIn("https://example.test/parking/", markdown)
        self.assertIn("parallel", markdown)
        self.assertIn("diagonal", markdown)
        self.assertIn("Differences detected", markdown)

    def test_equivalent_known_values_have_no_interpreted_differences(self):
        markdown = self.render({
            "parking:lane:both": "marked",
            "parking:lane:both:marked": "lay_by",
        }, {"parking:both": "street_side", "parking:both:markings": "yes"})
        self.assertIn("No differences in interpreted values", markdown)
        self.assertNotIn("Differences detected", markdown)

    def test_unknown_data_warns_even_when_both_sides_match(self):
        markdown = self.render({"parking:lane:left": "unusual_position"}, {
            "parking:left": "unusual_position",
        })
        self.assertIn("unusual", markdown)
        self.assertIn("Not fully interpreted", markdown)
        self.assertNotIn("equivalent", markdown.lower())

    def test_missing_data_is_labelled_explicitly(self):
        markdown = self.render({}, {})
        self.assertIn("Not tagged", markdown)
        table = "\n".join(line for line in markdown.splitlines() if line.startswith("|"))
        self.assertNotIn("unrestricted", table.lower())

    def test_markings_and_access_use_attribute_specific_labels(self):
        markdown = self.render({}, {
            "parking:left:markings": "yes", "parking:right:markings": "no",
            "parking:left:access": "yes", "parking:right:access": "no",
        })
        markings_row = next(line for line in markdown.splitlines() if "Markings |" in line)
        access_row = next(line for line in markdown.splitlines() if "Access |" in line)
        self.assertEqual(markings_row.split("|")[-3:-1], [" Marked ", " Unmarked "])
        self.assertEqual(access_row.split("|")[-3:-1], [" yes ", " no "])

    def test_untrusted_tag_content_cannot_add_columns_links_or_html(self):
        hostile = "other|value\n<script>alert(1)</script> [click](https://evil.test) ![x](https://evil.test/x)"
        markdown = self.render({"parking:lane:left": hostile}, {
            "parking:left:restriction:conditional": hostile,
        })
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("[click](https://evil.test)", markdown)
        self.assertNotIn("![x](https://evil.test/x)", markdown)
        self.assertNotIn("value\n<script>", markdown)
        table_lines = [line for line in markdown.splitlines() if line.startswith("|")]
        self.assertTrue(table_lines)
        for line in table_lines:
            with self.subTest(line=line):
                self.assertEqual(len(re.findall(r"(?<!\\)\|", line)), 6)

    def test_evaluation_and_rendering_do_not_change_input_tags(self):
        old = {"parking:lane:left": "parallel", "parking:lane:left:parallel": "lay_by"}
        new = {"parking:left": "lay_by", "parking:left:orientation": "parallel"}
        original_old, original_new = copy.deepcopy(old), copy.deepcopy(new)
        comparison.evaluate_side(old, "left", "old")
        comparison.evaluate_side(new, "left", "new")
        self.render(old, new)
        self.assertEqual(old, original_old)
        self.assertEqual(new, original_new)


class ParkingComparisonIntegrationTests(unittest.TestCase):
    def run_generator(self, tags, *, payload=None, only_auto=True, expect_preview=True):
        element = {
            "type": "way", "id": 42, "tags": copy.deepcopy(tags),
            "geometry": [{"lat": 52, "lon": 13}, {"lat": 52.1, "lon": 13.1}],
        }
        overpass = Mock()
        overpass.getElementsFromQuery.side_effect = [[element], [], []]
        helper = Mock(DEFAULT_MODEL_ORDER=["test-model"])
        helper.request_ai_parking_conversion.return_value = (payload, None)
        quota = Mock()
        quota.get_model_with_kontingent_from_list.return_value = "test-model"
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch("requests.get", side_effect=AssertionError("Unexpected HTTP request")))
            stack.enter_context(patch("requests.post", side_effect=AssertionError("Unexpected HTTP request")))
            stack.enter_context(patch.object(generator, "aihelper", helper))
            stack.enter_context(patch.object(generator, "free_tokens", quota))
            stack.enter_context(patch.object(generator, "ai_conversion_available", return_value=True))
            stack.enter_context(patch.object(generator, "ONLY_AUTO_TASKS", only_auto))
            stack.enter_context(patch.object(generator.mrcb.Challenge, "saveToFile"))
            render = stack.enter_context(patch.object(
                generator, "build_parking_comparison", return_value="PARKING COMPARISON"
            ))
            challenge = generator.main(overpass=overpass, use_ai=payload is not None)
        self.assertEqual(element["tags"], tags)
        self.assertEqual(len(challenge.tasks), 1)
        instruction = challenge.tasks[0].mainFeature.properties["task_instruction"]
        if expect_preview:
            render.assert_called_once()
            self.assertEqual(render.call_args.args[0], tags)
            self.assertEqual(instruction.count("PARKING COMPARISON"), 1)
            proposed = render.call_args.args[1]
        else:
            render.assert_not_called()
            self.assertIn("Visual comparison unavailable", instruction)
            proposed = None
        return proposed, challenge.tasks[0], helper

    def test_automatic_comparison_uses_applied_edits_and_existing_tags(self):
        tags = {
            "parking:lane:left": "parallel", "parking:lane:left:parallel": "on_street",
            "name": "Example Road", "surface": "asphalt",
        }
        proposed, task, helper = self.run_generator(tags)
        self.assertEqual(proposed, {
            "parking:left": "lane", "parking:left:orientation": "parallel",
            "name": "Example Road", "surface": "asphalt",
        })
        self.assertEqual(task.cooperativeWork.tagsToSet["parking:left"], "lane")
        helper.request_ai_parking_conversion.assert_not_called()

    def test_ai_comparison_uses_its_actual_set_and_unset_operations(self):
        tags = {
            "parking:lane:left": "unknown", "parking:lane:right": "no",
            "parking:both:fee": "yes", "name": "Example Road",
        }
        payload = {
            "meta": {"version": 2, "type": 1},
            "operations": [{
                "operationType": "modifyElement",
                "data": {
                    "id": "way/42", "operations": [
                        {"operation": "setTags", "data": {
                            "parking:left": "street_side", "parking:right": "separate",
                        }},
                        {"operation": "unsetTags", "data": [
                            "parking:lane:left", "parking:lane:right", "parking:both:fee",
                        ]},
                    ],
                },
            }],
        }
        before = copy.deepcopy(payload)
        proposed, task, helper = self.run_generator(tags, payload=payload)
        self.assertEqual(proposed, {
            "parking:left": "street_side", "parking:right": "separate", "name": "Example Road",
        })
        self.assertEqual(task.cooperativeWork.to_dict(), payload)
        self.assertEqual(payload, before)
        helper.request_ai_parking_conversion.assert_called_once()

    def test_manual_noop_does_not_display_an_unoffered_automatic_conversion(self):
        tags = {"parking:lane:left": "unknown", "parking:lane:right": "no"}
        proposed, task, helper = self.run_generator(tags, only_auto=False)
        self.assertEqual(proposed, tags)
        self.assertEqual(task.cooperativeWork.tagsToSet, {})
        helper.request_ai_parking_conversion.assert_not_called()

    def test_cooperative_operations_preserve_unedited_tags_and_ignore_other_elements(self):
        tags = {"name": "Example Road", "parking:left": "lane", "parking:right": "no"}
        payload = {
            "operations": [
                {"operationType": "modifyElement", "data": {
                    "id": "way/999", "operations": [
                        {"operation": "setTags", "data": {"name": "Wrong Road"}},
                    ],
                }},
                {"operationType": "modifyElement", "data": {
                    "id": "way/42", "operations": [
                        {"operation": "unsetTags", "data": ["parking:left"]},
                        {"operation": "setTags", "data": {"parking:both": "street_side"}},
                    ],
                }},
            ],
        }
        before_tags, before_payload = copy.deepcopy(tags), copy.deepcopy(payload)
        self.assertEqual(comparison.apply_cooperative_work(tags, payload, "way/42"), {
            "name": "Example Road", "parking:right": "no", "parking:both": "street_side",
        })
        self.assertEqual(tags, before_tags)
        self.assertEqual(payload, before_payload)

    def test_unsupported_cooperative_edits_fail_closed(self):
        tags = {"parking:left": "lane"}
        for edit in (
            {"operation": "setTags", "data": [{"key": "parking:left", "value": "no"}]},
            {"operation": "unsetTags", "data": {"parking:left": None}},
            {"operation": "replaceGeometry", "data": []},
        ):
            with self.subTest(edit=edit):
                payload = {"operations": [{
                    "operationType": "modifyElement", "data": {
                        "id": "way/42", "operations": [edit],
                    },
                }]}
                with self.assertRaises(ValueError):
                    comparison.apply_cooperative_work(tags, payload, "way/42")
                self.assertEqual(tags, {"parking:left": "lane"})

    def test_cooperative_edits_for_the_same_tag_are_applied_in_payload_order(self):
        payload = {"operations": [
            {"operationType": "modifyElement", "data": {
                "id": "way/42", "operations": [
                    {"operation": "setTags", "data": {"parking:left": "lane"}},
                    {"operation": "unsetTags", "data": ["parking:left"]},
                ],
            }},
            {"operationType": "modifyElement", "data": {
                "id": "way/42", "operations": [
                    {"operation": "setTags", "data": {"parking:left": "street_side"}},
                ],
            }},
        ]}
        self.assertEqual(comparison.apply_cooperative_work({}, payload, "way/42"), {
            "parking:left": "street_side",
        })

    def test_unpreviewable_ai_payload_reports_unavailable_instead_of_guessing(self):
        payload = {"operations": [{
            "operationType": "modifyElement", "data": {
                "id": "way/42", "operations": [
                    {"operation": "replaceGeometry", "data": []},
                ],
            },
        }]}
        self.run_generator({"parking:lane:left": "unknown"}, payload=payload, expect_preview=False)


if __name__ == "__main__":
    unittest.main()
