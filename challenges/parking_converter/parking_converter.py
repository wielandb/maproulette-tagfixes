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
                    tagChanges["parking:right"] = "lane"
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
                    tagChanges["parking:right"] = "lane"
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
                    tagChanges["parking:right"] = "lane"
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
                    tagChanges["parking:right"] = "lane"
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
                    tagChanges["parking:right"] = "lane"
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
                    tagChanges["parking:right"] = "lane"
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
                tagChanges["parking:right"] = "lane"
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
                    tagChanges["parking:left"] = "lane"
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
                    tagChanges["parking:left"] = "lane"
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
                    tagChanges["parking:left"] = "lane"
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
                    tagChanges["parking:left"] = "lane"
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
                    tagChanges["parking:left"] = "lane"
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
                    tagChanges["parking:left"] = "lane"
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
                tagChanges["parking:left"] = "lane"
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
                    tagChanges["parking:both"] = "lane"
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
                    tagChanges["parking:both"] = "lane"
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
                    tagChanges["parking:both"] = "lane"
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
                    tagChanges["parking:both"] = "lane"
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
                    tagChanges["parking:both"] = "lane"
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
                    tagChanges["parking:both"] = "lane"
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
                tagChanges["parking:both"] = "lane"
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
    ## Ensure base parking tag when any sub-tag exists under parking:<side> in converted tags
    ## Said differently: if there is a tag parking:<side>:<something>, then there should also a tag set parking:<side> with value "yes" (but only if the tag does not exist already with a more specific value)
    for side in ["right", "left", "both"]:
        base = f"parking:{side}"
        is_basetag_set = tagChanges.get(base) is not None
        basetag_needs_to_be_set = False
        for key in tagChanges:
            if key.startswith(base + ":") and key != base:
                if not is_basetag_set:
                    basetag_needs_to_be_set = True # Don't change the dict during iteration
        
        if basetag_needs_to_be_set:
            tagChanges[base] = "yes"

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
    ## condition: disc
    if "parking:condition:right" in tags and tags["parking:condition:right"] == "disc":
        if "parking:condition:right:maxstay" in tags and "parking:condition:right:time_interval" in tags:
            maxstay = tags["parking:condition:right:maxstay"]
            interval = tags["parking:condition:right:time_interval"]
            tagChanges["parking:right:maxstay:conditional"] = f"{maxstay} @ {interval}"
            tagChanges["parking:right:authentication:disc:conditional"] = f"yes @ {interval}"
            tagChanges["parking:condition:right"] = None
            tagChanges["parking:condition:right:maxstay"] = None
            tagChanges["parking:condition:right:time_interval"] = None
    if "parking:condition:left" in tags and tags["parking:condition:left"] == "disc":
        if "parking:condition:left:maxstay" in tags and "parking:condition:left:time_interval" in tags:
            maxstay = tags["parking:condition:left:maxstay"]
            interval = tags["parking:condition:left:time_interval"]
            tagChanges["parking:left:maxstay:conditional"] = f"{maxstay} @ {interval}"
            tagChanges["parking:left:authentication:disc:conditional"] = f"yes @ {interval}"
            tagChanges["parking:condition:left"] = None
            tagChanges["parking:condition:left:maxstay"] = None
            tagChanges["parking:condition:left:time_interval"] = None
    if "parking:condition:both" in tags and tags["parking:condition:both"] == "disc":
        if "parking:condition:both:maxstay" in tags and "parking:condition:both:time_interval" in tags:
            maxstay = tags["parking:condition:both:maxstay"]
            interval = tags["parking:condition:both:time_interval"]
            tagChanges["parking:both:maxstay:conditional"] = f"{maxstay} @ {interval}"
            tagChanges["parking:both:authentication:disc:conditional"] = f"yes @ {interval}"
            tagChanges["parking:condition:both"] = None
            tagChanges["parking:condition:both:maxstay"] = None
            tagChanges["parking:condition:both:time_interval"] = None
    ## condition: ticket
    if "parking:condition:right" in tags and tags["parking:condition:right"] == "ticket":
        tagChanges["parking:right:fee"] = "yes"
        tagChanges["parking:right:authentication:ticket"] = "yes"
        tagChanges["parking:condition:right"] = None
    if "parking:condition:left" in tags and tags["parking:condition:left"] == "ticket":
        tagChanges["parking:left:fee"] = "yes"
        tagChanges["parking:left:authentication:ticket"] = "yes"
        tagChanges["parking:condition:left"] = None
    if "parking:condition:both" in tags and tags["parking:condition:both"] == "ticket":
        tagChanges["parking:both:fee"] = "yes"
        tagChanges["parking:both:authentication:ticket"] = "yes"
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
    # capacity: parking:lane:<side>:capacity OR parking:lane:<side>:capacity -> parking:<side>:capacity
    if "parking:lane:right:capacity" in tags:
        tagChanges["parking:right:capacity"] = tags["parking:lane:right:capacity"]
        tagChanges["parking:lane:right:capacity"] = None
    if "parking:lane:left:capacity" in tags:
        tagChanges["parking:left:capacity"] = tags["parking:lane:left:capacity"]
        tagChanges["parking:lane:left:capacity"] = None
    if "parking:lane:both:capacity" in tags:
        tagChanges["parking:both:capacity"] = tags["parking:lane:both:capacity"]
        tagChanges["parking:lane:both:capacity"] = None
    if "parking:condition:right:capacity" in tags:
        tagChanges["parking:right:capacity"] = tags["parking:condition:right:capacity"]
        tagChanges["parking:condition:right:capacity"] = None
    if "parking:condition:left:capacity" in tags:
        tagChanges["parking:left:capacity"] = tags["parking:condition:left:capacity"]
        tagChanges["parking:condition:left:capacity"] = None
    if "parking:condition:both:capacity" in tags:
        tagChanges["parking:both:capacity"] = tags["parking:condition:both:capacity"]
        tagChanges["parking:condition:both:capacity"] = None
    
    
    ## Combine left and right tags if they are the same
    if "parking:right" in tagChanges and "parking:left" in tagChanges and tagChanges["parking:right"] == tagChanges["parking:left"]:
        tagChanges["parking:both"] = tagChanges["parking:right"]
        tagChanges["parking:right"] = None
        tagChanges["parking:left"] = None
    if "parking:right:orientation" in tagChanges and "parking:left:orientation" in tagChanges and tagChanges["parking:right:orientation"] == tagChanges["parking:left:orientation"]:
        tagChanges["parking:both:orientation"] = tagChanges["parking:right:orientation"]
        tagChanges["parking:right:orientation"] = None
        tagChanges["parking:left:orientation"] = None
    if "parking:right:markings" in tagChanges and "parking:left:markings" in tagChanges and tagChanges["parking:right:markings"] == tagChanges["parking:left:markings"]:
        tagChanges["parking:both:markings"] = tagChanges["parking:right:markings"]
        tagChanges["parking:right:markings"] = None
        tagChanges["parking:left:markings"] = None
    if "parking:right:fee" in tagChanges and "parking:left:fee" in tagChanges and tagChanges["parking:right:fee"] == tagChanges["parking:left:fee"]:
        tagChanges["parking:both:fee"] = tagChanges["parking:right:fee"]
        tagChanges["parking:right:fee"] = None
        tagChanges["parking:left:fee"] = None
    if "parking:right:restriction" in tagChanges and "parking:left:restriction" in tagChanges and tagChanges["parking:right:restriction"] == tagChanges["parking:left:restriction"]:
        tagChanges["parking:both:restriction"] = tagChanges["parking:right:restriction"]
        tagChanges["parking:right:restriction"] = None
        tagChanges["parking:left:restriction"] = None
    if "parking:right:maxstay" in tagChanges and "parking:left:maxstay" in tagChanges and tagChanges["parking:right:maxstay"] == tagChanges["parking:left:maxstay"]:
        tagChanges["parking:both:maxstay"] = tagChanges["parking:right:maxstay"]
        tagChanges["parking:right:maxstay"] = None
        tagChanges["parking:left:maxstay"] = None
    if "parking:right:maxstay:conditional" in tagChanges and "parking:left:maxstay:conditional" in tagChanges and tagChanges["parking:right:maxstay:conditional"] == tagChanges["parking:left:maxstay:conditional"]:
        tagChanges["parking:both:maxstay:conditional"] = tagChanges["parking:right:maxstay:conditional"]
        tagChanges["parking:right:maxstay:conditional"] = None
        tagChanges["parking:left:maxstay:conditional"] = None
    if "parking:right:authentication:disc" in tagChanges and "parking:left:authentication:disc" in tagChanges and tagChanges["parking:right:authentication:disc"] == tagChanges["parking:left:authentication:disc"]:
        tagChanges["parking:both:authentication:disc"] = tagChanges["parking:right:authentication:disc"]
        tagChanges["parking:right:authentication:disc"] = None
        tagChanges["parking:left:authentication:disc"] = None
    if "parking:right:authentication:disc:conditional" in tagChanges and "parking:left:authentication:disc:conditional" in tagChanges and tagChanges["parking:right:authentication:disc:conditional"] == tagChanges["parking:left:authentication:disc:conditional"]:
        tagChanges["parking:both:authentication:disc:conditional"] = tagChanges["parking:right:authentication:disc:conditional"]
        tagChanges["parking:right:authentication:disc:conditional"] = None
        tagChanges["parking:left:authentication:disc:conditional"] = None
    if "parking:right:capacity" in tagChanges and "parking:left:capacity" in tagChanges and tagChanges["parking:right:capacity"] == tagChanges["parking:left:capacity"]:
        tagChanges["parking:both:capacity"] = tagChanges["parking:right:capacity"]
        tagChanges["parking:right:capacity"] = None
        tagChanges["parking:left:capacity"] = None
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