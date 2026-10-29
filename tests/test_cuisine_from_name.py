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

    def test_instructions_expose_local_pbf_data_age(self):
        candidate = {**element(), "pbf_source": "germany-latest.osm.pbf", "pbf_timestamp": "2026-10-29T00:00:00Z"}
        text = generator.build_task(candidate).mainFeature.properties["task_instruction"]
        self.assertIn("germany-latest.osm.pbf", text)
        self.assertIn("2026-10-29T00:00:00Z", text)
        self.assertIn("können inzwischen geändert sein", text)

    def test_invalid_or_missing_coordinates_fail_explicitly(self):
        cases = [element(kind="relation"), *[{**element(), **coordinates} for coordinates in (
            {"lat": None}, {"lat": float("nan")}, {"lon": float("inf")},
            {"lat": 91}, {"lon": -181}, {"lat": True})]]
        cases[0].pop("center")
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises((KeyError, TypeError, ValueError)):
                generator.build_task(candidate)


class GenerationTests(unittest.TestCase):
    def run_main(self, elements, **kwargs):
        with patch.object(generator, "iter_pbf_elements", return_value=iter(elements)), \
             patch.object(mrcb, "Overpass", side_effect=AssertionError("Overpass is not used")), \
             contextlib.redirect_stdout(io.StringIO()):
            return generator.main(pbf=Path("germany.osm.pbf"), **kwargs)

    def test_invalid_bbox_and_limits_are_rejected_before_download(self):
        with patch.object(generator, "download_germany") as download, \
             patch.object(generator, "iter_pbf_elements") as reader:
            for bbox in ((1, 2, 3), (52, 13, 51, 14), (1, 2, float("inf"), 4),
                         (-91, 2, 3, 4), (1, True, 3, 4)):
                with self.subTest(bbox=bbox), self.assertRaises(ValueError):
                    generator.main(bbox=bbox)
            for max_tasks in (0, -1, True):
                with self.subTest(max_tasks=max_tasks), self.assertRaises(ValueError):
                    generator.main(max_tasks=max_tasks)
            download.assert_not_called()
            reader.assert_not_called()

    def test_cli_forwards_existing_pbf_bbox_and_cache_settings(self):
        with patch.object(generator, "main") as main:
            generator.cli(["--pbf", "germany.osm.pbf", "--bbox", "51", "13", "52", "14",
                           "--cache-dir", "cache", "--max-tasks", "3", "--output", "tasks.json"])
        main.assert_called_once_with(output_file=Path("tasks.json"), bbox=[51.0, 13.0, 52.0, 14.0],
                                     max_tasks=3, pbf=Path("germany.osm.pbf"), cache_dir=Path("cache"))

    def test_default_download_cache_and_local_predicate(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(generator, "DEFAULT_CACHE_DIR", Path(temporary) / "cache"), \
             patch.object(generator, "download_germany", return_value=Path(temporary) / "download.osm.pbf") as download, \
             patch.object(generator, "iter_pbf_elements", return_value=iter([element()])) as reader, \
             contextlib.redirect_stdout(io.StringIO()):
            result = generator.main(output_file=Path(temporary) / "tasks.json", bbox=(51, 12, 53, 14))
            self.assertEqual(len(result.tasks), 1)
            download.assert_called_once_with(Path(temporary) / "cache")
            self.assertTrue((Path(temporary) / "cache").is_dir())
            self.assertEqual(reader.call_args.args, (Path(temporary) / "download.osm.pbf",))
            options = reader.call_args.kwargs
            self.assertEqual(options["tag_keys"], ("amenity",))
            self.assertEqual(options["bbox"], (51, 12, 53, 14))
            self.assertTrue(options["predicate"](element()["tags"]))
            self.assertFalse(options["predicate"]({"amenity": "cafe", "name": "Pizza"}))
        self.assertEqual(generator.DEFAULT_CACHE_DIR, ROOT / ".cache" / "geofabrik")

    def test_custom_cache_dir_is_resolved_from_caller(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(generator, "download_germany", return_value=Path(temporary) / "germany.osm.pbf") as download, \
             patch.object(generator, "iter_pbf_elements", return_value=iter([])), \
             contextlib.redirect_stdout(io.StringIO()):
            generator.main(cache_dir=Path(temporary) / "custom", output_file=Path(temporary) / "tasks.json")
            download.assert_called_once_with(Path(temporary) / "custom")

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
                with patch.object(imported, "iter_pbf_elements", return_value=iter([element()])), \
                     patch.object(imported, "download_germany") as download, \
                     contextlib.redirect_stdout(io.StringIO()):
                    challenge = imported.main(pbf=Path("germany.osm.pbf"), output_file=Path("nested") / "tasks.json")
                download.assert_not_called()
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
             contextlib.redirect_stdout(io.StringIO()) as output:
            result = self.run_main([bad, element(2)])
            self.assertEqual(result.tasks[0].mainFeature.properties["@id"], "node/2")
            self.assertTrue((Path(temporary) / "tasks.json").exists())
        self.assertEqual(generator.DEFAULT_OUTPUT, generator.SCRIPT_DIR / "cuisine_from_name.json")

    def test_limits_do_not_even_advance_the_next_pbf_candidate(self):
        for limits, expected in (({"max_tasks": 1}, 1), ({"max_output_bytes": 1}, 0)):
            with self.subTest(limits=limits), tempfile.TemporaryDirectory() as temporary:
                challenge = mrcb.Challenge(**limits)
                closed = []
                def candidates():
                    try:
                        yield element(1)
                        raise AssertionError("PBF scan advanced after reaching its output limit")
                    finally:
                        closed.append(True)
                with patch.object(generator, "iter_pbf_elements", return_value=candidates()), \
                     patch.object(mrcb, "Challenge", return_value=challenge), \
                     contextlib.redirect_stdout(io.StringIO()):
                    generator.main(pbf=Path("germany.osm.pbf"), output_file=Path(temporary) / "tasks.json")
                self.assertEqual(len(challenge.tasks), expected)
                self.assertTrue(challenge.limit_reached)
                self.assertEqual(closed, [True])

    def test_empty_success_replaces_output_but_pbf_failure_preserves_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "tasks.json"
            output.write_text("previous output", encoding="utf-8")
            def failed_scan():
                yield element()
                raise RuntimeError("PBF read failed")
            with patch.object(generator, "iter_pbf_elements", return_value=failed_scan()), \
                 self.assertRaises(RuntimeError):
                generator.main(pbf=Path("broken.osm.pbf"), output_file=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous output")
            self.run_main([], output_file=output)
            self.assertEqual(output.read_bytes(), b"")

    def test_download_failure_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "tasks.json"
            output.write_text("previous output", encoding="utf-8")
            with patch.object(generator, "download_germany", side_effect=RuntimeError("download unavailable")), \
                 patch.object(generator, "iter_pbf_elements") as reader, self.assertRaises(RuntimeError):
                generator.main(cache_dir=temporary, output_file=output)
            reader.assert_not_called()
            self.assertEqual(output.read_text(encoding="utf-8"), "previous output")

    def test_real_pbf_nodes_ways_relations_and_bbox_without_network(self):
        import osmium
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "fixture.osm.pbf"
            with osmium.SimpleWriter(str(path)) as writer:
                for osm_id, location in enumerate(((13.0, 52.0), (13.002, 52.0),
                                                   (13.002, 52.002), (13.0, 52.002)), 1):
                    writer.add_node(osmium.osm.mutable.Node(id=osm_id, location=location))
                for osm_id, location, tags in (
                    (20, (13.01, 52.01), {"amenity": "fast_food", "name": "Dönerhaus", "cuisine": "turkish"}),
                    (21, (13.02, 52.02), {"amenity": "restaurant", "name": "Pizza", "cuisine": "pizza"}),
                    (22, (14.0, 53.0), {"amenity": "restaurant", "name": "Pizza"}),
                ):
                    writer.add_node(osmium.osm.mutable.Node(id=osm_id, location=location, tags=tags))
                writer.add_way(osmium.osm.mutable.Way(
                    id=30, nodes=[1, 2, 3, 4, 1],
                    tags={"amenity": "restaurant", "name": "Pizzeria", "cuisine": "italian"}))
                writer.add_relation(osmium.osm.mutable.Relation(
                    id=40, members=[("w", 30, "outer")],
                    tags={"type": "multipolygon", "amenity": "restaurant",
                          "name": "Döner & Pizzeria", "cuisine": "kebab"}))
            output = Path(temporary) / "tasks.json"
            with patch.object(generator, "download_germany") as download, \
                 patch.object(mrcb, "Overpass", side_effect=AssertionError("No Overpass")), \
                 patch("requests.sessions.Session.request", side_effect=AssertionError("No HTTP while scanning PBF")), \
                 contextlib.redirect_stdout(io.StringIO()):
                result = generator.main(pbf=path, bbox=(51.9, 12.9, 52.1, 13.1), output_file=output)
            download.assert_not_called()
            by_id = {task.mainFeature.properties["@id"]: task for task in result.tasks}
            self.assertEqual(set(by_id), {"node/20", "way/30", "relation/40"})
            self.assertEqual(by_id["node/20"].cooperativeWork.tagsToSet, {"cuisine": "turkish;kebab"})
            self.assertEqual(by_id["way/30"].cooperativeWork.tagsToSet, {"cuisine": "italian;pizza"})
            self.assertEqual(by_id["relation/40"].cooperativeWork.tagsToSet, {"cuisine": "kebab;pizza"})
            for task in result.tasks:
                lon, lat = task.mainFeature.geometry
                self.assertTrue(12.9 <= lon <= 13.1 and 51.9 <= lat <= 52.1)


if __name__ == "__main__":
    unittest.main()
