import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from challenges.social_workshop import generate as workshop


NAME = "Werkstatt für Menschen mit Behinderungen"
EXPECTED = {
    "amenity": "social_facility", "social_facility": "workshop",
    "social_facility:for": "disabled",
}


def element(osm_type="node", osm_id=1, tags=None, **coordinates):
    result = {"type": osm_type, "id": osm_id, "tags": {"name": NAME} if tags is None else tags}
    result.update(coordinates or ({"lat": 51.0, "lon": 13.0} if osm_type == "node" else {"center": {"lat": 51.0, "lon": 13.0}}))
    return result


class WorkshopClassificationTests(unittest.TestCase):
    def test_clear_names_and_spelling_variants(self):
        for name in (
            NAME, "Behindertenwerkstatt", "BEHINDERTENWERKSTÄTTEN",
            "Behindertenwerkstaetten Neustadt", "WfbM Musterstadt",
            "Werkstätten für geistig behinderte Menschen",
        ):
            with self.subTest(name=name):
                tags = {"name": name}
                self.assertEqual(workshop.propose_changes(tags), EXPECTED)
                self.assertEqual(tags, {"name": name})

    def test_description_evidence_is_kept_verbatim(self):
        for key in ("description", "description:de"):
            tags = {"name": "Werk am Park", key: NAME}
            self.assertEqual(workshop.propose_changes(tags), EXPECTED)
            self.assertEqual(workshop.workshop_evidence(tags), (key, NAME))

    def test_generic_names_and_other_locations_are_excluded(self):
        for name in (
            "Werkstatt", "Lebenshilfe", "Caritas", "Werkstatt für Fahrräder",
            "Behindertenzentrum", "WfbM-Verwaltung", "Werkstattladen der WfbM",
            "Behindertenwerkstatt Wohnheim", "Behindertenwerkstatt Schule",
            "Ehemalige Behindertenwerkstatt", "Keine Werkstatt für behinderte Menschen",
            "mywfbmbrand",
        ):
            with self.subTest(name=name):
                self.assertIsNone(workshop.propose_changes({"name": name}))

    def test_other_use_in_description_is_not_reclassified(self):
        self.assertIsNone(workshop.propose_changes({
            "name": "Haus am Park",
            "description": "Werkstattladen der Behindertenwerkstatt",
        }))

    def test_positive_name_does_not_overrule_conflicting_descriptions(self):
        for key in ("description", "description:de"):
            for description in (
                "Ehemalige Behindertenwerkstatt, heute leerstehend",
                "Verwaltung der Werkstatt für behinderte Menschen",
                "Der Standort der Behindertenwerkstatt ist geschlossen.",
                "Das Gebäude liegt gegenüber der Werkstatt für behinderte Menschen.",
            ):
                with self.subTest(key=key, description=description):
                    self.assertIsNone(workshop.propose_changes({"name": NAME, key: description}))

    def test_neighboring_workshop_mentions_do_not_classify_the_building(self):
        for description in (
            "Das Gebäude liegt gegenüber der Werkstatt für behinderte Menschen.",
            "Ein Wohnhaus neben der Behindertenwerkstatt.",
            "Das Gebäude befindet sich in unmittelbarer Nähe der WfbM.",
            "Ein Gebäude unweit einer Werkstatt für Menschen mit Behinderungen.",
        ):
            with self.subTest(description=description):
                self.assertIsNone(workshop.propose_changes({"name": "Haus am Park", "description": description}))
        self.assertEqual(workshop.propose_changes({
            "name": "Haus am Park",
            "description": NAME + "; bietet neben Arbeit auch Beratung.",
        }), EXPECTED)

    def test_compatible_classifications_are_completed(self):
        for initial in ({}, {"amenity": "workshop"}, {"amenity": "social_facility"}, {"social_facility": "workshop"}):
            with self.subTest(initial=initial):
                tags = {"name": NAME, **initial}
                changes = workshop.propose_changes(tags)
                combined = {**tags, **changes}
                self.assertEqual({key: combined[key] for key in EXPECTED}, EXPECTED)
                self.assertIsNone(workshop.propose_changes(combined))

    def test_conflicting_primary_tags_and_subtypes_are_preserved(self):
        for initial in (
            {"amenity": "school"}, {"amenity": "clinic"},
            {"social_facility": "day_care"}, {"social_facility": "group_home"},
            *({key: "yes"} for key in workshop.COMPETING_KEYS),
        ):
            with self.subTest(initial=initial):
                tags = {"name": NAME, **initial}
                original = dict(tags)
                self.assertIsNone(workshop.propose_changes(tags))
                self.assertEqual(tags, original)

    def test_building_landuse_and_addresses_are_not_conflicts(self):
        tags = {"name": NAME, "building": "industrial", "landuse": "industrial", "addr:city": "Dresden", "shop": "no"}
        self.assertEqual(workshop.propose_changes(tags), EXPECTED)

    def test_existing_target_groups_are_never_changed(self):
        for target in ("mental_health", "disabled;juvenile", "senior", ""):
            with self.subTest(target=target):
                changes = workshop.propose_changes({"name": NAME, "social_facility:for": target})
                self.assertEqual(changes, {"amenity": "social_facility", "social_facility": "workshop"})
        self.assertIsNone(workshop.propose_changes({
            "name": NAME, **EXPECTED,
        }))

    def test_type_alone_is_insufficient_to_infer_target_group(self):
        self.assertIsNone(workshop.propose_changes({
            "name": "Jugendwerkstatt", "amenity": "social_facility", "social_facility": "workshop",
        }))

    def test_closed_or_planned_facilities_are_excluded(self):
        for initial in (
            {"disused": "yes"}, {"abandoned": "yes"}, {"removed": "yes"}, {"destroyed": "yes"},
            {"removed:amenity": "workshop"}, {"destroyed:amenity": "workshop"}, {"proposed:amenity": "social_facility"},
            {"disused:amenity": "workshop"}, {"construction": "yes"}, {"razed:building": "yes"},
        ):
            with self.subTest(initial=initial):
                self.assertIsNone(workshop.propose_changes({"name": NAME, **initial}))

    def test_malformed_tags_are_not_proposed(self):
        for tags in (None, [], {"name": NAME, "amenity": 3}):
            with self.subTest(tags=tags):
                self.assertIsNone(workshop.propose_changes(tags))


