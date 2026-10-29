import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared import challenge_builder as mrcb


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cuisine_from_name", ROOT / "challenges/cuisine_from_name/generate.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


def element(osm_id=1, kind="node", **extra_tags):
    result = {"type": kind, "id": osm_id,
              "tags": {"amenity": "fast_food", "name": "City-Dönerpizza", **extra_tags}}
    if kind == "node":
        result.update(lat=52.0, lon=13.0)
    else:
        result["center"] = {"lat": 52.0, "lon": 13.0}
    return result


class CuisineRulesTests(unittest.TestCase):
    def test_name_variants_and_compounds(self):
        for name in ("Döner", "DOENER", "donerhaus", "Citydöner", "Kebab", "Kebap-Palast"):
            for amenity in ("fast_food", "restaurant"):
                with self.subTest(name=name, amenity=amenity):
                    self.assertEqual(generator.propose_changes({"amenity": amenity, "name": name}),
                                     {"cuisine": "kebab"})
        for name in ("Pizza", "PIZZERIA", "Pizzahaus", "Citypizza"):
            with self.subTest(name=name):
                self.assertEqual(generator.propose_changes({"amenity": "restaurant", "name": name}),
                                 {"cuisine": "pizza"})

    def test_combined_signals_form_one_additive_change(self):
        tags = element(cuisine="turkish; pasta", website="https://example.org/")["tags"]
        original = dict(tags)
        changes = generator.propose_changes(tags)
        self.assertEqual(changes, {"cuisine": "turkish; pasta;kebab;pizza"})
        self.assertEqual(tags, original)
        self.assertIsNone(generator.propose_changes({**tags, **changes}))

    def test_existing_tokens_and_aliases_are_retained(self):
        for cuisine in ("kebab;pizza", "Pizza;Kebab", "kebab;italian_pizza", " kebab ; italian_pizza "):
            with self.subTest(cuisine=cuisine):
                self.assertIsNone(generator.propose_changes(element(cuisine=cuisine)["tags"]))
        self.assertEqual(generator.propose_changes(element(cuisine="italian_pizza")["tags"]),
                         {"cuisine": "italian_pizza;kebab"})
        # Membership is based on complete tokens, not a substring.
        self.assertEqual(generator.propose_changes(element(cuisine="kebab_house")["tags"]),
                         {"cuisine": "kebab_house;kebab;pizza"})

    def test_empty_cuisine_is_filled_without_an_empty_list_item(self):
        for value in ("", "  "):
            self.assertEqual(generator.propose_changes(element(cuisine=value)["tags"]),
                             {"cuisine": "kebab;pizza"})

    def test_invalid_lists_require_manual_work(self):
        for value in (None, 4, "italian;pasta;", ";pizza", "italian;;pizza", "italian,pasta"):
            with self.subTest(value=value):
                self.assertIsNone(generator.propose_changes(element(cuisine=value)["tags"]))

    def test_unrelated_objects_and_missing_names_do_not_generate_tasks(self):
        for tags in ({"amenity": "cafe", "name": "Pizza"},
                     {"shop": "bakery", "name": "Pizza"},
                     {"amenity": "restaurant", "name": "Zum Bahnhof"},
                     {"amenity": "restaurant", "name": None},
                     {"amenity": "restaurant"}):
            with self.subTest(tags=tags):
                self.assertIsNone(generator.propose_changes(tags))

    def test_lifecycle_markers_are_skipped_but_negative_flags_are_allowed(self):
        for prefix in generator.LIFECYCLE_PREFIXES:
            for extra in ({prefix: "yes"}, {f"{prefix}:amenity": "restaurant"},
                          {f"{prefix}:name": "Pizza"}, {f"{prefix}:cuisine": "pizza"}):
                with self.subTest(extra=extra):
                    self.assertIsNone(generator.propose_changes(element(**extra)["tags"]))
        self.assertIsNotNone(generator.propose_changes(element(disused="no")["tags"]))


class TaskTests(unittest.TestCase):
    def test_all_osm_types_produce_one_tagfix_with_context(self):
        for kind in ("node", "way", "relation"):
            with self.subTest(kind=kind):
                candidate = element(kind=kind, cuisine="turkish", website="https://example.org/menu(test)",
                                    **{"website:menu": "https://example.org/menu.pdf"})
                before = copy.deepcopy(candidate)
                task = generator.build_task(candidate).to_dict()
                self.assertEqual(candidate, before)
                self.assertEqual(task["cooperativeWork"]["meta"], {"version": 2, "type": 1})
                operations = task["cooperativeWork"]["operations"]
                self.assertEqual(len(operations), 1)
                self.assertEqual(operations[0]["data"]["id"], f"{kind}/1")
                self.assertEqual(operations[0]["data"]["operations"], [
                    {"operation": "setTags", "data": {"cuisine": "turkish;kebab;pizza"}},
                    {"operation": "unsetTags", "data": []},
                ])
                feature = task["features"][0]
                self.assertEqual(feature["geometry"], {"type": "Point", "coordinates": [13.0, 52.0]})
                self.assertEqual(feature["properties"]["@id"], f"{kind}/1")
                instruction = feature["properties"]["task_instruction"]
                for expected in ("Bisher", "Vorschlag", "turkish;kebab;pizza", "ausschließlich aus dem Namen",
                                 "überspringe", "https://wiki.openstreetmap.org/wiki/Key:cuisine",
                                 "https://example.org/menu.pdf", "https://example.org/menu%28test%29"):
                    self.assertIn(expected, instruction)

    def test_markdown_values_are_escaped_and_nonweb_links_are_omitted(self):
        candidate = element(name="Döner | `Pizza`", website="javascript:alert(1)",
                            **{"website:menu": "https://user:password@example.org/"})
        instruction = generator.build_task(candidate).mainFeature.properties["task_instruction"]
        self.assertIn("Döner \\| `Pizza`", instruction)
        self.assertNotIn("javascript:", instruction)
        self.assertNotIn("password", instruction)

    def test_invalid_or_missing_coordinates_fail_explicitly(self):
        cases = [element(kind="relation"), *[{**element(), **coordinates} for coordinates in (
            {"lat": None}, {"lat": float("nan")}, {"lon": float("inf")},
            {"lat": 91}, {"lon": -181}, {"lat": True})]]
        cases[0].pop("center")
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises((KeyError, TypeError, ValueError)):
                generator.build_task(candidate)


