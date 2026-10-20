import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from shared import challenge_builder as mrcb


ROOT = Path(__file__).resolve().parents[1]
GENERATORS = (
    "note_abgerissen/note_abgerissen.py",
    "note_abgerissen/old_note_abgerissen.py",
    "amenity_nursing_home/amenity_nursing_home.py",
    "nursing_home_for/nursing_home_for.py",
)


def load_generator(relative_path):
    name = "test_simple_limit_" + Path(relative_path).stem
    spec = importlib.util.spec_from_file_location(name, ROOT / "challenges" / relative_path)
    module = importlib.util.module_from_spec(spec)
    # Dataclasses need their module registered during import.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class SimpleGeneratorLimitTests(unittest.TestCase):
    def run_generator(self, relative_path, prefill=False, **limits):
        challenge = mrcb.Challenge(**limits)
        elements = [
            {"type": "node", "id": index, "lat": 52.0, "lon": 13.0,
             "tags": {"note": "abgerissen"}}
            for index in range(1, 5)
        ]
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(contextlib.redirect_stderr(io.StringIO()))
            if prefill:
                challenge.addTask(mrcb.Task(mrcb.GeoFeature([13.0, 52.0])))
            stack.enter_context(patch("requests.get", side_effect=AssertionError("Unexpected HTTP request")))
            stack.enter_context(patch("requests.post", side_effect=AssertionError("Unexpected HTTP request")))
            stack.enter_context(patch.object(mrcb.Overpass, "getElementsFromQuery", return_value=elements))
            stack.enter_context(patch.object(mrcb, "Challenge", return_value=challenge))
            stack.enter_context(patch.dict(sys.modules, {"challenge_builder": mrcb}))
            stack.enter_context(patch("random.shuffle"))
            save = stack.enter_context(patch.object(challenge, "saveToFile"))
            add_task = stack.enter_context(patch.object(challenge, "addTask", wraps=challenge.addTask))
            geometry = stack.enter_context(patch.object(mrcb, "getElementGeometry", wraps=mrcb.getElementGeometry))
            center = stack.enter_context(patch.object(mrcb, "getElementCenterPoint", wraps=mrcb.getElementCenterPoint))
            module = load_generator(relative_path)
            history = None
            if relative_path == "note_abgerissen/note_abgerissen.py":
                history = stack.enter_context(patch.object(
                    module, "fetch_history_info", return_value=module.HistoryInfo(None, None, None, None)
                ))
            if relative_path != "note_abgerissen/old_note_abgerissen.py":
                module.main()
        save.assert_called_once()
        return challenge, add_task.call_count, geometry.call_count + center.call_count, history

    def test_exact_task_limit_stops_before_processing_the_next_element(self):
        for relative_path in GENERATORS:
            with self.subTest(generator=relative_path):
                challenge, added, geometries, history = self.run_generator(relative_path, max_tasks=1)
                self.assertEqual(len(challenge.tasks), 1)
                self.assertTrue(challenge.limit_reached)
                self.assertEqual(added, 1)
                self.assertEqual(geometries, 1)
                if history is not None:
                    history.assert_called_once_with("node", 1)

    def test_oversized_task_stops_instead_of_trying_every_remaining_element(self):
        for relative_path in GENERATORS:
            with self.subTest(generator=relative_path):
                challenge, added, geometries, history = self.run_generator(relative_path, max_output_bytes=1)
                self.assertEqual(challenge.tasks, [])
                self.assertTrue(challenge.limit_reached)
                self.assertEqual(added, 1)
                self.assertEqual(geometries, 1)
                if history is not None:
                    history.assert_called_once_with("node", 1)

    def test_pre_reached_limit_avoids_geometry_and_history_work(self):
        for relative_path in GENERATORS:
            with self.subTest(generator=relative_path):
                challenge, added, geometries, history = self.run_generator(relative_path, prefill=True, max_tasks=1)
                self.assertEqual(len(challenge.tasks), 1)
                self.assertTrue(challenge.limit_reached)
                self.assertEqual(added, 0)
                self.assertEqual(geometries, 0)
                if history is not None:
                    history.assert_not_called()


if __name__ == "__main__":
    unittest.main()
