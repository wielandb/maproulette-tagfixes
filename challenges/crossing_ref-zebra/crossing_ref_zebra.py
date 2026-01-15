import sys
sys.path.append('../../shared')
import challenge_builder as mrcb
from tqdm import tqdm

def needs_task(element):
    return True


op = mrcb.Overpass()
print("Fetching elements from Overpass...")

elements = op.getElementsFromQuery(
    """
[out:json][timeout:250];
area(id:3600051477)->.searchArea;
nwr["highway"="crossing"]["crossing:markings"="zebra"]["crossing_ref"!="zebra"](area.searchArea);
nwr["highway"="crossing"]["crossing"="zebra"]["crossing_ref"!="zebra"](area.searchArea);
out center body;
"""
)


challenge = mrcb.Challenge()

for element in tqdm(elements):
    if needs_task(element):
        geom = mrcb.getElementCenterPoint(element)
        mainFeature = mrcb.GeoFeature.withId(
            element["type"],
            element["id"],
            geom,
            properties={}
        )
        cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                {"crossing_ref": "zebra"},
            )
        t = mrcb.Task(
            mainFeature,
            [],
            cooperativeWork
        )
        challenge.addTask(t)

challenge.saveToFile("crossing_ref_zebra.json")
