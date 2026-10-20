import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from challenges.imgur404 import imgur_404_image as imgur
from challenges.imgur404 import valueFinder as finder


class ImgurTaskLimitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.matches = self.directory / "matches.json"
        self.elements = [
            {
                "type": "node", "id": osm_id, "lat": 1.0, "lon": 2.0,
                "tags": {
                    "image": f"https://i.imgur.com/Photo{osm_id}.jpg",
                    "name": "Straße 東京 🚉",
                },
            }
            for osm_id in range(1, 5)
        ]

    def run_generator(self, *, task_limit=50_000, byte_limit=99_000_000, checks=None):
        self.matches.write_text(json.dumps(self.elements), encoding="utf-8")
        challenge = imgur.mrcb.Challenge(max_tasks=task_limit, max_output_bytes=byte_limit)
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(imgur, "SCRIPT_DIR", self.directory))
            stack.enter_context(patch.object(finder, "MATCHES_FILE", self.matches))
            stack.enter_context(patch.object(finder, "main"))
            stack.enter_context(patch.object(imgur.random, "shuffle"))
            stack.enter_context(patch.object(imgur.mrcb, "Challenge", return_value=challenge))
            check = stack.enter_context(patch.object(
                imgur, "check_imgur_404", return_value=True, side_effect=checks,
            ))
            current = stack.enter_context(patch.object(
                imgur, "get_current_element",
                side_effect=lambda osm_type, osm_id: next(
                    element for element in self.elements if element["id"] == osm_id
                ),
            ))
            setter = stack.enter_context(patch.object(
                imgur, "find_tag_setter",
                side_effect=lambda osm_type, osm_id, key, value: (f"user{osm_id}", 1),
            ))
            statistics = imgur.main()
        output = (self.directory / "imgur404.json").read_bytes()
        reports = json.loads((self.directory / "user_reports.json").read_text(encoding="utf-8"))
        return challenge, output, reports, statistics, check, current, setter

    def test_count_limit_stops_before_any_checks_for_the_next_object(self):
        challenge, output, reports, statistics, check, current, setter = self.run_generator(
            task_limit=2, checks=[True, True, ValueError("must not check a third object")],
        )
        self.assertEqual(len(challenge.tasks), 2)
        self.assertEqual(output.count(b"\x1e"), 2)
        self.assertEqual(set(reports), {"user1", "user2"})
        self.assertEqual(statistics["tasks"], 2)
        self.assertTrue(statistics["limit_reached"])
        self.assertEqual([call.args[:2] for call in current.call_args_list], [("node", 1), ("node", 2)])
        self.assertEqual([call.args[:2] for call in setter.call_args_list], [("node", 1), ("node", 2)])
        self.assertEqual(check.call_count, 2)

    def test_exact_byte_limit_stops_before_checks_for_the_next_object(self):
        _, full_output, _, _, _, _, _ = self.run_generator(task_limit=2)
        challenge, output, reports, statistics, check, current, setter = self.run_generator(
            byte_limit=len(full_output),
            checks=[True, True, ValueError("must not check a third object")],
        )
        self.assertEqual(output, full_output)
        self.assertEqual(challenge.output_size_bytes, len(output))
        self.assertTrue(statistics["limit_reached"])
        self.assertEqual(statistics["output_size_bytes"], len(output))
        self.assertEqual(statistics["tasks"], 2)
        self.assertEqual(set(reports), {"user1", "user2"})
        self.assertEqual((check.call_count, current.call_count, setter.call_count), (2, 2, 2))

    def test_rejected_task_does_not_enter_counts_or_user_reports(self):
        _, full_output, _, _, _, _, _ = self.run_generator(task_limit=2)
        _, output, reports, statistics, check, current, setter = self.run_generator(
            byte_limit=len(full_output) - 1,
            checks=[True, True, ValueError("must stop after rejecting the second object")],
        )
        self.assertEqual(output, full_output[:full_output.index(b"\x1e", 1)])
        self.assertEqual(statistics["tasks"], 1)
        self.assertEqual(statistics["direct_links"], 1)
        self.assertEqual(statistics["missing_links"], 1)
        self.assertEqual(set(reports), {"user1"})
        self.assertEqual(reports["user1"][0]["id"], 1)
        self.assertEqual({path.name for path in (self.directory / "user_reports").glob("*.txt")}, {"user1.txt"})
        self.assertEqual((check.call_count, current.call_count, setter.call_count), (2, 2, 2))

    def test_oversized_first_task_finishes_successfully_with_empty_output_and_reports(self):
        output_path = self.directory / "imgur404.json"
        output_path.write_text("previous output", encoding="utf-8")
        reports_directory = self.directory / "user_reports"
        reports_directory.mkdir()
        (reports_directory / "old.txt").write_text("old report", encoding="utf-8")
        _, output, reports, statistics, check, current, setter = self.run_generator(
            byte_limit=1,
            checks=[True, ValueError("must not check a second object")],
        )
        self.assertEqual(output, b"")
        self.assertEqual(reports, {})
        self.assertEqual(list(reports_directory.glob("*.txt")), [])
        self.assertEqual(statistics["tasks"], 0)
        self.assertEqual(statistics["direct_links"], 0)
        self.assertEqual(statistics["missing_links"], 0)
        self.assertTrue(statistics["limit_reached"])
        self.assertEqual((check.call_count, current.call_count, setter.call_count), (1, 1, 1))

    def test_objects_without_a_task_do_not_consume_the_count_limit(self):
        challenge, _, reports, statistics, check, current, setter = self.run_generator(
            task_limit=1,
            checks=[False, True, ValueError("must not check a third object")],
        )
        self.assertEqual(challenge.tasks[0].mainFeature.properties["@id"], "node/2")
        self.assertEqual(statistics["tasks"], 1)
        self.assertEqual(set(reports), {"user2"})
        self.assertEqual(check.call_count, 2)
        current.assert_called_once_with("node", 2)
        self.assertEqual(setter.call_count, 1)


if __name__ == "__main__":
    unittest.main()
