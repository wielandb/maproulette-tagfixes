import os, sys, json, base64
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET
import requests
import tempfile
from time import sleep
import math
import re
from urllib.parse import urlsplit
from datetime import datetime, timedelta, timezone

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
    def __init__(self, geometry, properties = None):
        self.geometry = geometry
        self.properties = dict(properties or {})
        # infer the type of the geometry (Point, LineString, Polygon) from the coordinates
        # if its just a list of 2 numbers, its a Point
        # if its a list of lists of 2 numbers, its a LineString
        # if its a list of lists of 2 numbers where start and end are the same, its a Polygon
        if isinstance(geometry, list) and geometry:
            if isinstance(geometry[0], list):
                if len(geometry) < 2 or any(len(point) != 2 for point in geometry):
                    raise ValueError("LineString must have at least two coordinate pairs")
                if len(geometry) >= 4 and geometry[0] == geometry[-1]:
                    self.geometryType = "Polygon"
                else:
                    self.geometryType = "LineString"
            else:
                if len(geometry) != 2:
                    raise ValueError("Point must contain a longitude and latitude")
                self.geometryType = "Point"
        else:
            raise ValueError("Invalid coordinates")

    @classmethod
    def withId(cls, osmType, osmId, geometry, properties):
        properties = dict(properties)
        properties["@id"] = str(osmType) + "/" + str(osmId)
        return cls(geometry, properties)

    def to_dict(self):
        return {
            "type": "Feature",
            "geometry": {
                "type": self.geometryType,
                "coordinates": [self.geometry] if self.geometryType == "Polygon" else self.geometry
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


class OSMElementNotFoundError(ValueError):
    """The editing API confirms that an element is missing or deleted."""


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
        response = requests.get(url, timeout=(10, 30))
        if response.status_code in (404, 410):
            raise OSMElementNotFoundError(f"Could not fetch {osm_type} {osm_id}: HTTP {response.status_code}")
        if response.status_code != 200:
            raise ValueError(f"Could not fetch {osm_type} {osm_id}: HTTP {response.status_code}")
        data = response.json()
        elements = data.get("elements") if isinstance(data, dict) else None
        if not isinstance(elements, list) or len(elements) != 1:
            raise ValueError(f"Invalid data returned for {osm_type} {osm_id}")
        element = elements[0]
        if (not isinstance(element, dict) or element.get("type") != osm_type
                or element.get("id") != osm_id
                or isinstance(element.get("version"), bool)
                or not isinstance(element.get("version"), int) or element["version"] < 1):
            raise ValueError(f"Invalid data returned for {osm_type} {osm_id}")
        # An omitted member/node list must never be interpreted as an empty
        # relation/way and overwrite all existing references in the OSC.
        if osm_type in ("relation", "way"):
            field = "members" if osm_type == "relation" else "nodes"
            if not isinstance(element.get(field), list):
                raise ValueError(f"Missing {field} for {osm_type} {osm_id}")
        return element

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
        # A failed serialization must not leave a truncated challenge behind.
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding="UTF-8", dir=os.path.dirname(os.path.abspath(filename)),
                delete=False,
            ) as f:
                temporary_name = f.name
                for task in self.tasks:
                    f.write('\x1E')
                    json.dump(task.to_dict(), f, ensure_ascii=False)
                    f.write('\n')
            os.replace(temporary_name, filename)
        finally:
            if temporary_name and os.path.exists(temporary_name):
                os.remove(temporary_name)
    
    def cap(self):
        # Makes sure that the number of tasks is no more than 50000 (drops everything beyond that)
        if len(self.tasks) > 50000:
            self.tasks = self.tasks[:50000]

class _OverpassResponseError(ValueError):
    def __init__(self, message, retryable=True, http_status=None):
        super().__init__(message)
        self.retryable = retryable
        self.http_status = http_status


class Overpass:
    # Global instances: https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances
    DEFAULT_URLS = (
        "https://overpass.openstreetmap.fr/api/interpreter",
        "https://overpass-api.de/api/interpreter",
        "https://overpass.private.coffee/api/interpreter",
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    )
    REQUEST_HEADERS = {
        "User-Agent": "maproulette-tagfixes/1.0 (+https://github.com/wielandb/maproulette-tagfixes)",
        "Accept": "application/json",
    }

    def __init__(self, max_attempts=6, retry_delay=5, request_timeout=300, overpass_urls=None):
        if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
            raise ValueError("max_attempts must be a positive integer")
        for name, value, minimum in (("retry_delay", retry_delay, 0), ("request_timeout", request_timeout, 0)):
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
                raise ValueError(f"{name} must be a finite nonnegative number")
        if request_timeout == 0:
            raise ValueError("request_timeout must be positive")
        if overpass_urls is None:
            configured_urls = os.environ.get("OVERPASS_URLS")
            overpass_urls = (
                [url.strip() for url in configured_urls.split(",") if url.strip()]
                if configured_urls is not None else self.DEFAULT_URLS
            )
        if isinstance(overpass_urls, str):
            raise ValueError("overpass_urls must be a list of HTTP(S) URLs")
        urls = []
        for url in overpass_urls:
            if not isinstance(url, str):
                raise ValueError("overpass_urls must contain HTTP(S) URLs")
            url = url.strip()
            parsed = urlsplit(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("overpass_urls must contain HTTP(S) URLs")
            if url not in urls:
                urls.append(url)
        if not urls:
            raise ValueError("overpass_urls must contain at least one server")
        self.resultElements = {}
        self.overpass_urls = tuple(urls)
        self.overpass_url = urls[0]
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.request_timeout = request_timeout
        self._area_resolvers = {}
        self._boundary_ways = {}

    @staticmethod
    def _clean_message(message, max_chars=500):
        # HTML error pages and carriage returns must not corrupt terminal output.
        message = " ".join(re.sub(r"<[^>]*>", " ", str(message)).split())
        return message if len(message) <= max_chars else message[:max_chars] + "...[truncated]"

    def _response_excerpt(self, response, max_chars=500):
        return self._clean_message(response.text or "", max_chars)

    def _response_elements(self, response):
        status = response.status_code
        if status != 200:
            retryable = status in (403, 404, 405, 406, 408, 413, 414, 429) or 500 <= status < 600
            raise _OverpassResponseError(f"HTTP {status}: {self._response_excerpt(response)}", retryable, http_status=status)
        try:
            payload = response.json()
        except ValueError as exc:
            raise _OverpassResponseError(f"Invalid Overpass JSON: {self._response_excerpt(response)}") from exc
        # Overpass can return HTTP 200 with an error and partial data.
        if isinstance(payload, dict) and payload.get("remark"):
            remark = self._clean_message(payload["remark"])
            retryable = not any(marker in remark.lower() for marker in ("parse error", "static error"))
            raise _OverpassResponseError(f"Overpass query failed: {remark}", retryable)
        if isinstance(payload, dict):
            metadata = payload.get("osm3s")
            timestamp = metadata.get("timestamp_osm_base") if isinstance(metadata, dict) else None
            if isinstance(timestamp, str):
                try:
                    osm_base = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    pass
                else:
                    if osm_base.tzinfo is not None and datetime.now(timezone.utc) - osm_base > timedelta(days=7):
                        raise _OverpassResponseError(f"Outdated Overpass data (OSM base {timestamp})")
        if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list) or any(
            not isinstance(element, dict) for element in payload["elements"]
        ):
            raise _OverpassResponseError(f"Invalid Overpass elements: {self._response_excerpt(response)}")
        return payload["elements"]

    def _fetch_boundary(self, url, relation_id):
        print(f"Loading country boundary relation/{relation_id} from {url}...", file=sys.stderr)
        response = requests.post(
            url, data={'data': f'[out:json][timeout:90];relation({relation_id});out geom;'},
            headers=self.REQUEST_HEADERS, timeout=(10, self.request_timeout),
        )
        elements = self._response_elements(response)
        relation = next((element for element in elements if element.get("type") == "relation" and element.get("id") == relation_id), None)
        if relation is None:
            raise _OverpassResponseError(f"Missing country boundary relation/{relation_id}")
        for member in relation.get("members", []):
            if member.get("type") != "way" or member.get("role", "") not in ("", "outer", "inner"):
                continue
            geometry = member.get("geometry") or []
            if not geometry or any(not isinstance(point, dict) or "lat" not in point or "lon" not in point for point in geometry):
                member["geometry"] = self._repair_boundary_way(member["ref"], geometry)
        return relation

    def _repair_boundary_way(self, way_id, original):
        # A missing node in a mirror must not silently alter the country border.
        if way_id not in self._boundary_ways:
            print(f"Repairing incomplete boundary way/{way_id} from the OSM API...", file=sys.stderr)
            response = requests.get(
                f"https://api.openstreetmap.org/api/0.6/way/{way_id}/full.json",
                headers=self.REQUEST_HEADERS, timeout=(10, self.request_timeout),
            )
            response.raise_for_status()
            try:
                elements = response.json()["elements"]
                way = next(element for element in elements if element.get("type") == "way" and element.get("id") == way_id)
                nodes = {element["id"]: element for element in elements if element.get("type") == "node"}
                geometry = [{"lat": nodes[ref]["lat"], "lon": nodes[ref]["lon"]} for ref in way["nodes"]]
            except (ValueError, KeyError, TypeError, StopIteration) as exc:
                raise _OverpassResponseError(f"Incomplete OSM boundary way/{way_id}") from exc
            if len(geometry) < 2:
                raise _OverpassResponseError(f"Incomplete OSM boundary way/{way_id}")
            self._boundary_ways[way_id] = geometry
        geometry = self._boundary_ways[way_id]
        if len(original) < 2 or not isinstance(original[0], dict) or not isinstance(original[-1], dict):
            raise _OverpassResponseError(f"Cannot verify endpoints of boundary way/{way_id}")
        endpoints = {(point.get("lat"), point.get("lon")) for point in (original[0], original[-1])}
        repaired_endpoints = {(point["lat"], point["lon"]) for point in (geometry[0], geometry[-1])}
        if endpoints != repaired_endpoints:
            raise _OverpassResponseError(f"Boundary way/{way_id} endpoints have changed; refusing an inexact border")
        return geometry

    def _fetch_area_candidates(self, url, query):
        print(f"Selecting candidates for an exact country filter on {url}...", file=sys.stderr)
        # Only the independent candidate selector is split. The original query's
        # recursion, set assignments and output still run together afterwards.
        masked = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/',
                        lambda match: ' ' * len(match[0]), query)
        number = r'(-?(?:\d+(?:\.\d*)?|\.\d+))'
        pattern = r'\(\s*' + r'\s*,\s*'.join([number] * 4) + r'\s*\)'
        matches = list(re.finditer(pattern, masked))
        if len(matches) != 1:
            raise _OverpassResponseError("Candidate selection needs exactly one bounding box")
        match = matches[0]
        bbox = tuple(float(value) for value in match.groups())
        south, west, north, east = bbox
        if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
            raise _OverpassResponseError("Candidate selection has an invalid bounding box")
        suffix = query[match.end():]
        # These queries are generated internally with one timeout setting.
        timeouts = list(re.finditer(r'\[timeout:\s*\d+\]', masked[:match.start()]))
        if len(timeouts) != 1:
            raise _OverpassResponseError("Candidate selection needs a query timeout")
        timeout_match = timeouts[0]
        prefix = query[:timeout_match.start()] + '[timeout:60]' + query[timeout_match.end():match.start()]
        pending = [(bbox, 0)]
        requests_made = 0
        selected = {}
        while pending:
            tile, depth = pending.pop()
            south, west, north, east = tile
            if max(north - south, east - west) > 2:
                if depth >= 8:
                    raise _OverpassResponseError("Candidate bounding box exceeds the tile depth limit")
                pending.extend((child, depth + 1) for child in reversed(self._split_candidate_bbox(tile)))
                continue
            if requests_made >= 128:
                raise _OverpassResponseError("Candidate selection exceeded 128 requests; refusing partial results")
            requests_made += 1
            tile_query = prefix + '(' + ','.join(f'{value:.7f}' for value in tile) + ')' + suffix
            response = None
            try:
                response = requests.post(
                    url, data={'data': tile_query}, headers=self.REQUEST_HEADERS,
                    timeout=(10, min(self.request_timeout, 90)),
                )
                batch = self._response_elements(response)
            except (requests.ReadTimeout, _OverpassResponseError) as exc:
                # A busy gateway, rate limit or broken CGI is not evidence that
                # the selector itself needs smaller spatial regions.
                query_exhausted = isinstance(exc, requests.ReadTimeout) or (
                    response is not None and response.status_code == 200
                    and re.search(r'runtime error:.*(?:query timed out|out of memory)', str(exc), re.I)
                )
                if not query_exhausted or depth >= 8 or max(north - south, east - west) <= 0.05:
                    raise
                print(f"Candidate tile exhausted its resources; splitting {tile}...", file=sys.stderr)
                pending.extend((child, depth + 1) for child in reversed(self._split_candidate_bbox(tile)))
                continue
            print(f"Candidate tile {requests_made}: {len(batch)} objects ({south:.3f},{west:.3f},{north:.3f},{east:.3f}).", file=sys.stderr)
            for element in batch:
                osm_type, osm_id = element.get('type'), element.get('id')
                if osm_type not in ('node', 'way', 'relation') or isinstance(osm_id, bool) or not isinstance(osm_id, int) or osm_id <= 0:
                    raise _OverpassResponseError("Candidate selection returned an invalid element identity")
                selected.setdefault((osm_type, osm_id), element)
        elements = list(selected.values())
        print(f"Received {len(elements)} spatial candidates from {url}.", file=sys.stderr)
        return elements

    @staticmethod
    def _split_candidate_bbox(bbox):
        south, west, north, east = bbox
        if north - south >= east - west:
            middle = (south + north) / 2
            return ((south, west, middle, east), (middle, west, north, east))
        middle = (west + east) / 2
        return ((south, west, north, middle), (south, middle, north, east))

    def _prepare_query(self, url, query):
        # OSM France serves current global data but does not build the area DB.
        # Resolve exact country selections to IDs instead of returning empty data.
        if urlsplit(url).hostname != "overpass.openstreetmap.fr":
            return query
        if __package__:
            from .overpass_areas import AreaFilterError, AreaFilterResolver
        else:
            from overpass_areas import AreaFilterError, AreaFilterResolver
        if url not in self._area_resolvers:
            self._area_resolvers[url] = AreaFilterResolver(
                lambda relation_id: self._fetch_boundary(url, relation_id),
                fetch_candidates=lambda query: self._fetch_area_candidates(url, query),
            )
        try:
            return self._area_resolvers[url].rewrite(query)
        except AreaFilterError as exc:
            raise _OverpassResponseError(f"Could not resolve area filter: {exc}") from exc

    def getElementsFromQuery(self, overpass_query):
        # Start with the last successful server, then rotate on each failed attempt.
        urls = (self.overpass_url,) + tuple(url for url in self.overpass_urls if url != self.overpass_url)
        errors = []
        for attempt in range(self.max_attempts):
            url = urls[attempt % len(urls)]
            status = None
            try:
                prepared_query = self._prepare_query(url, overpass_query)
                response = requests.post(
                    url, data={'data': prepared_query}, headers=self.REQUEST_HEADERS,
                    timeout=(10, self.request_timeout),
                )
                status = response.status_code
                elements = self._response_elements(response)
            except _OverpassResponseError as exc:
                status = exc.http_status
                if not exc.retryable:
                    raise ValueError(f"Overpass query failed on {url}: {exc}") from None
                error = str(exc)
            except requests.RequestException as exc:
                error = self._clean_message(f"{type(exc).__name__}: {exc}")
            else:
                self.overpass_url = url
                return elements
            errors.append(f"{url}: {error}")
            print(f"Overpass attempt {attempt + 1}/{self.max_attempts} failed on {url}: {error}", file=sys.stderr)
            if attempt + 1 < self.max_attempts:
                delay = min(self.retry_delay * 2 ** min(attempt, 10), 60)
                # The primary instance's usage policy requires >=30s after 406/429.
                if status in (406, 429):
                    delay = max(delay, 30)
                next_url = urls[(attempt + 1) % len(urls)]
                print(f"Retrying in {delay:g}s on {next_url}...", file=sys.stderr)
                sleep(delay)
        raise ValueError(f"Overpass request failed after {self.max_attempts} attempts: " + " | ".join(errors))