class WorkshopTaskTests(unittest.TestCase):
    def test_all_osm_representations_produce_one_object_tagfix(self):
        for osm_type in ("node", "way", "relation"):
            with self.subTest(osm_type=osm_type):
                task = workshop.build_task(element(osm_type))
                data = task.to_dict()
                self.assertEqual(data["features"][0]["properties"]["@id"], f"{osm_type}/1")
                operations = data["cooperativeWork"]["operations"]
                self.assertEqual(len(operations), 1)
                self.assertEqual(operations[0]["data"]["operations"][0]["data"], EXPECTED)
                self.assertEqual(operations[0]["data"]["operations"][1]["data"], [])

    def test_instructions_show_evidence_comparison_and_safe_links(self):
        tags = {"name": "WfbM **Test** | [Ort]", "website": "https://example.org/werkstatt", "contact:website": "javascript:alert(1)"}
        task = workshop.build_task(element(tags=tags))
        text = task.mainFeature.properties["task_instruction"]
        self.assertIn("Hinweis aus name", text)
        self.assertIn("Bisher | Vorschlag", text)
        self.assertIn("überspringe unsichere Fälle", text)
        self.assertIn("https://example.org/werkstatt", text)
        self.assertNotIn("javascript:alert", text)
        self.assertIn("\\|", text)
        self.assertIn("\\[Ort\\]", text)

    def test_unusable_coordinates_are_skipped(self):
        candidates = [
            {"type": "relation", "id": 1, "tags": {"name": NAME}},
            element(lat=float("nan"), lon=13),
            element(lat=51, lon=float("inf")),
            element(lat=100, lon=13),
            element(lat=None, lon=13),
            element(osm_type="way", center={"lat": 51}),
        ]
        for candidate in candidates:
            with self.subTest(candidate=candidate):
                self.assertIsNone(workshop.build_task(candidate))


