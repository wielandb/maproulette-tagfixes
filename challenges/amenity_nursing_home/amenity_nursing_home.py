import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from shared import challenge_builder as mrcb
from tqdm import tqdm
import random


def checkIsForSeniors(tags):
    if "name" in tags:
        if "senior" in tags["name"].lower():
            return True
        if "altenpfleg" in tags["name"].lower():
            return True
    if "website" in tags:
        if "altenpfleg" in tags["website"].lower():
            return True
    return False

def checkIsAssistedLiving(tags):
    if "name" in tags:
        if "seniorenresidenz" in tags["name"].lower():
            return True
    return False


def main():
    op = mrcb.Overpass()

    elements = op.getElementsFromQuery(
        """
    [out:json][timeout:25];
    area(id:3600051477)->.searchArea;
    nwr["amenity"="nursing_home"](area.searchArea);
    out tags center;
        """
    )

    challenge = mrcb.Challenge()

    random.shuffle(elements)

    for element in tqdm(elements):
        if challenge.limit_reached:
            break
        isForSeniors = checkIsForSeniors(element["tags"])
        isAssistedLiving = checkIsAssistedLiving(element["tags"])
        try:
            geom = mrcb.getElementCenterPoint(element)
            mainFeature = mrcb.GeoFeature.withId(
                element["type"], element["id"], geom, properties={}
            )
        except (KeyError, TypeError, ValueError) as exc:
            print(f"Skipping {element['type']}/{element['id']} without a usable center: {exc}")
            continue
        if isAssistedLiving:
            cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                {"amenity":"social_facility", "social_facility":"assisted_living", "social_facility:for":"senior"}
            )
        elif isForSeniors:
            cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                {"amenity":"social_facility", "social_facility":"nursing_home", "social_facility:for":"senior"}
            )
        else:
            cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                {"amenity":"social_facility", "social_facility":"nursing_home"}
            )
        t = mrcb.Task(
            mainFeature,
            additionalFeatures=[],
            cooperativeWork=cooperativeWork
        )
        if not challenge.addTask(t):
            break

    challenge.saveToFile(SCRIPT_DIR / "amenity_nursing_home.json")


if __name__ == "__main__":
    main()
