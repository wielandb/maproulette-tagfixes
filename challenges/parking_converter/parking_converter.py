import sys
sys.path.append('../../shared')
import challenge_builder as mrcb
from tqdm import tqdm
import random

"""
Parallel on_street
{"parking:lane:right":"parallel", "parking:lane:right:parallel":"on_street"} -> {"parking:right":"on_street", "parking:right:orientation":"parallel"}
{"parking:lane:left":"parallel", "parking:lane:left:parallel":"on_street"} -> {"parking:left":"on_street", "parking:left:orientation":"parallel"}
{"parking:lane:both":"parallel", "parking:lane:both:parallel":"on_street"} -> {"parking:both":"on_street", "parking:both:orientation":"parallel"}

Parallel half_on_kerb
{"parking:lane:right":"parallel", "parking:lane:right:parallel":"half_on_kerb"} -> {"parking:right":"half_on_kerb", "parking:right:orientation":"parallel"}
{"parking:lane:left":"parallel", "parking:lane:left:parallel":"half_on_kerb"} -> {"parking:left":"half_on_kerb", "parking:left:orientation":"parallel"}
{"parking:lane:both":"parallel", "parking:lane:both:parallel":"half_on_kerb"} -> {"parking:both":"half_on_kerb", "parking:both:orientation":"parallel"}

Parallel on_kerb
{"parking:lane:right":"parallel", "parking:lane:right:parallel":"on_kerb"} -> {"parking:right":"on_kerb", "parking:right:orientation":"parallel"}
{"parking:lane:left":"parallel", "parking:lane:left:parallel":"on_kerb"} -> {"parking:left":"on_kerb", "parking:left:orientation":"parallel"}
{"parking:lane:both":"parallel", "parking:lane:both:parallel":"on_kerb"} -> {"parking:both":"on_kerb", "parking:both:orientation":"parallel"}

Parallel street_side
{"parking:lane:right":"parallel", "parking:lane:right:parallel":"street_side"} -> {"parking:right":"street_side", "parking:right:orientation":"parallel"}
{"parking:lane:left":"parallel", "parking:lane:left:parallel":"street_side"} -> {"parking:left":"street_side", "parking:left:orientation":"parallel"}
{"parking:lane:both":"parallel", "parking:lane:both:parallel":"street_side"} -> {"parking:both":"street_side", "parking:both:orientation":"parallel"}

diagonal on_street
{"parking:lane:right":"diagonal", "parking:lane:right:diagonal":"on_street"} -> {"parking:right":"on_street", "parking:right:orientation":"diagonal"}
{"parking:lane:left":"diagonal", "parking:lane:left:diagonal":"on_street"} -> {"parking:left":"on_street", "parking:left:orientation":"diagonal"}
{"parking:lane:both":"diagonal", "parking:lane:both:diagonal":"on_street"} -> {"parking:both":"on_street", "parking:both:orientation":"diagonal"}

diagonal half_on_kerb
{"parking:lane:right":"diagonal", "parking:lane:right:diagonal":"half_on_kerb"} -> {"parking:right":"half_on_kerb", "parking:right:orientation":"diagonal"}
{"parking:lane:left":"diagonal", "parking:lane:left:diagonal":"half_on_kerb"} -> {"parking:left":"half_on_kerb", "parking:left:orientation":"diagonal"}
{"parking:lane:both":"diagonal", "parking:lane:both:diagonal":"half_on_kerb"} -> {"parking:both":"half_on_kerb", "parking:both:orientation":"diagonal"}

diagonal on_kerb
{"parking:lane:right":"diagonal", "parking:lane:right:diagonal":"on_kerb"} -> {"parking:right":"on_kerb", "parking:right:orientation":"diagonal"}
{"parking:lane:left":"diagonal", "parking:lane:left:diagonal":"on_kerb"} -> {"parking:left":"on_kerb", "parking:left:orientation":"diagonal"}
{"parking:lane:both":"diagonal", "parking:lane:both:diagonal":"on_kerb"} -> {"parking:both":"on_kerb", "parking:both:orientation":"diagonal"}

diagonal street_side
{"parking:lane:right":"diagonal", "parking:lane:right:diagonal":"street_side"} -> {"parking:right":"street_side", "parking:right:orientation":"diagonal"}
{"parking:lane:left":"diagonal", "parking:lane:left:diagonal":"street_side"} -> {"parking:left":"street_side", "parking:left:orientation":"diagonal"}
{"parking:lane:both":"diagonal", "parking:lane:both:diagonal":"street_side"} -> {"parking:both":"street_side", "parking:both:orientation":"diagonal"}

perpendicular on_street
{"parking:lane:right":"perpendicular", "parking:lane:right:perpendicular":"on_street"} -> {"parking:right":"on_street", "parking:right:orientation":"perpendicular"}
{"parking:lane:left":"perpendicular", "parking:lane:left:perpendicular":"on_street"} -> {"parking:left":"on_street", "parking:left:orientation":"perpendicular"}
{"parking:lane:both":"perpendicular", "parking:lane:both:perpendicular":"on_street"} -> {"parking:both":"on_street", "parking:both:orientation":"perpendicular"}

perpendicular half_on_kerb
{"parking:lane:right":"perpendicular", "parking:lane:right:perpendicular":"half_on_kerb"} -> {"parking:right":"half_on_kerb", "parking:right:orientation":"perpendicular"}
{"parking:lane:left":"perpendicular", "parking:lane:left:perpendicular":"half_on_kerb"} -> {"parking:left":"half_on_kerb", "parking:left:orientation":"perpendicular"}
{"parking:lane:both":"perpendicular", "parking:lane:both:perpendicular":"half_on_kerb"} -> {"parking:both":"half_on_kerb", "parking:both:orientation":"perpendicular"}

perpendicular on_kerb
{"parking:lane:right":"perpendicular", "parking:lane:right:perpendicular":"on_kerb"} -> {"parking:right":"on_kerb", "parking:right:orientation":"perpendicular"}
{"parking:lane:left":"perpendicular", "parking:lane:left:perpendicular":"on_kerb"} -> {"parking:left":"on_kerb", "parking:left:orientation":"perpendicular"}
{"parking:lane:both":"perpendicular", "parking:lane:both:perpendicular":"on_kerb"} -> {"parking:both":"on_kerb", "parking:both:orientation":"perpendicular"}

perpendicular street_side
{"parking:lane:right":"perpendicular", "parking:lane:right:perpendicular":"street_side"} -> {"parking:right":"street_side", "parking:right:orientation":"perpendicular"}
{"parking:lane:left":"perpendicular", "parking:lane:left:perpendicular":"street_side"} -> {"parking:left":"street_side", "parking:left:orientation":"perpendicular"}
{"parking:lane:both":"perpendicular", "parking:lane:both:perpendicular":"street_side"} -> {"parking:both":"street_side", "parking:both:orientation":"perpendicular"}
"""