class GenerationTests(unittest.TestCase):
    def test_germany_and_bbox_queries_share_every_name_pattern(self):
        query = generator.build_query()
        self.assertIn("area(id:3600051477)", query)
        self.assertIn("(area.searchArea)", query)
        self.assertIn("fast_food|restaurant", query)
        self.assertIn("out tags center;", query)
        for _, pattern in generator.NAME_RULES:
            self.assertIn(pattern.pattern, query)
        sample = generator.build_query((51.0, 13.0, 52.0, 14.0))
        self.assertNotIn("area(", sample)
        self.assertIn("(51.0,13.0,52.0,14.0)", sample)

    def test_invalid_bbox_and_limits_are_rejected_before_http(self):
        with patch.object(mrcb.Overpass, "getElementsFromQuery") as download:
            for bbox in ((1, 2, 3), (52, 13, 51, 14), (1, 2, float("inf"), 4),
                         (-91, 2, 3, 4), (1, True, 3, 4)):
                with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                    generator.main(bbox=bbox)
            for max_tasks in (0, -1, True):
                with self.subTest(max_tasks=max_tasks), self.assertRaises(ValueError):
                    generator.main(max_tasks=max_tasks)
            download.assert_not_called()

    def test_cli_forwards_sample_settings(self):
        with patch.object(generator, "main") as main:
            generator.cli(["--bbox", "51", "13", "52", "14", "--max-tasks", "3", "--output", "tasks.json"])
        main.assert_called_once_with(output_file=Path("tasks.json"), bbox=[51.0, 13.0, 52.0, 14.0], max_tasks=3)

    def test_import_from_unrelated_directory_and_custom_output(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                spec = importlib.util.spec_from_file_location(
                    "cuisine_unrelated_cwd", ROOT / "challenges/cuisine_from_name/generate.py"
                )
                imported = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(imported)
                with patch.object(mrcb.Overpass, "getElementsFromQuery", return_value=[element()]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    challenge = imported.main(output_file=Path("nested") / "tasks.json")
                output = Path(temporary) / "nested" / "tasks.json"
                self.assertEqual(len(challenge.tasks), 1)
                content = output.read_bytes()
                self.assertTrue(content.startswith(b"\x1e"))
                record = json.loads(content[1:].decode("utf-8"))
                self.assertEqual(record["features"][0]["properties"]["suggested_cuisine"], "kebab;pizza")
            finally:
                os.chdir(previous)

    def test_default_output_is_beside_script_and_missing_geometry_is_skipped(self):
        bad = element(1, "relation")
        bad.pop("center")
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(generator, "DEFAULT_OUTPUT", Path(temporary) / "tasks.json"), \
             patch.object(mrcb.Overpass, "getElementsFromQuery", return_value=[bad, element(2)]), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            result = generator.main()
            self.assertEqual(result.tasks[0].mainFeature.properties["@id"], "node/2")
            self.assertTrue((Path(temporary) / "tasks.json").exists())
        self.assertEqual(generator.DEFAULT_OUTPUT, generator.SCRIPT_DIR / "cuisine_from_name.json")
        self.assertIn("Skipping relation/1", output.getvalue())

    def test_limits_stop_before_processing_the_next_candidate(self):
        for limits, expected in (({"max_tasks": 1}, 1), ({"max_output_bytes": 1}, 0)):
            with self.subTest(limits=limits), tempfile.TemporaryDirectory() as temporary:
                challenge = mrcb.Challenge(**limits)
                with patch.object(mrcb.Overpass, "getElementsFromQuery", return_value=[element(1), element(2)]), \
                     patch.object(mrcb, "Challenge", return_value=challenge), \
                     patch.object(generator, "build_task", wraps=generator.build_task) as build, \
                     contextlib.redirect_stdout(io.StringIO()):
                    generator.main(output_file=Path(temporary) / "tasks.json")
                self.assertEqual(len(challenge.tasks), expected)
                self.assertEqual(build.call_count, 1)
                self.assertTrue(challenge.limit_reached)

    def test_empty_success_replaces_old_output_but_query_failure_preserves_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "tasks.json"
            output.write_text("previous output", encoding="utf-8")
            with patch.object(mrcb.Overpass, "getElementsFromQuery", side_effect=RuntimeError("offline")), \
                 self.assertRaises(RuntimeError):
                generator.main(output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous output")
            with patch.object(mrcb.Overpass, "getElementsFromQuery", return_value=[]), \
                 contextlib.redirect_stdout(io.StringIO()):
                generator.main(output_file=output)
            self.assertEqual(output.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
