import requests
from time import sleep
import random
import sys
sys.path.append('../../shared')
import challenge_builder as mrcb
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x, *args, **kwargs):
        return x



def check_imgur_404(link):
    # Build some headers to make the request look like it's coming from a browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
    }
    if ";" in link:
        return False
    # remove .jpg from the link
    link = link.replace(".jpg", "")
    link = link.replace(".png", "")
    link = link.replace(".jpeg", "")
    # remove i. from the link
    link = link.replace("i.", "")
    # Replace http with https
    link = link.replace("http://", "https://")
    reqSucc = False
    while not reqSucc:
        try:
            ans = requests.get(link, headers=headers, allow_redirects=True)
            reqSucc = True
        except requests.exceptions.ConnectionError:
            print("Connection error, retrying")
            print(link)
            sleep(10)
        except (requests.exceptions.InvalidSchema, requests.exceptions.MissingSchema):
            return False
    print(ans.status_code)
    if "error/404" in ans.url:
        print(link, "is a 404 image")
        return True
    else:
        return False

op = mrcb.Overpass()

elements = op.getElementsFromQuery(
    """
    [out:json][timeout:250];
    nwr["image"~"i.imgur.com"];
    out tags center;
    """
)
challenge = mrcb.Challenge()

random.shuffle(elements)

for element in tqdm(elements):
    if check_imgur_404(element["tags"]["image"]):
        tagChanges = {"image":None}
        if "source" in element["tags"]:
            if "anasonic" in element["tags"]["source"]:
                tagChanges["source"] = None
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
            tagChanges
        )
        t = mrcb.Task(
            mainFeature,
            additionalFeatures=[],
            cooperativeWork=cooperativeWork
        )
        challenge.addTask(t)
        challenge.saveToFile("imgur404.json")