def convert_base_parking_tags(tags):
    if "parking:lane:right" in tags:
        if tags["parking:lane:right"] == "parallel":
            if "parking:lane:right:parallel" in tags:
                if tags["parking:lane:right:parallel"] == "on_street":
                    tags["parking:right"] = "on_street"
                    tags["parking:right:orientation"] = "parallel"
                elif tags["parking:lane:right:parallel"] == "half_on_kerb":
                    tags["parking:right"] = "half_on_kerb"
                    tags["parking:right:orientation"] = "parallel"
                elif tags["parking:lane:right:parallel"] == "on_kerb":
                    tags["parking:right"] = "on_kerb"
                    tags["parking:right:orientation"] = "parallel"
                elif tags["parking:lane:right:parallel"] == "street_side":
                    tags["parking:right"] = "street_side"
                    tags["parking:right:orientation"] = "parallel"
        elif tags["parking:lane:right"] == "diagonal":
            if "parking:lane:right:diagonal" in tags:
                if tags["parking:lane:right:diagonal"] == "on_street":
                    tags["parking:right"] = "on_street"
                    tags["parking:right:orientation"] = "diagonal"
                elif tags["parking:lane:right:diagonal"] == "half_on_kerb":
                    tags["parking:right"] = "half_on_kerb"
                    tags["parking:right:orientation"] = "diagonal"
                elif tags["parking:lane:right:diagonal"] == "on_kerb":
                    tags["parking:right"] = "on_kerb"
                    tags["parking:right:orientation"] = "diagonal"
                elif tags["parking:lane:right:diagonal"] == "street_side":
                    tags["parking:right"] = "street_side"
                    tags["parking:right:orientation"] = "diagonal"
        elif tags["parking:lane:right"] == "perpendicular":
            if "parking:lane:right:perpendicular" in tags:
                if tags["parking:lane:right:perpendicular"] == "on_street":
                    tags["parking:right"] = "on_street"
                    tags["parking:right:orientation"] = "perpendicular"
                elif tags["parking:lane:right:perpendicular"] == "half_on_kerb":
                    tags["parking:right"] = "half_on_kerb"
                    tags["parking:right:orientation"] = "perpendicular"
                elif tags["parking:lane:right:perpendicular"] == "on_kerb":
                    tags["parking:right"] = "on_kerb"
                    tags["parking:right:orientation"] = "perpendicular"
                elif tags["parking:lane:right:perpendicular"] == "street_side":
                    tags["parking:right"] = "street_side"
                    tags["parking:right:orientation"] = "perpendicular"
    if "parking:lane:left" in tags:
        if tags["parking:lane:left"] == "parallel":
            if "parking:lane:left:parallel" in tags:
                if tags["parking:lane:left:parallel"] == "on_street":
                    tags["parking:left"] = "on_street"
                    tags["parking:left:orientation"] = "parallel"
                elif tags["parking:lane:left:parallel"] == "half_on_kerb":
                    tags["parking:left"] = "half_on_kerb"
                    tags["parking:left:orientation"] = "parallel"
                elif tags["parking:lane:left:parallel"] == "on_kerb":
                    tags["parking:left"] = "on_kerb"
                    tags["parking:left:orientation"] = "parallel"
                elif tags["parking:lane:left:parallel"] == "street_side":
                    tags["parking:left"] = "street_side"
                    tags["parking:left:orientation"] = "parallel"
        elif tags["parking:lane:left"] == "diagonal":
            if "parking:lane:left:diagonal" in tags:
                if tags["parking:lane:left:diagonal"] == "on_street":
                    tags["parking:left"] = "on_street"
                    tags["parking:left:orientation"] = "diagonal"
                elif tags["parking:lane:left:diagonal"] == "half_on_kerb":
                    tags["parking:left"] = "half_on_kerb"
                    tags["parking:left:orientation"] = "diagonal"
                elif tags["parking:lane:left:diagonal"] == "on_kerb":
                    tags["parking:left"] = "on_kerb"
                    tags["parking:left:orientation"] = "diagonal"
                elif tags["parking:lane:left:diagonal"] == "street_side":
                    tags["parking:left"] = "street_side"
                    tags["parking:left:orientation"] = "diagonal"
        elif tags["parking:lane:left"] == "perpendicular":
            if "parking:lane:left:perpendicular" in tags:
                if tags["parking:lane:left:perpendicular"] == "on_street":
                    tags["parking:left"] = "on_street"
                    tags["parking:left:orientation"] = "perpendicular"
                elif tags["parking:lane:left:perpendicular"] == "half_on_kerb":
                    tags["parking:left"] = "half_on_kerb"
                    tags["parking:left:orientation"] = "perpendicular"
                elif tags["parking:lane:left:perpendicular"] == "on_kerb":
                    tags["parking:left"] = "on_kerb"
                    tags["parking:left:orientation"] = "perpendicular"
                elif tags["parking:lane:left:perpendicular"] == "street_side":
                    tags["parking:left"] = "street_side"
                    tags["parking:left:orientation"] = "perpendicular"
    if "parking:lane:both" in tags:
        if tags["parking:lane:both"] == "parallel":
            if "parking:lane:both:parallel" in tags:
                if tags["parking:lane:both:parallel"] == "on_street":
                    tags["parking:both"] = "on_street"
                    tags["parking:both:orientation"] = "parallel"
                elif tags["parking:lane:both:parallel"] == "half_on_kerb":
                    tags["parking:both"] = "half_on_kerb"
                    tags["parking:both:orientation"] = "parallel"
                elif tags["parking:lane:both:parallel"] == "on_kerb":
                    tags["parking:both"] = "on_kerb"
                    tags["parking:both:orientation"] = "parallel"
                elif tags["parking:lane:both:parallel"] == "street_side":
                    tags["parking:both"] = "street_side"
                    tags["parking:both:orientation"] = "parallel"
        elif tags["parking:lane:both"] == "diagonal":
            if "parking:lane:both:diagonal" in tags:
                if tags["parking:lane:both:diagonal"] == "on_street":
                    tags["parking:both"] = "on_street"
                    tags["parking:both:orientation"] = "diagonal"
                elif tags["parking:lane:both:diagonal"] == "half_on_kerb":
                    tags["parking:both"] = "half_on_kerb"
                    tags["parking:both:orientation"] = "diagonal"
                elif tags["parking:lane:both:diagonal"] == "on_kerb":
                    tags["parking:both"] = "on_kerb"
                    tags["parking:both:orientation"] = "diagonal"
                elif tags["parking:lane:both:diagonal"] == "street_side":
                    tags["parking:both"] = "street_side"
                    tags["parking:both:orientation"] = "diagonal"
        elif tags["parking:lane:both"] == "perpendicular":
            if "parking:lane:both:perpendicular" in tags:
                if tags["parking:lane:both:perpendicular"] == "on_street":
                    tags["parking:both"] = "on_street"
                    tags["parking:both:orientation"] = "perpendicular"
                elif tags["parking:lane:both:perependicular"] == "half_on_kerb":
                    tags["parking:both"] = "half_on_kerb"
                    tags["parking:both:orientation"] = "perpendicular"
                elif tags["parking:lane:both:perpendicular"] == "on_kerb":
                    tags["parking:both"] = "on_kerb"
                    tags["parking:both:orientation"] = "perpendicular"
                elif tags["parking:lane:both:perpendicular"] == "street_side":
                    tags["parking:both"] = "street_side"
                    tags["parking:both:orientation"] = "perpendicular"
    # remove the old tags (set them to null)
    for tag in tags:
        if tag in ["parking:lane:right", "parking:lane:right:parallel", "parking:lane:right:diagonal", "parking:lane:right:perpendicular"]:
            tags[tag] = None
        if tag in ["parking:lane:left", "parking:lane:left:parallel", "parking:lane:left:diagonal", "parking:lane:left:perpendicular"]:
            tags[tag] = None
        if tag in ["parking:lane:both", "parking:lane:both:parallel", "parking:lane:both:diagonal", "parking:lane:both:perpendicular"]:
            tags[tag] = None
    return tags


