import os, sys, json, base64
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET
import requests

def TagsAsMdTable(tags):
    # This function takes a dict of tags and returns a markdown table with the tags
    # The first column is the key and the second column is the value
    table = "| Key | Value |\n| --- | --- |\n"
    for key, value in tags.items():
        table += f"| {key} | {value} |\n"
    return table


@dataclass
class GeoFeature:
    # This is an abstraction of a GeoJSON Feature
    # A geo feature is a feature that has a geometry and properties
    # The geometry is a dict with a type and coordinates
    # The properties is a dict with key-value pairs
    def __init__(self, geometry, properties = {}):
        self.geometry = geometry
        self.properties = properties
        # infer the type of the geometry (Point, LineString, Polygon) from the coordinates
        # if its just a list of 2 numbers, its a Point
        # if its a list of lists of 2 numbers, its a LineString
        # if its a list of lists of 2 numbers where start and end are the same, its a Polygon
        if isinstance(geometry, list):
            if isinstance(geometry[0], list):
                if geometry[0][0] == geometry[-1][0] and geometry[0][1] == geometry[-1][1]:
                    self.geometryType = "Polygon"
                else:
                    self.geometryType = "LineString"
            else:
                self.geometryType = "Point"
        else:
            print(geometry)
            raise ValueError("Invalid coordinates")

    @classmethod
    def withId(cls, osmType, osmId, geometry, properties):
        print(osmType, osmId, geometry, properties)
        properties["@id"] = str(osmType) + "/" + str(osmId)
        return cls(geometry, properties)

    def to_dict(self):
        return {
            "type": "Feature",
            "geometry": {
                "type": self.geometryType,
                "coordinates": self.geometry
            },
            "properties": self.properties
        }

    def convertPolygonToClosedString(self):
        if self.geometryType == "Polygon":
            self.geometryType = "LineString"

@dataclass
class TagFix():
    def __init__(self, osmType, osmId, tags):
        # give tags to set and to delete in this format: {"name": "suggested name", "wrongtag": null}
        self.osmType = osmType
        self.osmId = osmId
        self.tagsToDelete = [key for key, value in tags.items() if value == None]
        self.tagsToSet = {key: value for key, value in tags.items() if value != None}
        if not isinstance(self.tagsToDelete, list):
            raise ValueError("tagsToDelete must be a list, e.g. ['tag1', 'tag2']")
        if not isinstance(self.tagsToSet, dict):
            raise ValueError("tagsToSet must be a dict e.g. {'tag1': 'value1', 'tag2': 'value2'}")
        
    def to_dict(self):
        return {"meta": 
            {"version": 2, "type": 1}, 
            "operations": [
                {"operationType": "modifyElement", 
                "data": {
                    "id": str(self.osmType) + "/" + str(self.osmId),  
                    "operations": [
                        {
                            "operation": "setTags", 
                            "data": self.tagsToSet
                        },
                        {
                            "operation": "unsetTags",
                            "data": self.tagsToDelete
                        }
                    ]
                }}]}

@dataclass
class OscChange():
    def __init__(self, osc_content):
        if not isinstance(osc_content, str):
            raise ValueError("osc_content must be a string containing the XML-based .osc change file")
        # Pre-encode once so repeated calls to to_dict() are stable
        self.encoded_content = base64.b64encode(osc_content.encode("utf-8")).decode("ascii")

    def to_dict(self):
        return {
            "meta": {"version": 2, "type": 2},
            "file": {
                "type": "xml",
                "format": "osc",
                "encoding": "base64",
                "content": self.encoded_content
            }
        }


