import sys
sys.path.append('../../shared')
import challenge_builder as mrcb
from tqdm import tqdm
import random
import copy

MSG_COMPLETE = """
The street parking tags for this side could all successfully be converted to the new format. There are no tags left that contain "parking" in any way.
- ✔️ For every tag from the old scheme, an equivalent tag from the new scheme was found and added
- ✔️ There are no tags left that contain "parking" in any way
Check the proposed tags and if they seem logical, you can accept them.
"""

MSG_INCOMPLETE_1 = """
**⚠️ Incomplete conversion! Please edit manually!**

❗ The street parking tags for this side could not all be converted to the new format. There are still tags left that contain "parking" in some way.
The following tags could not be converted:
"""

MSG_INCOMPLETE_2 = """

Please convert this street parking side to the new format manually, giving special attention to theese tags where no automatic conversion was possible!
(It could very well be that the tags that were not converted automatically are a mixture of new and old tags, so the right solution might be to just convert the base tags as normal)
"""

def convert_base_parking_tags(tags):
    tagChanges = {} # to set a new tag: "newTag": "newValue", to unset a tag: "oldTag": None
    # Go thhrough all tags; if a tag contains parking and the value is "lay_by", change the value of this tag to street_side
    for key in tags:
        if "parking" in key and tags[key] == "lay_by":
            tags[key] = "street_side" # In this case, we want to manipulate the tags themself, not the tagChanges dict
    # The normal conversion if-cascade
    if "parking:lane:right" in tags:
        if tags["parking:lane:right"] == "parallel":
            tagChanges["parking:right:orientation"] = "parallel"
            tagChanges["parking:lane:right"] = None
            if "parking:lane:right:parallel" in tags:
                if tags["parking:lane:right:parallel"] == "on_street":
                    tagChanges["parking:right"] = "on_street"
                    tagChanges["parking:lane:right:parallel"] = None
                elif tags["parking:lane:right:parallel"] == "half_on_kerb":
                    tagChanges["parking:right"] = "half_on_kerb"
                    tagChanges["parking:lane:right:parallel"] = None
                elif tags["parking:lane:right:parallel"] == "on_kerb":
                    tagChanges["parking:right"] = "on_kerb"
                    tagChanges["parking:lane:right:parallel"] = None
                elif tags["parking:lane:right:parallel"] == "street_side":
                    tagChanges["parking:right"] = "street_side"
                    tagChanges["parking:lane:right:parallel"] = None
                elif tags["parking:lane:right:parallel"] == "painted_area_only":
                    tagChanges["parking:right"] = "on_street"
                    tagChanges["parking:right:markings"] = "yes"
                    tagChanges["parking:lane:right:parallel"] = None
                elif tags["parking:lane:right:parallel"] == "marked":
                    tagChanges["parking:right:markings"] = "yes"
                    tagChanges["parking:right"] = "yes" # Set the generic "yes" so that it's noted that you can obviously park there, but its unclear how
                    tagChanges["parking:lane:right:parallel"] = None
        elif tags["parking:lane:right"] == "diagonal":
            tagChanges["parking:right:orientation"] = "diagonal"
            tagChanges["parking:lane:right"] = None
            if "parking:lane:right:diagonal" in tags:
                if tags["parking:lane:right:diagonal"] == "on_street":
                    tagChanges["parking:right"] = "on_street"
                    tagChanges["parking:lane:right:diagonal"] = None
                elif tags["parking:lane:right:diagonal"] == "half_on_kerb":
                    tagChanges["parking:right"] = "half_on_kerb"
                    tagChanges["parking:lane:right:diagonal"] = None
                elif tags["parking:lane:right:diagonal"] == "on_kerb":
                    tagChanges["parking:right"] = "on_kerb"
                    tagChanges["parking:lane:right:diagonal"] = None
                elif tags["parking:lane:right:diagonal"] == "street_side":
                    tagChanges["parking:right"] = "street_side"
                    tagChanges["parking:lane:right:diagonal"] = None
                elif tags["parking:lane:right:diagonal"] == "painted_area_only":
                    tagChanges["parking:right"] = "on_street"
                    tagChanges["parking:right:markings"] = "yes"
                    tagChanges["parking:lane:right:diagonal"] = None
                elif tags["parking:lane:right:diagonal"] == "marked":
                    tagChanges["parking:right:markings"] = "yes"
                    tagChanges["parking:right"] = "yes" # Set the generic "yes" so that it's noted that you can obviously park there, but its unclear how
                    tagChanges["parking:lane:right:diagonal"] = None
        elif tags["parking:lane:right"] == "perpendicular":
            tagChanges["parking:right:orientation"] = "perpendicular"
            tagChanges["parking:lane:right"] = None
            if "parking:lane:right:perpendicular" in tags:
                if tags["parking:lane:right:perpendicular"] == "on_street":
                    tagChanges["parking:right"] = "on_street"
                    tagChanges["parking:lane:right:perpendicular"] = None
                elif tags["parking:lane:right:perpendicular"] == "half_on_kerb":
                    tagChanges["parking:right"] = "half_on_kerb"
                    tagChanges["parking:lane:right:perpendicular"] = None
                elif tags["parking:lane:right:perpendicular"] == "on_kerb":
                    tagChanges["parking:right"] = "on_kerb"
                    tagChanges["parking:lane:right:perpendicular"] = None
                elif tags["parking:lane:right:perpendicular"] == "street_side":
                    tagChanges["parking:right"] = "street_side"
                    tagChanges["parking:lane:right:perpendicular"] = None
                elif tags["parking:lane:right:perpendicular"] == "painted_area_only":
                    tagChanges["parking:right"] = "on_street"
                    tagChanges["parking:right:markings"] = "yes"
                    tagChanges["parking:lane:right:perpendicular"] = None
                elif tags["parking:lane:right:perpendicular"] == "marked":
                    tagChanges["parking:right:markings"] = "yes"
                    tagChanges["parking:right"] = "yes" # Set the generic "yes" so that it's noted that you can obviously park there, but its unclear how
                    tagChanges["parking:lane:right:perpendicular"] = None
        elif tags["parking:lane:right"] == "no":
            tagChanges["parking:right"] = "no"
            tagChanges["parking:lane:right"] = None
        elif tags["parking:lane:right"] == "no_parking":
            tagChanges["parking:right"] = "no"
            tagChanges["parking:right:restriction"] = "no_parking"
            tagChanges["parking:lane:right"] = None
        elif tags["parking:lane:right"] == "no_stopping":
            tagChanges["parking:right"] = "no"
            tagChanges["parking:right:restriction"] = "no_stopping"
            tagChanges["parking:lane:right"] = None
        elif tags["parking:lane:right"] == "no_standing":
            tagChanges["parking:right"] = "no"
            tagChanges["parking:right:restriction"] = "no_standing"
            tagChanges["parking:lane:right"] = None
        elif tags["parking:lane:right"] == "separate":
            tagChanges["parking:right"] = "separate"
            tagChanges["parking:lane:right"] = None
        elif tags["parking:lane:right"] == "marked":
            tagChanges["parking:right:markings"] = "yes"
            tagChanges["parking:lane:right"] = None
        elif tags["parking:lane:right"] == "marked" and "parking:lane:right:marked" in tags:
            if tags["parking:lane:right:marked"] == "on_street":
                tagChanges["parking:right"] = "on_street"
                tagChanges["parking:right:markings"] = "yes"
                tagChanges["parking:lane:right:marked"] = None
            elif tags["parking:lane:right:marked"] == "half_on_kerb":
                tagChanges["parking:right"] = "half_on_kerb"
                tagChanges["parking:right:markings"] = "yes"
                tagChanges["parking:lane:right:marked"] = None
            elif tags["parking:lane:right:marked"] == "on_kerb":
                tagChanges["parking:right"] = "on_kerb"
                tagChanges["parking:right:markings"] = "yes"
                tagChanges["parking:lane:right:marked"] = None
            elif tags["parking:lane:right:marked"] == "street_side":
                tagChanges["parking:right"] = "street_side"
                tagChanges["parking:right:markings"] = "yes"
                tagChanges["parking:lane:right:marked"] = None
    # Left side
    if "parking:lane:left" in tags:
        if tags["parking:lane:left"] == "parallel":
            tagChanges["parking:left:orientation"] = "parallel"
            tagChanges["parking:lane:left"] = None
            if "parking:lane:left:parallel" in tags:
                if tags["parking:lane:left:parallel"] == "on_street":
                    tagChanges["parking:left"] = "on_street"
                    tagChanges["parking:lane:left:parallel"] = None
                elif tags["parking:lane:left:parallel"] == "half_on_kerb":
                    tagChanges["parking:left"] = "half_on_kerb"
                    tagChanges["parking:lane:left:parallel"] = None
                elif tags["parking:lane:left:parallel"] == "on_kerb":
                    tagChanges["parking:left"] = "on_kerb"
                    tagChanges["parking:lane:left:parallel"] = None
                elif tags["parking:lane:left:parallel"] == "street_side":
                    tagChanges["parking:left"] = "street_side"
                    tagChanges["parking:lane:left:parallel"] = None
                elif tags["parking:lane:left:parallel"] == "painted_area_only":
                    tagChanges["parking:left"] = "on_street"
                    tagChanges["parking:left:markings"] = "yes"
                    tagChanges["parking:lane:left:parallel"] = None
                elif tags["parking:lane:left:parallel"] == "marked":
                    tagChanges["parking:left:markings"] = "yes"
                    tagChanges["parking:left"] = "yes" # Set the generic "yes" so that it's noted that you can obviously park there, but its unclear how
                    tagChanges["parking:lane:left:parallel"] = None
        elif tags["parking:lane:left"] == "diagonal":
            tagChanges["parking:left:orientation"] = "diagonal"
            tagChanges["parking:lane:left"] = None
            if "parking:lane:left:diagonal" in tags:
                if tags["parking:lane:left:diagonal"] == "on_street":
                    tagChanges["parking:left"] = "on_street"
                    tagChanges["parking:lane:left:diagonal"] = None
                elif tags["parking:lane:left:diagonal"] == "half_on_kerb":
                    tagChanges["parking:left"] = "half_on_kerb"
                    tagChanges["parking:lane:left:diagonal"] = None
                elif tags["parking:lane:left:diagonal"] == "on_kerb":
                    tagChanges["parking:left"] = "on_kerb"
                    tagChanges["parking:lane:left:diagonal"] = None
                elif tags["parking:lane:left:diagonal"] == "street_side":
                    tagChanges["parking:left"] = "street_side"
                    tagChanges["parking:lane:left:diagonal"] = None
                elif tags["parking:lane:left:diagonal"] == "painted_area_only":
                    tagChanges["parking:left"] = "on_street"
                    tagChanges["parking:left:markings"] = "yes"
                    tagChanges["parking:lane:left:diagonal"] = None
                elif tags["parking:lane:left:diagonal"] == "marked":
                    tagChanges["parking:left:markings"] = "yes"
                    tagChanges["parking:left"] = "yes" # Set the generic "yes" so that it's noted that you can obviously park there, but its unclear how
                    tagChanges["parking:lane:left:diagonal"] = None
        elif tags["parking:lane:left"] == "perpendicular":
            tagChanges["parking:left:orientation"] = "perpendicular"
            tagChanges["parking:lane:left"] = None
            if "parking:lane:left:perpendicular" in tags:
                if tags["parking:lane:left:perpendicular"] == "on_street":
                    tagChanges["parking:left"] = "on_street"
                    tagChanges["parking:lane:left:perpendicular"] = None
                elif tags["parking:lane:left:perpendicular"] == "half_on_kerb":
                    tagChanges["parking:left"] = "half_on_kerb"
                    tagChanges["parking:lane:left:perpendicular"] = None
                elif tags["parking:lane:left:perpendicular"] == "on_kerb":
                    tagChanges["parking:left"] = "on_kerb"
                    tagChanges["parking:lane:left:perpendicular"] = None
                elif tags["parking:lane:left:perpendicular"] == "street_side":
                    tagChanges["parking:left"] = "street_side"
                    tagChanges["parking:lane:left:perpendicular"] = None
                elif tags["parking:lane:left:perpendicular"] == "painted_area_only":
                    tagChanges["parking:left"] = "on_street"
                    tagChanges["parking:left:markings"] = "yes"
                    tagChanges["parking:lane:left:perpendicular"] = None
                elif tags["parking:lane:left:perpendicular"] == "marked":
                    tagChanges["parking:left:markings"] = "yes"
                    tagChanges["parking:left"] = "yes" # Set the generic "yes" so that it's noted that you can obviously park there, but its unclear how
                    tagChanges["parking:lane:left:perpendicular"] = None
        elif tags["parking:lane:left"] == "no":
            tagChanges["parking:left"] = "no"
            tagChanges["parking:lane:left"] = None
        elif tags["parking:lane:left"] == "no_parking":
            tagChanges["parking:left"] = "no"
            tagChanges["parking:left:restriction"] = "no_parking"
            tagChanges["parking:lane:left"] = None
        elif tags["parking:lane:left"] == "no_stopping":
            tagChanges["parking:left"] = "no"
            tagChanges["parking:left:restriction"] = "no_stopping"
            tagChanges["parking:lane:left"] = None
        elif tags["parking:lane:left"] == "no_standing":
            tagChanges["parking:left"] = "no"
            tagChanges["parking:left:restriction"] = "no_standing"
            tagChanges["parking:lane:left"] = None
        elif tags["parking:lane:left"] == "separate":
            tagChanges["parking:left"] = "separate"
            tagChanges["parking:lane:left"] = None
        elif tags["parking:lane:left"] == "marked":
            tagChanges["parking:left:markings"] = "yes"
            tagChanges["parking:left"] = "yes" # Set the generic "yes" so that it's noted that you can obviously park there, but its unclear how
            tagChanges["parking:lane:left"] = None
        elif tags["parking:lane:left"] == "marked" and "parking:lane:left:marked" in tags:
            if tags["parking:lane:left:marked"] == "on_street":
                tagChanges["parking:left"] = "on_street"
                tagChanges["parking:left:markings"] = "yes"
                tagChanges["parking:lane:left:marked"] = None
            elif tags["parking:lane:left:marked"] == "half_on_kerb":
                tagChanges["parking:left"] = "half_on_kerb"
                tagChanges["parking:left:markings"] = "yes"
                tagChanges["parking:lane:left:marked"] = None
            elif tags["parking:lane:left:marked"] == "on_kerb":
                tagChanges["parking:left"] = "on_kerb"
                tagChanges["parking:left:markings"] = "yes"
                tagChanges["parking:lane:left:marked"] = None
            elif tags["parking:lane:left:marked"] == "street_side":
                tagChanges["parking:left"] = "street_side"
                tagChanges["parking:left:markings"] = "yes"
                tagChanges["parking:lane:left:marked"] = None
    # Both sides
    if "parking:lane:both" in tags:
        if tags["parking:lane:both"] == "parallel":
            tagChanges["parking:both:orientation"] = "parallel"
            tagChanges["parking:lane:both"] = None
            if "parking:lane:both:parallel" in tags:
                if tags["parking:lane:both:parallel"] == "on_street":
                    tagChanges["parking:both"] = "on_street"
                    tagChanges["parking:lane:both:parallel"] = None
                elif tags["parking:lane:both:parallel"] == "half_on_kerb":
                    tagChanges["parking:both"] = "half_on_kerb"
                    tagChanges["parking:lane:both:parallel"] = None
                elif tags["parking:lane:both:parallel"] == "on_kerb":
                    tagChanges["parking:both"] = "on_kerb"
                    tagChanges["parking:lane:both:parallel"] = None
                elif tags["parking:lane:both:parallel"] == "street_side":
                    tagChanges["parking:both"] = "street_side"
                    tagChanges["parking:lane:both:parallel"] = None
                elif tags["parking:lane:both:parallel"] == "painted_area_only":
                    tagChanges["parking:both"] = "on_street"
                    tagChanges["parking:both:markings"] = "yes"
                    tagChanges["parking:lane:both:parallel"] = None
                elif tags["parking:lane:both:parallel"] == "marked":
                    tagChanges["parking:both:markings"] = "yes"
                    tagChanges["parking:lane:both:parallel"] = None
        elif tags["parking:lane:both"] == "diagonal":
            tagChanges["parking:both:orientation"] = "diagonal"
            tagChanges["parking:lane:both"] = None
            if "parking:lane:both:diagonal" in tags:
                if tags["parking:lane:both:diagonal"] == "on_street":
                    tagChanges["parking:both"] = "on_street"
                    tagChanges["parking:lane:both:diagonal"] = None
                elif tags["parking:lane:both:diagonal"] == "half_on_kerb":
                    tagChanges["parking:both"] = "half_on_kerb"
                    tagChanges["parking:lane:both:diagonal"] = None
                elif tags["parking:lane:both:diagonal"] == "on_kerb":
                    tagChanges["parking:both"] = "on_kerb"
                    tagChanges["parking:lane:both:diagonal"] = None
                elif tags["parking:lane:both:diagonal"] == "street_side":
                    tagChanges["parking:both"] = "street_side"
                    tagChanges["parking:lane:both:diagonal"] = None
                elif tags["parking:lane:both:diagonal"] == "painted_area_only":
                    tagChanges["parking:both"] = "on_street"
                    tagChanges["parking:both:markings"] = "yes"
                    tagChanges["parking:lane:both:diagonal"] = None
                elif tags["parking:lane:both:diagonal"] == "marked":
                    tagChanges["parking:both:markings"] = "yes"
                    tagChanges["parking:lane:both:diagonal"] = None
        elif tags["parking:lane:both"] == "perpendicular":
            tagChanges["parking:both:orientation"] = "perpendicular"
            tagChanges["parking:lane:both"] = None
            if "parking:lane:both:perpendicular" in tags:
                if tags["parking:lane:both:perpendicular"] == "on_street":
                    tagChanges["parking:both"] = "on_street"
                    tagChanges["parking:lane:both:perpendicular"] = None
                elif tags["parking:lane:both:perpendicular"] == "half_on_kerb":
                    tagChanges["parking:both"] = "half_on_kerb"
                    tagChanges["parking:lane:both:perpendicular"] = None
                elif tags["parking:lane:both:perpendicular"] == "on_kerb":
                    tagChanges["parking:both"] = "on_kerb"
                    tagChanges["parking:lane:both:perpendicular"] = None
                elif tags["parking:lane:both:perpendicular"] == "street_side":
                    tagChanges["parking:both"] = "street_side"
                    tagChanges["parking:lane:both:perpendicular"] = None
                elif tags["parking:lane:both:perpendicular"] == "painted_area_only":
                    tagChanges["parking:both"] = "on_street"
                    tagChanges["parking:both:markings"] = "yes"
                    tagChanges["parking:lane:both:perpendicular"] = None
                elif tags["parking:lane:both:perpendicular"] == "marked":
                    tagChanges["parking:both:markings"] = "yes"
                    tagChanges["parking:lane:both:perpendicular"] = None
        elif tags["parking:lane:both"] == "no":
            tagChanges["parking:both"] = "no"
            tagChanges["parking:lane:both"] = None
        elif tags["parking:lane:both"] == "no_parking":
            tagChanges["parking:both"] = "no"
            tagChanges["parking:both:restriction"] = "no_parking"
            tagChanges["parking:lane:both"] = None
        elif tags["parking:lane:both"] == "no_stopping":
            tagChanges["parking:both"] = "no"
            tagChanges["parking:both:restriction"] = "no_stopping"
            tagChanges["parking:lane:both"] = None
        elif tags["parking:lane:both"] == "no_standing":
            tagChanges["parking:both"] = "no"
            tagChanges["parking:both:restriction"] = "no_standing"
            tagChanges["parking:lane:both"] = None
        elif tags["parking:lane:both"] == "separate":
            tagChanges["parking:both"] = "separate"
            tagChanges["parking:lane:both"] = None
        elif tags["parking:lane:both"] == "marked":
            tagChanges["parking:both:markings"] = "yes"
            tagChanges["parking:lane:both"] = None
        elif tags["parking:lane:both"] == "marked" and "parking:lane:both:marked" in tags:
            if tags["parking:lane:both:marked"] == "on_street":
                tagChanges["parking:both"] = "on_street"
                tagChanges["parking:both:markings"] = "yes"
                tagChanges["parking:lane:both:marked"] = None
            elif tags["parking:lane:both:marked"] == "half_on_kerb":
                tagChanges["parking:both"] = "half_on_kerb"
                tagChanges["parking:both:markings"] = "yes"
                tagChanges["parking:lane:both:marked"] = None
            elif tags["parking:lane:both:marked"] == "on_kerb":
                tagChanges["parking:both"] = "on_kerb"
                tagChanges["parking:both:markings"] = "yes"
                tagChanges["parking:lane:both:marked"] = None
            elif tags["parking:lane:both:marked"] == "street_side":
                tagChanges["parking:both"] = "street_side"
                tagChanges["parking:both:markings"] = "yes"
                tagChanges["parking:lane:both:marked"] = None
    # Other things like conditions
    ## Generic yes in base tag needed
    for side in ["right", "left", "both"]:
        if any([True for key in tags if f"parking:{side}" in key]) and not "parking:"+side in tags:
            tagChanges["parking:"+side] = "yes"
    ## Free parking
    if "parking:condition:right" in tags and tags["parking:condition:right"] == "free":
        tagChanges["parking:right:fee"] = "no"
        tagChanges["parking:condition:right"] = None
    if "parking:condition:left" in tags and tags["parking:condition:left"] == "free":
        tagChanges["parking:left:fee"] = "no"
        tagChanges["parking:condition:left"] = None
    if "parking:condition:both" in tags and tags["parking:condition:both"] == "free":
        tagChanges["parking:both:fee"] = "no"
        tagChanges["parking:condition:both"] = None
    ## condition: no_parking
    if "parking:condition:right" in tags and tags["parking:condition:right"] == "no_parking":
        tagChanges["parking:right"] = "no"
        tagChanges["parking:right:restriction"] = "no_parking"
        tagChanges["parking:condition:right"] = None
    if "parking:condition:left" in tags and tags["parking:condition:left"] == "no_parking":
        tagChanges["parking:left"] = "no"
        tagChanges["parking:left:restriction"] = "no_parking"
        tagChanges["parking:condition:left"] = None
    if "parking:condition:both" in tags and tags["parking:condition:both"] == "no_parking":
        tagChanges["parking:both"] = "no"
        tagChanges["parking:both:restriction"] = "no_parking"
        tagChanges["parking:condition:both"] = None
    ## condition: no_stopping
    if "parking:condition:right" in tags and tags["parking:condition:right"] == "no_stopping":
        tagChanges["parking:right"] = "no"
        tagChanges["parking:right:restriction"] = "no_stopping"
        tagChanges["parking:condition:right"] = None
    if "parking:condition:left" in tags and tags["parking:condition:left"] == "no_stopping":
        tagChanges["parking:left"] = "no"
        tagChanges["parking:left:restriction"] = "no_stopping"
        tagChanges["parking:condition:left"] = None
    if "parking:condition:both" in tags and tags["parking:condition:both"] == "no_stopping":
        tagChanges["parking:both"] = "no"
        tagChanges["parking:both:restriction"] = "no_stopping"
        tagChanges["parking:condition:both"] = None
    return tagChanges


