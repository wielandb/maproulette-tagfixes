import sys
sys.path.append('../../shared')
import challenge_builder as mrcb
from tqdm import tqdm

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

challenge.saveToFile("nursing_home_for.json")
