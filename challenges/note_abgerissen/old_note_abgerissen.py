import sys
sys.path.append('../../shared')
import challenge_builder as mrcb
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
        challenge.addTask(t)

challenge.saveToFile("note_abgerissen.json")