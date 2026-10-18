import contextlib
import importlib.util
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests


ROOT = Path(__file__).resolve().parents[1]


@contextlib.contextmanager
def working_directory(path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def load_script(relative_path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    # Dataclasses look up their module while the class is being created.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class GeneratorTests(unittest.TestCase):
    def test_incomplete_way_geometries_are_skipped_without_aborting_later_tasks(self):
        first = {"lat": 52.0, "lon": 13.0}
        last = {"lat": 52.1, "lon": 13.1}
        for directory in ["note_abgerissen", "parking_converter"]:
            with self.subTest(generator=directory):
                module = load_script(f"challenges/{directory}/{directory}.py", f"test_geometry_{directory}")
                tags = {"note": "abgerissen"} if directory == "note_abgerissen" else {"parking:lane:both": "no"}
                elements = [
                    {"type": "way", "id": index, "tags": tags, "geometry": geometry}
                    for index, geometry in enumerate([[], [first], [first, None, last], [first, last]], start=1)
                ]
                challenge = module.mrcb.Challenge()
                with contextlib.ExitStack() as stack:
                    output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    stack.enter_context(patch("requests.get", side_effect=AssertionError("Unexpected HTTP request")))
                    stack.enter_context(patch("requests.post", side_effect=AssertionError("Unexpected HTTP request")))
                    stack.enter_context(patch.object(module.mrcb.Overpass, "getElementsFromQuery", return_value=elements))
                    stack.enter_context(patch.object(module.mrcb, "Challenge", return_value=challenge))
                    save = stack.enter_context(patch.object(challenge, "saveToFile"))
                    if directory == "note_abgerissen":
                        stack.enter_context(patch.object(module, "fetch_history_info", return_value=module.HistoryInfo(None, None, None, None)))
                    else:
                        stack.enter_context(patch.object(module, "aihelper", None))
                        stack.enter_context(patch.object(module.random, "shuffle"))
                    module.main()
                save.assert_called_once()
                self.assertEqual(len(challenge.tasks), 1)
                self.assertEqual(challenge.tasks[0].to_dict()["features"][0]["properties"]["@id"], "way/4")
                for invalid_id in [1, 2, 3]:
                    self.assertIn(f"Skipping way/{invalid_id}", output.getvalue())

    def test_missing_nursing_home_centers_are_skipped_without_aborting_later_tasks(self):
        for directory in ["amenity_nursing_home", "nursing_home_for"]:
            with self.subTest(generator=directory):
                module = load_script(f"challenges/{directory}/{directory}.py", f"test_center_{directory}")
                elements = [
                    {"type": "relation", "id": 1, "tags": {}},
                    {"type": "relation", "id": 2, "tags": {}, "center": {"lat": 52}},
                    {"type": "node", "id": 3, "tags": {}, "lat": None, "lon": None},
                    {"type": "relation", "id": 4, "tags": {}, "center": {"lat": 52, "lon": 13}},
                ]
                challenge = module.mrcb.Challenge()
                with contextlib.ExitStack() as stack:
                    output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                    stack.enter_context(patch("requests.get", side_effect=AssertionError("Unexpected HTTP request")))
                    stack.enter_context(patch("requests.post", side_effect=AssertionError("Unexpected HTTP request")))
                    stack.enter_context(patch.object(module.mrcb.Overpass, "getElementsFromQuery", return_value=elements))
                    stack.enter_context(patch.object(module.mrcb, "Challenge", return_value=challenge))
                    save = stack.enter_context(patch.object(challenge, "saveToFile"))
                    if directory == "amenity_nursing_home":
                        stack.enter_context(patch.object(module.random, "shuffle"))
                    module.main()
                save.assert_called_once()
                self.assertEqual(len(challenge.tasks), 1)
                self.assertEqual(challenge.tasks[0].to_dict()["features"][0]["properties"]["@id"], "relation/4")
                self.assertIn("Skipping relation/1", output.getvalue())
                self.assertIn("Skipping relation/2", output.getvalue())
                self.assertIn("Skipping node/3", output.getvalue())

    def test_generators_run_from_an_unrelated_directory_and_save_beside_script(self):
        cases = [
            ("amenity_nursing_home", "amenity_nursing_home.py"),
            ("nursing_home_for", "nursing_home_for.py"),
            ("note_abgerissen", "note_abgerissen.py"),
            ("parking_converter", "parking_converter.py"),
        ]
        node = {
            "type": "node", "id": 1, "lat": 52.0, "lon": 13.0,
            "tags": {"note": "abgerissen"},
        }
        way = {
            "type": "way", "id": 2,
            "geometry": [{"lat": 52.0, "lon": 13.0}, {"lat": 52.1, "lon": 13.1}],
            "tags": {"parking:lane:both": "parallel", "parking:lane:both:parallel": "on_street"},
        }
        with tempfile.TemporaryDirectory() as temporary, working_directory(temporary):
            for directory, filename in cases:
                with self.subTest(generator=directory), contextlib.redirect_stdout(io.StringIO()):
                    relative = f"challenges/{directory}/{filename}"
                    # Ensure each script must resolve its own shared import.
                    old_shared = sys.modules.pop("challenge_builder", None)
                    old_path = sys.path[:]
                    try:
                        sys.path[:] = [entry for entry in sys.path if Path(entry or '.').resolve() != ROOT / 'shared']
                        with patch("requests.get", side_effect=AssertionError("Unexpected HTTP request")):
                            module = load_script(relative, f"test_generator_{directory}")
                            challenge = module.mrcb.Challenge()
                            element = way if directory == "parking_converter" else node
                            with contextlib.ExitStack() as stack:
                                stack.enter_context(patch.object(module.mrcb.Overpass, "getElementsFromQuery", return_value=[element]))
                                stack.enter_context(patch.object(module.mrcb, "Challenge", return_value=challenge))
                                save = stack.enter_context(patch.object(challenge, "saveToFile"))
                                if directory == "note_abgerissen":
                                    stack.enter_context(patch.object(module, "fetch_history_info", return_value=module.HistoryInfo(None, None, None, None)))
                                if directory == "parking_converter":
                                    stack.enter_context(patch.object(module, "aihelper", None))
                                module.main()
                            save.assert_called_once_with(ROOT / "challenges" / directory / f"{directory}.json")
                            self.assertEqual(len(challenge.tasks), 1)
                            self.assertEqual(challenge.tasks[0].to_dict()["features"][0]["properties"]["@id"], f"{element['type']}/{element['id']}")
                    finally:
                        sys.path[:] = old_path
                        sys.modules.pop("challenge_builder", None)
                        if old_shared is not None:
                            sys.modules["challenge_builder"] = old_shared

    def test_history_errors_return_empty_information(self):
        module = load_script("challenges/note_abgerissen/note_abgerissen.py", "test_note_history")
        unavailable = Mock(status_code=503)
        invalid_json = Mock(status_code=200)
        invalid_json.json.side_effect = ValueError("Invalid JSON")
        for response in [requests.Timeout("Offline"), unavailable, invalid_json]:
            with self.subTest(response=response):
                get = patch.object(module.requests, "get")
                with get as mocked_get:
                    if isinstance(response, Exception):
                        mocked_get.side_effect = response
                    else:
                        mocked_get.return_value = response
                    info = module.fetch_history_info("way", 123)
                self.assertEqual(info, module.HistoryInfo(None, None, None, None))
                self.assertIsNone(module.build_tagfix("way", 123, info, None))


class OptionalParkingAITests(unittest.TestCase):
    def load_helper(self):
        with patch.dict(sys.modules, {"free_tokens": Mock()}):
            return load_script("challenges/parking_converter/aihelper.py", "test_optional_parking_aihelper")

    def test_import_does_not_read_credentials(self):
        with patch("pathlib.Path.open", side_effect=AssertionError("Credentials were read on import")):
            self.load_helper()

    def test_missing_or_invalid_credentials_disable_ai_without_a_request(self):
        helper = self.load_helper()
        for error in [FileNotFoundError("Missing credentials"), ValueError("Invalid JSON"), KeyError("prompt_id")]:
            with self.subTest(error=error), patch.object(helper, "_load_creds", side_effect=error), patch.object(helper, "OpenAI") as client:
                self.assertFalse(helper.has_ai_configuration())
                self.assertEqual(helper.request_ai_parking_conversion({"type": "way", "id": 1}), (None, None))
                client.assert_not_called()

    def test_unavailable_quota_service_does_not_abort_automatic_conversion(self):
        module = load_script("challenges/parking_converter/parking_converter.py", "test_parking_quota_fallback")
        helper = Mock(DEFAULT_MODEL_ORDER=["test-model"])
        helper.has_ai_configuration.return_value = True
        quota = Mock()
        quota.get_model_with_kontingent_from_list.side_effect = RuntimeError("Quota service offline")
        geometry = [{"lat": 52.0, "lon": 13.0}, {"lat": 52.1, "lon": 13.1}]
        elements = [
            {"type": "way", "id": 1, "geometry": geometry, "tags": {"parking:lane:both": "unrecognized"}},
            {"type": "way", "id": 2, "geometry": geometry, "tags": {"parking:lane:both": "no"}},
        ]
        challenge = module.mrcb.Challenge()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch("requests.get", side_effect=AssertionError("Unexpected HTTP request")))
            stack.enter_context(patch.object(module, "aihelper", helper))
            stack.enter_context(patch.object(module, "free_tokens", quota))
            stack.enter_context(patch.object(module.mrcb.Overpass, "getElementsFromQuery", return_value=elements))
            stack.enter_context(patch.object(module.mrcb, "Challenge", return_value=challenge))
            stack.enter_context(patch.object(challenge, "saveToFile"))
            module.main()
        self.assertEqual(len(challenge.tasks), 1)
        self.assertEqual(challenge.tasks[0].to_dict()["features"][0]["properties"]["@id"], "way/2")
        helper.request_ai_parking_conversion.assert_not_called()


if __name__ == "__main__":
    unittest.main()
