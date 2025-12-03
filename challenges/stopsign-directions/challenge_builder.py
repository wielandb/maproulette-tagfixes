import os, sys, json
from dataclasses import dataclass, field
from typing import List, Dict
import requests
import geojson
from turfpy.measurement import distance, bbox, centroid



@dataclass
class GeoFeature:
    def __init__(self, geometry, properties={}):
        self.geometry = geometry
        self.properties = properties
        # fix or raise errors for common geometry problems
        if not isinstance(geometry, geojson.geometry.Geometry):
            raise ValueError("geometry must be an instance of the geoJSON Geometry class, got " + str(type(geometry)) + " instead")
        if geometry.type == "Point" and len(geometry.coordinates) != 2:
            geometry.coordinates = centroid(geometry).coordinates
        if geometry.type == "LineString" and len(geometry.coordinates) < 2:
            raise ValueError("LineString must have at least 2 points")
        if geometry.type == "Polygon" and len(geometry.coordinates) != 1:
            geometry.coordinates = [geometry.coordinates]
        if geometry.type == "Polygon" and len(geometry.coordinates[0]) < 4:
            raise ValueError("Polygon must have at least 4 points")

    @classmethod
    def withId(cls, osmType, osmId, geometry, properties):
        properties["@id"] = f"{osmType}/{osmId}"
        return cls(geometry, properties)

    def toGeoJSON(self):
        return geojson.Feature(geometry=self.geometry, properties=self.properties)

@dataclass
class TagFix():
    def __init__(self, osmType, osmId, tags):
        self.osmType = osmType
        self.osmId = osmId
        self.tagsToDelete = [key for key, value in tags.items() if value is None]
        self.tagsToSet = {key: value for key, value in tags.items() if value is not None}
        if not isinstance(self.tagsToDelete, list):
            raise ValueError("tagsToDelete must be a list, e.g. ['tag1', 'tag2']")
        if not isinstance(self.tagsToSet, dict):
            raise ValueError("tagsToSet must be a dict e.g. {'tag1': 'value1', 'tag2': 'value2'}")
        
    def toGeoJSON(self):
        return {"meta": {"version": 2, "type": 1}, 
                "operations": [
                    {"operationType": "modifyElement", 
                     "data": {
                         "id": f"{self.osmType}/{self.osmId}",  
                         "operations": [
                             {"operation": "setTags", "data": self.tagsToSet},
                             {"operation": "unsetTags", "data": self.tagsToDelete}
                         ]
                     }
                    }
                ]
                }

@dataclass
class Task:
    def __init__(self, mainFeature, additionalFeatures=[], cooperativeWork=None):
        self.mainFeature = mainFeature
        self.additionalFeatures = additionalFeatures
        self.cooperativeWork = cooperativeWork

    @classmethod
    def fromGeoJSON(cls, geojson_data):
        if not isinstance(geojson_data, dict) or geojson_data.get('type') != 'FeatureCollection':
            raise ValueError("Input must be a GeoJSON FeatureCollection")
        
        features = geojson_data.get('features', [])
        if not features:
            raise ValueError("FeatureCollection must contain at least one feature")
        
        # Convert geometry dict to proper geojson.Geometry object
        def convert_geometry(geom_dict):
            geom_type = geom_dict['type']
            if geom_type == 'Point':
                return geojson.Point(geom_dict['coordinates'])
            elif geom_type == 'LineString':
                return geojson.LineString(geom_dict['coordinates'])
            elif geom_type == 'Polygon':
                return geojson.Polygon(geom_dict['coordinates'])
            else:
                raise ValueError(f"Unsupported geometry type: {geom_type}")
        
        # First feature is the main feature
        main_feature = GeoFeature(
            convert_geometry(features[0]['geometry']), 
            features[0]['properties']
        )
        
        # Rest are additional features
        additional_features = [
            GeoFeature(convert_geometry(f['geometry']), f['properties']) 
            for f in features[1:]
        ]
        
        # Get cooperative work if it exists
        cooperative_work = None
        if 'cooperativeWork' in geojson_data:
            cooperative_work = TagFix(
                geojson_data['cooperativeWork']['operations'][0]['data']['id'].split('/')[0],
                int(geojson_data['cooperativeWork']['operations'][0]['data']['id'].split('/')[1]),
                geojson_data['cooperativeWork']['operations'][0]['data']['operations'][0]['data']
            )
        
        return cls(main_feature, additional_features, cooperative_work)

    def toGeoJSON(self):
        features = [self.mainFeature.toGeoJSON()] + [f.toGeoJSON() for f in self.additionalFeatures]
        return geojson.FeatureCollection(features, **({"cooperativeWork": self.cooperativeWork.toGeoJSON()} if self.cooperativeWork else {}))

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
                json.dump(task.toGeoJSON(), f, ensure_ascii=False)
                f.write('\n')

    @classmethod
    def loadFromFile(cls, filename):
        challenge = cls()
        try:
            with open(filename, 'r', encoding="UTF-8") as f:
                content = f.read()
                # Split by Record Separator character
                task_jsons = content.split('\x1E')
                # Filter out empty strings
                task_jsons = [tj for tj in task_jsons if tj.strip()]
                
                for task_json in task_jsons:
                    geojson_data = json.loads(task_json)
                    task = Task.fromGeoJSON(geojson_data)
                    challenge.addTask(task)
        except FileNotFoundError:
            print(f"File not found: {filename}")        
        return challenge