class OscBuilder:
    """
    Helper to build .osc change files with convenience helpers for common operations.
    """

    def __init__(self, generator: str = "maproulette-tagfixes"):
        self.generator = generator
        self.create_elems: List[ET.Element] = []
        self.modify_elems: List[ET.Element] = []
        self.delete_elems: List[ET.Element] = []
        self._next_temp_id = -1

    def _new_temp_id(self) -> int:
        temp_id = self._next_temp_id
        self._next_temp_id -= 1
        return temp_id

    def _fetch_current_element(self, osm_type: str, osm_id: int) -> Dict:
        url = f"https://api.openstreetmap.org/api/0.6/{osm_type}/{osm_id}.json"
        response = requests.get(url)
        if response.status_code != 200:
            raise ValueError(f"Could not fetch {osm_type} {osm_id}: HTTP {response.status_code}")
        data = response.json()
        elements = data.get("elements", [])
        if not elements:
            raise ValueError(f"No data returned for {osm_type} {osm_id}")
        return elements[0]

    def _element_to_xml(self, element: Dict) -> ET.Element:
        el_type = element.get("type")
        if el_type not in ("node", "way", "relation"):
            raise ValueError(f"Unsupported element type: {el_type}")
        attrs = {"id": str(element["id"]), "version": str(element["version"])}
        if el_type == "node":
            attrs["lat"] = str(element["lat"])
            attrs["lon"] = str(element["lon"])
        xml_elem = ET.Element(el_type, attrs)
        if el_type == "way":
            for nd_ref in element.get("nodes", []):
                xml_elem.append(ET.Element("nd", {"ref": str(nd_ref)}))
        elif el_type == "relation":
            for member in element.get("members", []):
                member_attrs = {
                    "type": member["type"],
                    "ref": str(member["ref"]),
                    "role": member.get("role", "")
                }
                xml_elem.append(ET.Element("member", member_attrs))
        for k, v in element.get("tags", {}).items():
            xml_elem.append(ET.Element("tag", {"k": k, "v": v}))
        return xml_elem

    def createNode(self, lat: float, lon: float, tags: Optional[Dict[str, str]] = None) -> int:
        """
        Create a new node with a temporary negative ID. Returns the new node ID.
        """
        tags = tags or {}
        node_id = self._new_temp_id()
        node_elem = ET.Element("node", {"id": str(node_id), "lat": str(lat), "lon": str(lon), "version": "1"})
        for k, v in tags.items():
            node_elem.append(ET.Element("tag", {"k": k, "v": v}))
        self.create_elems.append(node_elem)
        return node_id

    def createWayFromNodeIds(self, node_ids: List[int], tags: Optional[Dict[str, str]] = None) -> int:
        """
        Create a new way using the provided node IDs. Returns the new way ID.
        """
        if not node_ids:
            raise ValueError("node_ids must contain at least one node")
        tags = tags or {}
        way_id = self._new_temp_id()
        way_elem = ET.Element("way", {"id": str(way_id), "version": "1"})
        for nid in node_ids:
            way_elem.append(ET.Element("nd", {"ref": str(nid)}))
        for k, v in tags.items():
            way_elem.append(ET.Element("tag", {"k": k, "v": v}))
        self.create_elems.append(way_elem)
        return way_id

    def createWay(self, coordinates: List[List[float]], tags: Optional[Dict[str, str]] = None):
        """
        Create a new way from a list of coordinates [[lon, lat], ...].
        Nodes are created automatically and linked in the new way.
        Returns (way_id, node_ids).
        """
        if not coordinates:
            raise ValueError("coordinates must contain at least one coordinate pair")
        node_ids = [self.createNode(lat=coord[1], lon=coord[0]) for coord in coordinates]
        way_id = self.createWayFromNodeIds(node_ids, tags)
        return way_id, node_ids

    def removeObject(self, osm_type: str, osm_id: int):
        """
        Delete an existing element (node/way/relation).
        """
        current = self._fetch_current_element(osm_type, osm_id)
        self.delete_elems.append(self._element_to_xml(current))
        return self

    def removeNodeFromWay(self, way_id: int, node_id: int):
        """
        Remove a node from a way by rewriting the way member list.
        """
        way = self._fetch_current_element("way", way_id)
        nodes = way.get("nodes", [])
        if node_id not in nodes:
            raise ValueError(f"Node {node_id} not found in way {way_id}")
        way["nodes"] = [n for n in nodes if n != node_id]
        self.modify_elems.append(self._element_to_xml(way))
        return self

    def addObjectToRelation(self, relation_id: int, object_type: str, object_id: int, position: Optional[int] = None, role: str = ""):
        """
        Insert a member into a relation at the given position (defaults to append).
        Supports negative positions to count from the end (-1 = after last, -2 = before last, etc.).
        """
        relation = self._fetch_current_element("relation", relation_id)
        members = list(relation.get("members", []))
        insertion = {"type": object_type, "ref": object_id, "role": role}
        if position is None:
            insert_index = len(members)
        elif position < 0:
            insert_index = len(members) + position + 1
            insert_index = max(0, insert_index)
        elif position >= len(members):
            insert_index = len(members)
        else:
            insert_index = position
        members.insert(insert_index, insertion)
        relation["members"] = members
        self.modify_elems.append(self._element_to_xml(relation))
        return self

    def removeObjectFromRelation(self, relation_id: int, object_type: str, object_id: int, role: Optional[str] = None):
        """
        Remove an existing member from a relation.
        """
        relation = self._fetch_current_element("relation", relation_id)
        members = relation.get("members", [])
        new_members = []
        removed = False
        for m in members:
            if m.get("type") == object_type and m.get("ref") == object_id and (role is None or m.get("role", "") == role):
                if removed:
                    new_members.append(m)
                else:
                    removed = True
            else:
                new_members.append(m)
        if not removed:
            raise ValueError(f"Member {object_type}/{object_id} not found in relation {relation_id}")
        relation["members"] = new_members
        self.modify_elems.append(self._element_to_xml(relation))
        return self

    def to_xml_element(self) -> ET.Element:
        osc = ET.Element("osmChange", {"version": "0.6", "generator": self.generator})
        if self.create_elems:
            create = ET.SubElement(osc, "create")
            for el in self.create_elems:
                create.append(el)
        if self.modify_elems:
            modify = ET.SubElement(osc, "modify")
            for el in self.modify_elems:
                modify.append(el)
        if self.delete_elems:
            delete = ET.SubElement(osc, "delete")
            for el in self.delete_elems:
                delete.append(el)
        return osc

    def to_string(self) -> str:
        osc = self.to_xml_element()
        return ET.tostring(osc, encoding="unicode")

    def to_osc_change(self) -> OscChange:
        return OscChange(self.to_string())

