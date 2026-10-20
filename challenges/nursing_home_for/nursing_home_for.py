import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from shared import challenge_builder as mrcb
from tqdm import tqdm

def main():
    op = mrcb.Overpass()

    elements = op.getElementsFromQuery(
        """
    [out:json][timeout:250];
    area(id:3600051477)->.searchArea;
    nwr["amenity"="social_facility"]["social_facility"="nursing_home"][!"social_facility:for"](area.searchArea);
    out tags center;
        """
    )

    challenge = mrcb.Challenge()

    for element in elements:
        if challenge.limit_reached:
            break
        try:
            geom = mrcb.getElementCenterPoint(element)
            mainFeature = mrcb.GeoFeature.withId(
                element["type"], element["id"], geom, properties={}
            )
        except (KeyError, TypeError, ValueError) as exc:
            print(f"Skipping {element['type']}/{element['id']} without a usable center: {exc}")
            continue
        t = mrcb.Task(
            mainFeature
        )
        if not challenge.addTask(t):
            break

    challenge.saveToFile(SCRIPT_DIR / "nursing_home_for.json")


if __name__ == "__main__":
    main()
