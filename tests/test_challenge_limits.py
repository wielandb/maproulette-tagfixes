import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest

from shared.challenge_builder import Challenge, GeoFeature, OscChange, Task


def make_task(osm_id=1, text="Straße am Bahnhof 🚉"):
    return Task(GeoFeature.withId("node", osm_id, [13.0, 52.0], {"description": text}))


def expected_record(task):
    return b"\x1e" + json.dumps(task.to_dict(), ensure_ascii=False).encode("utf-8") + os.linesep.encode("ascii")


class ChallengeLimitTests(unittest.TestCase):
    def setUp(self):
        self.messages = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.messages)
        self.redirect.__enter__()
        self.addCleanup(self.redirect.__exit__, None, None, None)

    def test_exact_task_limit_rejects_later_tasks_without_serializing_them(self):
        first, second = make_task(1), make_task(2)
        challenge = Challenge(max_tasks=2)
        self.assertTrue(challenge.addTask(first))
        self.assertFalse(challenge.limit_reached)
        self.assertTrue(challenge.addTask(second))
        self.assertTrue(challenge.limit_reached)
        # This real task would raise TypeError if serialization were attempted.
        invalid = make_task(3, object())
        self.assertFalse(challenge.addTask(invalid))
        self.assertFalse(challenge.addTask(make_task(4)))
        self.assertEqual(challenge.tasks, [first, second])
        self.assertEqual(challenge.output_size_bytes, len(expected_record(first) + expected_record(second)))
        self.assertEqual(self.messages.getvalue().count("Challenge limit reached"), 1)

    def test_exact_byte_limit_accepts_last_record_and_stops(self):
        task = make_task()
        challenge = Challenge(max_output_bytes=len(expected_record(task)))
        self.assertTrue(challenge.addTask(task))
        self.assertTrue(challenge.limit_reached)
        self.assertFalse(challenge.addTask(make_task(2, object())))
        self.assertEqual(challenge.tasks, [task])
        self.assertEqual(challenge.output_size_bytes, challenge.max_output_bytes)
        self.assertEqual(self.messages.getvalue().count("Challenge limit reached"), 1)

    def test_record_that_would_exceed_byte_limit_by_one_is_not_added(self):
        first, second = make_task(1), make_task(2)
        maximum = len(expected_record(first) + expected_record(second)) - 1
        challenge = Challenge(max_output_bytes=maximum)
        self.assertTrue(challenge.addTask(first))
        self.assertFalse(challenge.limit_reached)
        self.assertFalse(challenge.addTask(second))
        self.assertTrue(challenge.limit_reached)
        self.assertFalse(challenge.addTask(make_task(3, object())))
        self.assertEqual(challenge.tasks, [first])
        self.assertEqual(challenge.output_size_bytes, len(expected_record(first)))
        self.assertEqual(self.messages.getvalue().count("Challenge limit reached"), 1)

    def test_oversized_first_task_leaves_a_valid_empty_file(self):
        task = make_task()
        maximum = len(expected_record(task)) - 1
        challenge = Challenge(max_output_bytes=maximum)
        self.assertFalse(challenge.addTask(task))
        self.assertTrue(challenge.limit_reached)
        self.assertEqual(challenge.tasks, [])
        self.assertEqual(challenge.output_size_bytes, 0)
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            challenge.saveToFile(filename)
            self.assertEqual(filename.read_bytes(), b"")
            self.assertEqual(filename.stat().st_size, challenge.output_size_bytes)

    def test_utf8_record_separators_native_newlines_and_osc_are_counted_exactly(self):
        first = make_task(1)
        second = Task(
            GeoFeature.withId("node", 2, [13.1, 52.1], {"description": "Aufzug zum Bahnsteig – Étage 2"}),
            additionalFeatures=[GeoFeature([[13.1, 52.1], [13.2, 52.2]], {"name": "Fußweg"})],
            cooperativeWork=OscChange(
                '<osmChange version="0.6"><modify><node id="2" version="1" lat="52.1" lon="13.1">'
                '<tag k="name" v="Aufzug Étage 2"/></node></modify></osmChange>'
            ),
        )
        expected = expected_record(first) + expected_record(second)
        challenge = Challenge(max_output_bytes=len(expected))
        self.assertTrue(challenge.addTask(first))
        self.assertTrue(challenge.addTask(second))
        self.assertEqual(challenge.output_size_bytes, len(expected))
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            challenge.saveToFile(filename)
            actual = filename.read_bytes()
            self.assertEqual(actual, expected)
            self.assertEqual(filename.stat().st_size, challenge.output_size_bytes)
        self.assertEqual(actual.count(b"\x1e"), 2)
        self.assertEqual(actual.count(os.linesep.encode("ascii")), 2)
        self.assertIn("Straße am Bahnhof 🚉".encode("utf-8"), actual)
        self.assertIn(b'"cooperativeWork"', actual)
        self.assertIn(second.cooperativeWork.encoded_content.encode("ascii"), actual)

    def test_default_limits_and_oversized_constructor_values_use_hard_caps(self):
        for kwargs in ({}, {"max_tasks": None, "max_output_bytes": None},
                       {"max_tasks": 50_001, "max_output_bytes": 99_000_001}):
            with self.subTest(kwargs=kwargs):
                challenge = Challenge(**kwargs)
                self.assertEqual(challenge.max_tasks, 50_000)
                self.assertEqual(challenge.max_output_bytes, 99_000_000)
                self.assertFalse(challenge.limit_reached)
        smaller = Challenge(max_tasks=2, max_output_bytes=1234)
        self.assertEqual(smaller.max_tasks, 2)
        self.assertEqual(smaller.max_output_bytes, 1234)

    def test_invalid_constructor_limits_are_rejected(self):
        for parameter in ("max_tasks", "max_output_bytes"):
            for value in (0, -1, True, False, 1.0, float("inf"), "2", [], {}):
                with self.subTest(parameter=parameter, value=value), self.assertRaises(ValueError):
                    Challenge(**{parameter: value})

    def test_writer_checks_byte_limit_again_after_task_mutation(self):
        first, second = make_task(1), make_task(2)
        maximum = len(expected_record(first) + expected_record(second))
        challenge = Challenge(max_output_bytes=maximum)
        self.assertTrue(challenge.addTask(first))
        self.assertTrue(challenge.addTask(second))
        second.mainFeature.properties["description"] += "X" * 1000
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            challenge.saveToFile(filename)
            self.assertEqual(filename.read_bytes(), expected_record(first))
            self.assertEqual(filename.stat().st_size, challenge.output_size_bytes)
        self.assertEqual(challenge.tasks, [first])
        self.assertTrue(challenge.limit_reached)

    def test_writer_applies_task_limit_to_directly_extended_tasks(self):
        first, second = make_task(1), make_task(2)
        challenge = Challenge(max_tasks=2)
        challenge.tasks.extend([first, second, make_task(3, object())])
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            challenge.saveToFile(filename)
            self.assertEqual(filename.read_bytes(), expected_record(first) + expected_record(second))
            self.assertEqual(filename.stat().st_size, challenge.output_size_bytes)
        self.assertEqual(challenge.tasks, [first, second])
        self.assertTrue(challenge.limit_reached)

    def test_writer_applies_byte_limit_to_directly_extended_tasks(self):
        first, second = make_task(1), make_task(2)
        maximum = len(expected_record(first) + expected_record(second)) - 1
        challenge = Challenge(max_output_bytes=maximum)
        challenge.tasks.extend([first, second, make_task(3, object())])
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            challenge.saveToFile(filename)
            self.assertEqual(filename.read_bytes(), expected_record(first))
            self.assertEqual(filename.stat().st_size, challenge.output_size_bytes)
        self.assertEqual(challenge.tasks, [first])
        self.assertTrue(challenge.limit_reached)

    def test_later_serialization_failure_preserves_old_file_and_removes_temporary_file(self):
        first, second = make_task(1), make_task(2)
        challenge = Challenge()
        challenge.addTask(first)
        challenge.addTask(second)
        original_size = challenge.output_size_bytes
        second.mainFeature.properties["invalid"] = object()
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "challenge.json"
            filename.write_bytes(b"previous output\r\n")
            with self.assertRaises(TypeError):
                challenge.saveToFile(filename)
            self.assertEqual(filename.read_bytes(), b"previous output\r\n")
            self.assertEqual(list(Path(directory).iterdir()), [filename])
        self.assertEqual(challenge.tasks, [first, second])
        self.assertEqual(challenge.output_size_bytes, original_size)


if __name__ == "__main__":
    unittest.main()