@dataclass
class Task:
    def __init__(self, mainFeature, additionalFeatures = [], cooperativeWork = None):
        self.mainFeature = mainFeature
        self.additionalFeatures = additionalFeatures
        self.cooperativeWork = cooperativeWork

    def to_dict(self):
        # the features are the main feature and the additional features as one list
        features = [self.mainFeature.to_dict()]
        for feature in self.additionalFeatures:
            features.append(feature.to_dict())
        if self.cooperativeWork == None:
            return {
                "type": "FeatureCollection",
                "features": features,
            }
        else:
            return {
                "type": "FeatureCollection",
                "features": features,
                "cooperativeWork": self.cooperativeWork.to_dict()
            }

@dataclass
class Challenge:
    def __init__(self):
        self.tasks = []

    def addTask(self, task):
        self.tasks.append(task)

    def saveToFile(self, filename):
        with open(filename, 'w', encoding="UTF-8") as f:
            for task in self.tasks:
                f.write('\x1E')
                json.dump(task.to_dict(), f, ensure_ascii=False)
                f.write('\n')
    
    def cap(self):
        # Makes sure that the number of tasks is no more than 50000 (drops everything beyond that)
        if len(self.tasks) > 50000:
            self.tasks = self.tasks[:49999]

class Overpass:
    def __init__(self):
        self.resultElements = {}
        self.overpass_url = "https://overpass-api.de/api/interpreter"

    def getElementsFromQuery(self, overpass_query):
        response = requests.get(self.overpass_url, params={'data': overpass_query})
        if response.status_code != 200:
            raise ValueError("Invalid return data")
        resultElements = response.json()["elements"]
        return resultElements