def are_all_old_parking_tags_gone(tags, tagChanges):
    # go through the tags. If a key in the tags dictionary has a value of None in the tagChanges dictionary, remove the key from the tags dictionary
    poppableDict = copy.deepcopy(tags)
    for key in tags:
        if key in tagChanges and tagChanges[key] == None:
            poppableDict.pop(key)
    tags = poppableDict
    # Now, go through all keys in tags and check if any of them contains "parking". if so, return False
    isOK = True
    offendingTags = {}
    for key in tags:
        if "parking" in key:
            isOK = False
            offendingTags[key] = tags[key]
    return offendingTags



op = mrcb.Overpass()

elements = op.getElementsFromQuery(
    """
[out:json][timeout:250];
way["parking:lane:right"];
way["parking:lane:both"];
way["parking:lane:left"];
out geom;
    """
)



challenge = mrcb.Challenge()

random.shuffle(elements)

for element in tqdm(elements):
    # Convert the geometry into a LineString
    # In the element, element["geometry"] is a dict of {"lat": float, "lon": float} for each node in the way
    # Convert this into a list of [lon, lat] pairs
    geom = [[node["lon"], node["lat"]] for node in element["geometry"]]
    # geom = mrcb.getElementCenterPoint(element)
    dd = convert_base_parking_tags(element["tags"])   

    # Only provide cooperative work if there are no old parking tags left
    offendingTags = are_all_old_parking_tags_gone(element["tags"], dd)
    if offendingTags == {}:
        cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                dd
            )
        instruction = MSG_COMPLETE
    else:
        cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                {"thistagwillneverbepresentandwillnotchangetags":None}
            )
        instruction = MSG_INCOMPLETE_1
        # Use dict comprehension to print "- ❌ KEY: VALUE" for all keys in offendingTags
        instruction += "\n".join([f"- ❌ {key}={offendingTags[key]}" for key in offendingTags])
        instruction += MSG_INCOMPLETE_2
    mainFeature = mrcb.GeoFeature.withId(
        element["type"],
        element["id"],
        geom,
        properties={"task_instruction":instruction}
    )
    t = mrcb.Task(
        mainFeature,
        additionalFeatures=[],
        cooperativeWork=cooperativeWork
    )


    challenge.addTask(t)

challenge.cap()

challenge.saveToFile("parking_converter.json")