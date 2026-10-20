import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parents[1]))
from shared import challenge_builder as mrcb
from tqdm import tqdm

def needs_task(element):
    # true if the length of all tags is 1
    return len(element["tags"]) == 1


op = mrcb.Overpass()
print("Fetching elements from Overpass...")

elements = op.getElementsFromQuery(
    """
[out:json][timeout:250];
area(id:3600051477)->.searchArea;
nwr["note"~"bgerissen"](if:count_tags()==1)(area.searchArea);
out tags center;
    """
)


challenge = mrcb.Challenge()

for element in tqdm(elements):
    if challenge.limit_reached:
        break
    if needs_task(element):
        geom = mrcb.getElementCenterPoint(element)
        mainFeature = mrcb.GeoFeature.withId(
            element["type"],
            element["id"],
            geom,
            properties={}
        )
        t = mrcb.Task(
            mainFeature
        )
        if not challenge.addTask(t):
            break

challenge.saveToFile("note_abgerissen.json")