class Overpass:
    def __init__(self, overpass_url="https://overpass-api.de/api/interpreter"):
        self.overpass_url = overpass_url

    def _response_excerpt(self, response, max_chars=500):
        text = response.text or ""
        text = text.replace("\n", "\\n")
        if len(text) > max_chars:
            return text[:max_chars] + "...[truncated]"
        return text

    def queryElementsRaw(self, overpass_query):
        response = requests.get(self.overpass_url, params={'data': overpass_query})
        if response.status_code != 200:
            snippet = self._response_excerpt(response)
            raise ValueError(f"Invalid return data (HTTP {response.status_code}): {snippet}")
        try:
            return response.json()["elements"]
        except (ValueError, KeyError, TypeError):
            snippet = self._response_excerpt(response)
            raise ValueError(f"Invalid return data (HTTP {response.status_code}): {snippet}")

    def queryElementsAsGeoJSON(self, overpass_query, forceGeomType=None):
        rawElements = self.queryElementsRaw(overpass_query)
        featureList = list(map(lambda element: geojson.Feature(
            geometry=self.geoJSONGeometryFromOverpassElement(element, forceGeomType),
            properties=self.geoJSONPropertiesFromOverpassElement(element)
        ), rawElements))
        return featureList


    def geoJSONPropertiesFromOverpassElement(self, element):
        if 'tags' in element:
            tags = element['tags']
        else:
            tags = {}
        tags["@type"] = element["type"]
        tags["@id"] = element["id"]
        return tags;            

    def geoJSONGeometryFromOverpassElement(self, element, forceGeomType=None):
        # returns a geojson depending on element; either Point(), LineString() or Polygon()
        # frist, asses the geometry type we want to give back based on the element if ForceGeomType is None
        if forceGeomType is None:
            if 'lat' in element or 'center' in element:
                geomType = "Point"
            elif 'bounds' in element:
                geomType = "Polygon"
            elif 'geometry' in element:
                if element['geometry']['type'] in ["Point", "LineString", "Polygon"]:
                    geomType = element['geometry']['type']
                else:
                    raise ValueError("No handalable coordinates found for element")
            else:
                raise ValueError("No handalable coordinates found for element")
        else:
            geomType = forceGeomType
        # now, create the geojson object
        if geomType == "Point":
            if 'geometry' in element:
                return geojson.Point(element['geometry']['coordinates'])
            elif 'center' in element:
                return geojson.Point([element['center']['lon'], element['center']['lat']])
            else:
                return geojson.Point([element['lon'], element['lat']])
        elif geomType == "LineString":
            return geojson.LineString([[point['lon'], point['lat']] for point in element['geometry']])
        elif geomType == "Polygon":
            if 'bounds' in element:
                return geojson.Polygon([
                    [[element['bounds']['minlon'], element['bounds']['minlat']],
                    [element['bounds']['minlon'], element['bounds']['maxlat']],
                    [element['bounds']['maxlon'], element['bounds']['maxlat']],
                    [element['bounds']['maxlon'], element['bounds']['minlat']],
                    [element['bounds']['minlon'], element['bounds']['minlat']]]
                ])
            if 'coordinates' in element['geometry']:
                return geojson.Polygon([element['geometry']['coordinates']])
            else:
                return geojson.Polygon([[[point['lon'], point['lat']] for point in element['geometry']]])
        raise ValueError("No handalable coordinates found for element")