class WorkshopGeneratorTests(unittest.TestCase):
    def run_main(self, candidates, **options):
        with patch.object(workshop.mrcb.Overpass, "getElementsFromQuery", return_value=candidates), contextlib.redirect_stdout(io.StringIO()):
            return workshop.main(**options)

    def test_query_covers_all_evidence_fields_and_bbox(self):
        query = workshop.build_query()
        self.assertIn("area(id:3600051477)", query)
        for field in workshop.EVIDENCE_FIELDS:
            self.assertIn(f'nwr["{field}"', query)
        bounded = workshop.build_query((50, 12, 51, 13))
        self.assertNotIn("area(", bounded)
        self.assertIn("(50.0,12.0,51.0,13.0)", bounded)

    def test_invalid_options_fail_before_network(self):
        for bbox in ((51, 13, 50, 12), (0, 0, float("nan"), 1), (-91, 0, 1, 1), (0, 0, 1)):
            with self.subTest(bbox=bbox), patch.object(workshop.mrcb, "Overpass") as overpass:
                with self.assertRaises(ValueError):
                    workshop.main(bbox=bbox)
                overpass.assert_not_called()
        with patch.object(workshop.mrcb, "Overpass") as overpass:
            with self.assertRaises(ValueError):
                workshop.main(max_tasks=0)
            overpass.assert_not_called()

    def test_duplicates_noops_and_missing_geometry_are_omitted(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "tasks.json"
            candidates = [element(), element(), element(osm_id=2, tags={"name": "Caritas"}), element(osm_type="relation", osm_id=3)]
            candidates[-1].pop("center")
            challenge = self.run_main(candidates, output_file=output)
            self.assertEqual(len(challenge.tasks), 1)
            records = output.read_text(encoding="utf-8").split("\x1e")
            self.assertEqual(len(records), 2)
            self.assertEqual(json.loads(records[1])["features"][0]["properties"]["@id"], "node/1")

    def test_task_and_byte_limits_stop_later_builds(self):
        for options in ({"max_tasks": 1}, {}):
            with self.subTest(options=options), tempfile.TemporaryDirectory() as temporary:
                candidates = [element(osm_id=1), element(osm_id=2)]
                output = Path(temporary) / "tasks.json"
                challenge = workshop.mrcb.Challenge(**options) if options else workshop.mrcb.Challenge(max_output_bytes=1)
                with patch.object(workshop.mrcb, "Challenge", return_value=challenge), patch.object(workshop, "build_task", wraps=workshop.build_task) as build:
                    result = self.run_main(candidates, output_file=output, **options)
                self.assertEqual(build.call_count, 1)
                self.assertEqual(len(result.tasks), 1 if options else 0)

    def test_new_output_parent_is_created(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "new" / "nested" / "tasks.json"
            challenge = self.run_main([element()], output_file=output)
            self.assertEqual(len(challenge.tasks), 1)
            self.assertTrue(output.is_file())

    def test_failed_query_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "tasks.json"
            output.write_bytes(b"previous successful challenge")
            with patch.object(workshop.mrcb.Overpass, "getElementsFromQuery", side_effect=ValueError("unavailable")):
                with self.assertRaises(ValueError):
                    workshop.main(output_file=output)
            self.assertEqual(output.read_bytes(), b"previous successful challenge")

    def test_default_output_does_not_depend_on_working_directory(self):
        old_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as temporary:
            try:
                os.chdir(temporary)
                challenge = workshop.mrcb.Challenge()
                with patch.object(workshop.mrcb, "Challenge", return_value=challenge), patch.object(challenge, "saveToFile") as save:
                    self.run_main([])
                save.assert_called_once_with(workshop.SCRIPT_DIR / "social_workshop.json")
            finally:
                os.chdir(old_cwd)

    def test_cli_help_imports_without_network(self):
        result = subprocess.run(
            [sys.executable, str(workshop.SCRIPT_DIR / "generate.py"), "--help"],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("--bbox", result.stdout)
        self.assertIn("--output", result.stdout)
        self.assertIn("--max-tasks", result.stdout)


if __name__ == "__main__":
    unittest.main()