def createElementCenterPoint(element):
    # This function forces the element to have a lat and lon key
    # so that, regardless of the type of geometry of the element, the script can use lat/lon
    if 'lat' in element:
        element['lat'] = element['lat'] # That's a bit redundant, but it's here for clarity
        element['lon'] = element['lon']
    elif 'center' in element:
        element['lat'] = element['center']['lat']
        element['lon'] = element['center']['lon']
    elif 'bounds' in element:
        element['lat'] = (element['bounds']['minlat'] + element['bounds']['maxlat']) / 2
        element['lon'] = (element['bounds']['minlon'] + element['bounds']['maxlon']) / 2
    elif 'geometry' in element:
        if element['geometry']['type'] == 'Point':
            element['lat'] = element['geometry']['coordinates'][1]
            element['lon'] = element['geometry']['coordinates'][0]
        elif element['geometry']['type'] == 'LineString':
            # Create a center point as an average of all points
            lat = 0
            lon = 0
            for point in element['geometry']['coordinates']:
                lat += point[1]
                lon += point[0]
            element['lat'] = lat / len(element['geometry']['coordinates'])
            element['lon'] = lon / len(element['geometry']['coordinates'])
        elif element['geometry']['type'] == 'Polygon':
            # Create a center point as an average of all points
            lat = 0
            lon = 0
            for point in element['geometry']['coordinates']:
                lat += point[1]
                lon += point[0]
            element['lat'] = lat / len(element['geometry']['coordinates'])
            element['lon'] = lon / len(element['geometry']['coordinates'])
    else:
        print(element)
        raise ValueError("No handalable coordinates found for element")
    return element

def createGeometryFromElement(element):
    # "geometry" needs to check before "bounds", because when you output geom, bbox will also be given back
    # if there is "bounds" in element, construct a polygon with 4 points that represents the bbox
    if "lat" in element:
        # list of 2 floats for a dict that has lat lon as keys
        element["simpleGeometry"] = [element["lon"], element["lat"]]
    elif "geometry" in element:
        # list of lists of 2 floats for a dict that has lat lon as keys
        element["simpleGeometry"] = [[point["lon"], point["lat"]] for point in element["geometry"]]
    elif "bounds" in element:
        element["simpleGeometry"] = [
            [element["bounds"]["minlon"], element["bounds"]["minlat"]],
            [element["bounds"]["minlon"], element["bounds"]["maxlat"]],
            [element["bounds"]["maxlon"], element["bounds"]["maxlat"]],
            [element["bounds"]["maxlon"], element["bounds"]["minlat"]],
            [element["bounds"]["minlon"], element["bounds"]["minlat"]]
        ]	
    else:
        print(element)
        raise ValueError("No handalable geometry found for element")
    return element

def getElementCenterPoint(element):
    newElement = createElementCenterPoint(element)
    return [newElement["lon"], newElement["lat"]]

def getElementGeometry(element):
    newElement = createGeometryFromElement(element)
    return newElement["simpleGeometry"]


def _element_was_modified_by_user(osmType, osmId, username):
    """Return True if the given user appears in the history of the element."""
    url = f"https://api.openstreetmap.org/api/0.6/{osmType}/{osmId}/history.json"
    response = requests.get(url)
    if response.status_code != 200:
        return False
    try:
        versions = response.json().get("elements", [])
    except ValueError:
        return False
    for version in versions:
        if version.get("user") == username:
            return True
    return False


def filterElementsByUser(elements, username):
    """Filter a list of elements keeping only those edited by *username*.

    *elements* may contain Overpass-style dicts with ``type`` and ``id`` keys
    or ``(type, id)`` tuples. The original objects are returned for elements
    where the user has at least one version in the OSM history.
    """

    filtered = []
    for element in elements:
        if isinstance(element, tuple):
            osmType, osmId = element
        else:
            osmType = element.get("type")
            osmId = element.get("id")
        if not osmType or not osmId:
            continue
        if _element_was_modified_by_user(osmType, osmId, username):
            filtered.append(element)
    return filtered
