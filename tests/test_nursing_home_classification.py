import contextlib
import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "nursing_home_classification", ROOT / "challenges/amenity_nursing_home/amenity_nursing_home.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class NursingHomeClassificationTests(unittest.TestCase):
    def test_residence_detection_is_case_insensitive(self):
        for name in ["Seniorenresidenz am Park", "SENIORENRESIDENZ", "seniorenresidenz"]:
            with self.subTest(name=name):
                self.assertTrue(generator.checkIsAssistedLiving({"name": name}))
        self.assertFalse(generator.checkIsAssistedLiving({"name": "Seniorenpflegeheim"}))

    def test_specific_residence_suggestion_takes_precedence_over_senior_keyword(self):
        names = ["Seniorenresidenz am Park", "Seniorenpflegeheim", "Pflegeeinrichtung"]
        elements = [
            {"type": "node", "id": i, "lat": 52.0, "lon": 13.0,
             "tags": {"amenity": "nursing_home", "name": name}}
            for i, name in enumerate(names, 1)
        ]
        challenge = generator.mrcb.Challenge()
        with contextlib.ExitStack() as stack:
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            stack.enter_context(patch.object(generator.random, "shuffle"))
            stack.enter_context(patch.object(generator.mrcb.Overpass, "getElementsFromQuery", return_value=elements))
            stack.enter_context(patch.object(generator.mrcb, "Challenge", return_value=challenge))
            stack.enter_context(patch.object(challenge, "saveToFile"))
            generator.main()
        tags = [task.cooperativeWork.tagsToSet for task in challenge.tasks]
        self.assertEqual([item["social_facility"] for item in tags], ["assisted_living", "nursing_home", "nursing_home"])
        self.assertEqual(tags[0]["social_facility:for"], "senior")
        self.assertEqual(tags[1]["social_facility:for"], "senior")
        self.assertNotIn("social_facility:for", tags[2])


if __name__ == "__main__":
    unittest.main()
