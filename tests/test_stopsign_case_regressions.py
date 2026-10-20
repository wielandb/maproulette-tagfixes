import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "stopsign_case_regressions", ROOT / "challenges/stopsign-directions/directions.py"
)
directions = importlib.util.module_from_spec(spec)
with patch("requests.get", side_effect=AssertionError("Unexpected network request")), \
        patch("requests.post", side_effect=AssertionError("Unexpected network request")):
    spec.loader.exec_module(directions)

CASES = json.loads(
    (ROOT / "tests/fixtures/stopsign_51016_examples.json").read_text(encoding="utf-8")
)["cases"]


class StopsignCaseRegressions(unittest.TestCase):
    def test_reported_situations_with_current_osm_road_geometry(self):
        for case in CASES:
            with self.subTest(task=case["task_id"]):
                handler = directions.OSMDataHandler({"elements": case["elements"]})
                self.assertEqual(
                    handler.determine_give_way_direction(case["node_id"], case["way_id"]),
                    case["expected"],
                )

    def test_reported_situations_generate_only_supported_proposals(self):
        for case in CASES:
            with self.subTest(task=case["task_id"]):
                # Replay the missing-direction input, retaining today's topology.
                elements = copy.deepcopy(case["elements"])
                sign = next(e for e in elements if e["type"] == "node" and e["id"] == case["node_id"])
                sign["tags"].pop("direction", None)
                handler = directions.OSMDataHandler(
                    {"elements": elements}, candidate_node_ids={case["node_id"]}
                )
                challenge = directions.mrcb.Challenge()
                with patch("requests.get", side_effect=AssertionError("Unexpected network request")), \
                        patch("requests.post", side_effect=AssertionError("Unexpected network request")):
                    directions.populate_challenge(challenge, handler, sign["tags"]["highway"])
                if case["expected"] is None:
                    self.assertEqual(challenge.tasks, [])
                else:
                    self.assertEqual(len(challenge.tasks), 1)
                    self.assertEqual(
                        challenge.tasks[0].cooperativeWork.tagsToSet,
                        {"direction": case["expected"]},
                    )


if __name__ == "__main__":
    unittest.main()
