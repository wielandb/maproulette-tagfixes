import sys
sys.path.append('../../shared')
import challenge_builder as mrcb
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
        if "Seniorenresidenz" in tags["name"].lower():
            return True
    return False


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
    isForSeniors = checkIsForSeniors(element["tags"])
    isAssistedLiving = checkIsAssistedLiving(element["tags"])
    geom = mrcb.getElementCenterPoint(element)
    mainFeature = mrcb.GeoFeature.withId(
        element["type"],
        element["id"],
        geom,
        properties={}
    )
    if isForSeniors:
        cooperativeWork = mrcb.TagFix(
            element["type"],
            element["id"],
            {"amenity":"social_facility", "social_facility":"nursing_home", "social_facility:for":"senior"}
        )
    elif isAssistedLiving:
        cooperativeWork = mrcb.TagFix(
            element["type"],
            element["id"],
            {"amenity":"social_facility", "social_facility":"assisted_living", "social_facility:for":"senior"}
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
    challenge.addTask(t)

challenge.saveToFile("amenity_nursing_home.json")
