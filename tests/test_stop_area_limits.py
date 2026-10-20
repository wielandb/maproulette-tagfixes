import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shared import challenge_builder as mrcb


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "stop_area_limits", ROOT / "challenges/add_objects_to_stop_area/generate.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class StopAreaLimitTests(unittest.TestCase):
    def run_generator(self, count=3, **limits):
        relations = [
            {"type": "relation", "id": 500 + index, "version": 1,
             "lat": 52 + index * 0.01, "lon": 13,
             "tags": {"type": "public_transport", "public_transport": "stop_area"},
             "members": []}
            for index in range(count)
        ]
        objects = [
            {"type": "node", "id": 10 + index, "lat": relation["lat"], "lon": 13,
             "tags": {"amenity": "bench"}}
            for index, relation in enumerate(relations)
        ]
        current = {relation["id"]: relation for relation in relations}
        challenge = mrcb.Challenge(**limits)

        def prefetch(ids, cache):
            cache.update({relation_id: current[relation_id] for relation_id in ids})

        with tempfile.TemporaryDirectory() as temporary, contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            stack.enter_context(patch.object(generator, "collect_challenge_elements", return_value=relations + objects))
            stack.enter_context(patch.object(generator.random, "shuffle"))
            stack.enter_context(patch.object(generator.mrcb, "Challenge", return_value=challenge))
            stack.enter_context(patch.object(generator, "build_relation_member_features", return_value=[]))
            stack.enter_context(patch("requests.get", side_effect=AssertionError("Unexpected HTTP request")))
            stack.enter_context(patch("requests.post", side_effect=AssertionError("Unexpected HTTP request")))
            fetch = stack.enter_context(patch.object(generator, "prefetch_current_relations", side_effect=prefetch))
            build = stack.enter_context(patch.object(generator, "build_osc_add_members", wraps=generator.build_osc_add_members))
            output = Path(temporary) / "tasks.json"
            result = generator.main(output_file=output)
            contents = output.read_bytes()
        self.assertIs(result, challenge)
        self.assertEqual(len(contents), challenge.output_size_bytes)
        return challenge, contents, fetch, build

    def test_count_limit_stops_current_relation_fetch_and_osc_building(self):
        challenge, contents, fetch, build = self.run_generator(max_tasks=1)
        self.assertEqual(len(challenge.tasks), 1)
        self.assertTrue(challenge.limit_reached)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(fetch.call_args.args[0], [500])
        self.assertEqual(build.call_count, 1)
        self.assertEqual(contents.count(b"\x1e"), 1)

    def test_exact_byte_limit_avoids_prefetching_remaining_relation_batches(self):
        _, record, _, _ = self.run_generator(count=1)
        challenge, contents, fetch, build = self.run_generator(count=101, max_output_bytes=len(record))
        self.assertEqual(len(challenge.tasks), 1)
        self.assertTrue(challenge.limit_reached)
        self.assertEqual(contents, record)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(fetch.call_args.args[0]), 100)
        self.assertEqual(build.call_count, 1)

    def test_task_that_would_exceed_bytes_is_rejected_and_later_tasks_are_not_built(self):
        _, two_records, _, _ = self.run_generator(count=2, max_tasks=2)
        challenge, contents, _, build = self.run_generator(max_output_bytes=len(two_records) - 1)
        self.assertEqual(len(challenge.tasks), 1)
        self.assertTrue(challenge.limit_reached)
        self.assertLess(len(contents), len(two_records))
        self.assertEqual(build.call_count, 2)

    def test_oversized_first_task_stops_after_one_osc(self):
        challenge, contents, _, build = self.run_generator(max_output_bytes=1)
        self.assertEqual(challenge.tasks, [])
        self.assertTrue(challenge.limit_reached)
        self.assertEqual(contents, b"")
        self.assertEqual(build.call_count, 1)


if __name__ == "__main__":
    unittest.main()