def are_all_old_parking_tags_gone(tags):
    # this is to check that all old parking tags are gone
    # This is to check for things like parking:condition:left
    # So, this function will return False if there are any tags that have "parking" in them but arent one of the new tags (the old tags are allowed to be there if they are null)
    # The new Tags: parking:right, parking:left, parking:both, parking:right:orientation, parking:left:orientation, parking:both:orientation
    for tag in tags:
        if "parking" in tag:
            if tag not in ["parking:right", "parking:left", "parking:both", "parking:right:orientation", "parking:left:orientation", "parking:both:orientation"]:
                if tags[tag] != None:
                    # print the offending tag
                    print(tag)
                    return False            
    return True


def get_tag_diff(oldTags, newTags):
    # This function takes two dictionarys and returns a dictionary that only contains the keys that are either not present in both or have different values
    pass

op = mrcb.Overpass()

elements = op.getElementsFromQuery(
    """
[out:json][timeout:250];
nwr["parking:lane:right"](49.84152514611125,10.409545898437502,52.633062890594374,14.644775390625002);
nwr["parking:lane:both"](49.84152514611125,10.409545898437502,52.633062890594374,14.644775390625002);
nwr["parking:lane:left"](49.84152514611125,10.409545898437502,52.633062890594374,14.644775390625002);
out geom;
    """
)

challenge = mrcb.Challenge()

random.shuffle(elements)

for element in tqdm(elements):
    geom = mrcb.getElementCenterPoint(element)
    newTags = convert_base_parking_tags(element["tags"])
    mainFeature = mrcb.GeoFeature.withId(
        element["type"],
        element["id"],
        geom,
        properties={}
    )
    # Only provide cooperative work if there are no old parking tags left
    if are_all_old_parking_tags_gone(newTags):
        cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                newTags
            )
    else:
        cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                {"thistagwillneverbepresentandwillnotchangetags":None}
            )
    t = mrcb.Task(
        mainFeature,
        additionalFeatures=[],
        cooperativeWork=cooperativeWork
    )


    challenge.addTask(t)

challenge.saveToFile("parking_converter.json")