def _geometry_points(geometry):
    """Read coordinate pairs from Overpass geometry or a GeoJSON geometry."""
    if isinstance(geometry, list):
        try:
            points = [[point['lon'], point['lat']] for point in geometry]
        except (KeyError, TypeError) as exc:
            raise ValueError("Incomplete Overpass geometry") from exc
    elif isinstance(geometry, dict):
        geometry_type = geometry.get('type')
        coordinates = geometry.get('coordinates', [])
        if geometry_type == 'Point':
            points = [coordinates]
        elif geometry_type == 'LineString':
            points = coordinates
        elif geometry_type == 'Polygon':
            points = coordinates[0] if coordinates else []
        else:
            raise ValueError(f"Unsupported geometry type: {geometry_type}")
    else:
        raise ValueError("Invalid geometry")
    if not points or any(
        not isinstance(point, (list, tuple)) or len(point) != 2
        or any(not isinstance(value, (int, float)) for value in point)
        for point in points
    ):
        raise ValueError("No usable coordinates found for element")
    return points


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
        points = _geometry_points(element['geometry'])
        element['lat'] = sum(point[1] for point in points) / len(points)
        element['lon'] = sum(point[0] for point in points) / len(points)
    else:
        raise ValueError("No usable coordinates found for element")
    if not isinstance(element.get('lat'), (int, float)) or not isinstance(element.get('lon'), (int, float)):
        raise ValueError("No usable coordinates found for element")
    return element

def createGeometryFromElement(element):
    # "geometry" needs to check before "bounds", because when you output geom, bbox will also be given back
    # if there is "bounds" in element, construct a polygon with 4 points that represents the bbox
    if "lat" in element:
        # list of 2 floats for a dict that has lat lon as keys
        element["simpleGeometry"] = [element["lon"], element["lat"]]
    elif "geometry" in element:
        points = _geometry_points(element["geometry"])
        if isinstance(element["geometry"], dict) and element["geometry"].get("type") == "Point":
            element["simpleGeometry"] = points[0]
        else:
            element["simpleGeometry"] = points
    elif "bounds" in element:
        element["simpleGeometry"] = [
            [element["bounds"]["minlon"], element["bounds"]["minlat"]],
            [element["bounds"]["minlon"], element["bounds"]["maxlat"]],
            [element["bounds"]["maxlon"], element["bounds"]["maxlat"]],
            [element["bounds"]["maxlon"], element["bounds"]["minlat"]],
            [element["bounds"]["minlon"], element["bounds"]["minlat"]]
        ]	
    elif "center" in element:
        createElementCenterPoint(element)
        element["simpleGeometry"] = [element["lon"], element["lat"]]
    else:
        raise ValueError("No usable geometry found for element")
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
