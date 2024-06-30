import os, sys, json
from dataclasses import dataclass, field
from typing import List, Dict
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
    
    def cap():
        # Makes sure that the number of tasks is no more than 50000 (drops everything beyond that)
        if len(self.tasks) > 50000:
            self.tasks = self.tasks[:50000]

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