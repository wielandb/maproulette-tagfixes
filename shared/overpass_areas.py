"""Use OSM boundary polygons on Overpass instances without generated areas.

Only explicit relation-derived area IDs and named declarations are supported.
The original selector stays on the server, so recursive queries and intermediate
sets keep their meaning. No bounding-box approximation or simplification is used.
"""

import math
import re
from collections import defaultdict
from urllib.parse import urlencode


class AreaFilterError(ValueError):
    """An area cannot be translated without changing its selection."""


_LITERALS = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*[\s\S]*?\*/')
_DECLARATION = re.compile(r'\barea\s*\(\s*(?:id\s*:\s*)?(\d+)\s*\)\s*->\s*\.([A-Za-z_]\w*)\s*;')
_FILTER = re.compile(r'\(\s*area\s*(?::\s*(\d+)|\.\s*([A-Za-z_]\w*))\s*\)')
_SELECTOR = re.compile(r'\b(?:node|way|relation|rel|nwr|nw|wr|nr)\b')


def _code_mask(query):
    return _LITERALS.sub(lambda match: ''.join('\n' if char == '\n' else ' ' for char in match[0]), query)


def _coordinate(point):
    if not isinstance(point, dict):
        raise AreaFilterError('Boundary geometry has a missing coordinate')
    values = (point.get('lat'), point.get('lon'))
    if any(isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) for value in values):
        raise AreaFilterError('Boundary geometry has an invalid coordinate')
    if not (-90 <= values[0] <= 90 and -180 <= values[1] <= 180):
        raise AreaFilterError('Boundary coordinate is out of range')
    return values


def _rings(members, role):
    """Join entire, possibly reversed member ways, checking their endpoints."""
    fragments = []
    endpoints = defaultdict(list)
    for member in members:
        member_role = member.get('role', '')
        if member_role not in (role, '' if role == 'outer' else role):
            continue
        if member.get('type') != 'way':
            raise AreaFilterError('Nested boundary relations are not supported by the polygon fallback')
        geometry = member.get('geometry')
        if not isinstance(geometry, list) or len(geometry) < 2:
            raise AreaFilterError(f"Boundary way {member.get('ref')} has missing geometry")
        points = [_coordinate(point) for point in geometry]
        nodes = member.get('nodes')
        if nodes is not None:
            if not isinstance(nodes, list) or len(nodes) != len(points):
                raise AreaFilterError('Boundary node references do not match geometry')
            first, last = ('node', nodes[0]), ('node', nodes[-1])
        else:
            # out geom supplies member coordinates but no member node IDs.
            first, last = ('coordinate', points[0]), ('coordinate', points[-1])
        index = len(fragments)
        fragments.append((first, last, points))
        endpoints[first].append(index)
        endpoints[last].append(index)

    if any(len(indices) % 2 for indices in endpoints.values()):
        raise AreaFilterError('Boundary ways do not form closed rings')
    unused = set(range(len(fragments)))
    rings = []
    while unused:
        index = min(unused)
        unused.remove(index)
        first, last, points = fragments[index]
        ring = list(points)
        while last != first:
            choices = [candidate for candidate in endpoints[last] if candidate in unused]
            if not choices:
                raise AreaFilterError('Boundary ways do not form closed rings')
            # Rings can touch at one OSM node (the Austrian border does).
            # Any closed traversal of an even-degree boundary graph preserves
            # its even/odd polygon interior without adding connecting edges.
            index = min(choices)
            unused.remove(index)
            start, end, points = fragments[index]
            if start == last:
                extension, last = points, end
            else:
                extension, last = points[::-1], start
            if ring[-1] != extension[0]:
                raise AreaFilterError('Boundary ways disagree on their shared node coordinates')
            ring.extend(extension[1:])
        if len(ring) < 4 or ring[0] != ring[-1] or len(set(ring)) < 3:
            raise AreaFilterError('Boundary ring is degenerate or not closed')
        rings.append(ring)
    return rings


def _boundary_rings(relation):
    if not isinstance(relation, dict) or relation.get('type') != 'relation' or not isinstance(relation.get('members'), list):
        raise AreaFilterError('Boundary relation is missing from the Overpass response')
    members = []
    for member in relation['members']:
        if not isinstance(member, dict):
            raise AreaFilterError('Boundary relation contains an invalid member')
        role = member.get('role', '')
        if role in ('outer', 'inner') or (role == '' and member.get('type') in ('way', 'relation')):
            members.append(member)
        elif member.get('type') == 'way':
            raise AreaFilterError(f'Unsupported boundary way role: {role}')
    outers, inners = _rings(members, 'outer'), _rings(members, 'inner')
    if not outers:
        raise AreaFilterError('Boundary relation has no outer rings')
    return outers, inners


class AreaFilterResolver:
    def __init__(self, fetch_relation, fetch_candidates):
        self.fetch_relation = fetch_relation
        self.fetch_candidates = fetch_candidates
        self.shapes = {}
        self.selections = {}

    def _get_relation(self, area_id):
        if area_id <= 3600000000:
            raise AreaFilterError(f'Only relation-derived areas are supported: {area_id}')
        relation_id = area_id - 3600000000
        relation = self.fetch_relation(relation_id)
        if not isinstance(relation, dict) or relation.get('id') != relation_id:
            raise AreaFilterError(f'Boundary relation {relation_id} is missing')
        return relation

    def _get_shape(self, area_id):
        if area_id not in self.shapes:
            try:
                from shapely import make_valid
                from shapely.geometry import Polygon
                from shapely.prepared import prep
            except ImportError as exc:
                raise AreaFilterError('Shapely >= 2 is required for exact Overpass area fallback') from exc
            outers, inners = _boundary_rings(self._get_relation(area_id))
            outer_polygons, inner_polygons = [], []
            # Even/odd composition keeps holes, touching rings and islands in
            # holes. make_valid splits rings touching themselves at a vertex;
            # it does not simplify or replace the original boundary.
            for rings, polygons in ((outers, outer_polygons), (inners, inner_polygons)):
                for ring in rings:
                    polygon = make_valid(Polygon([(lon, lat) for lat, lon in ring]))
                    if polygon.geom_type not in ('Polygon', 'MultiPolygon') or polygon.is_empty:
                        raise AreaFilterError('Boundary ring is not a valid polygon')
                    polygons.append(polygon)
            for hole in inner_polygons:
                # XOR would turn a detached inner ring into an extra island.
                # Full polygon containment also rejects a hole crossing the
                # outer border, while allowing Jungholz's single shared node.
                if not any(outer.covers(hole) for outer in outer_polygons):
                    raise AreaFilterError('Boundary hole is not enclosed by an outer ring')
            shape = None
            for polygon in outer_polygons + inner_polygons:
                shape = polygon if shape is None else shape.symmetric_difference(polygon)
            if shape.is_empty or not shape.is_valid or shape.geom_type not in ('Polygon', 'MultiPolygon'):
                raise AreaFilterError('Boundary does not form a valid country polygon')
            self.shapes[area_id] = (shape, prep(shape))
        return self.shapes[area_id]

    @staticmethod
    def _independent_selector(statement):
        mask = _code_mask(statement)
        head = re.match(r'(node|way|relation|rel|nwr|nw|wr|nr)\b', mask)
        if not head:
            raise AreaFilterError('Unsupported area selector type')
        index = head.end()
        while index < len(mask):
            if mask[index].isspace():
                index += 1
                continue
            opening = mask[index]
            if opening not in '[(':
                raise AreaFilterError('Area fallback requires an independent selector without input sets')
            closing = ']' if opening == '[' else ')'
            start, depth = index, 1
            index += 1
            while index < len(mask) and depth:
                if mask[index] == opening:
                    depth += 1
                elif mask[index] == closing:
                    depth -= 1
                index += 1
            if depth:
                raise AreaFilterError('Unclosed filter in area selector')
            if opening == '(':
                content = mask[start + 1:index - 1].strip()
                if not content.startswith('if:') or re.search(r'\.\s*[A-Za-z_]', content):
                    raise AreaFilterError('Area fallback cannot prefetch a selector depending on other query sets')
        return head[1], statement[head.end():]

    @staticmethod
    def _matches(element, shape, prepared, relation_member=False):
        from shapely.geometry import LineString, Point

        element_type = element.get('type')
        if element_type == 'node':
            lat, lon = _coordinate(element)
            point = Point(lon, lat)
            return prepared.contains(point) if relation_member else prepared.covers(point)
        if element_type == 'way':
            geometry = element.get('geometry')
            if not isinstance(geometry, list) or not geometry:
                raise AreaFilterError(f"Candidate way {element.get('id', element.get('ref'))} has missing geometry")
            points = [_coordinate(point) for point in geometry]
            if len(set(points)) == 1:
                return prepared.contains(Point(points[0][1], points[0][0]))
            line = LineString([(lon, lat) for lat, lon in points])
            # A way must meet the polygon interior, including along a segment.
            # Touching only the country border does not qualify.
            return prepared.contains_properly(line) or (prepared.intersects(line) and shape.relate_pattern(line, 'T********'))
        if element_type == 'relation' and not relation_member:
            members = element.get('members')
            if not isinstance(members, list):
                raise AreaFilterError(f"Candidate relation {element.get('id')} has missing members")
            found = False
            for item in members:
                if not isinstance(item, dict):
                    raise AreaFilterError('Candidate relation has an invalid member')
                if item.get('type') in ('node', 'way'):
                    # Validate every direct member even after a match, so a
                    # truncated response cannot silently hide corrupt geometry.
                    found = AreaFilterResolver._matches(item, shape, prepared, relation_member=True) or found
                elif item.get('type') != 'relation':
                    raise AreaFilterError('Candidate relation has an invalid member type')
            # Native Overpass area filters inspect direct node/way members;
            # they do not recursively expand relation members here.
            return found
        raise AreaFilterError(f'Unsupported candidate type: {element_type}')

    def _hydrate(self, area_id, statement, relative_start, relative_end):
        without_area = statement[:relative_start] + statement[relative_end:]
        osm_type, filters = self._independent_selector(without_area)
        cache_key = (area_id, without_area)
        if cache_key not in self.selections:
            shape, prepared = self._get_shape(area_id)
            west, south, east, north = shape.bounds
            bbox = f'({south:.7f},{west:.7f},{north:.7f},{east:.7f})'
            query = '[out:json][timeout:250];' + statement[:relative_start] + bbox + statement[relative_end:] + ';out skel geom;'
            candidates = self.fetch_candidates(query)
            if not isinstance(candidates, list):
                raise AreaFilterError('Overpass candidate response is not an element list')
            allowed = {'node': {'node'}, 'way': {'way'}, 'rel': {'relation'}, 'relation': {'relation'},
                       'nw': {'node', 'way'}, 'nr': {'node', 'relation'}, 'wr': {'way', 'relation'},
                       'nwr': {'node', 'way', 'relation'}}[osm_type]
            ids = defaultdict(set)
            for element in candidates:
                if not isinstance(element, dict) or element.get('type') not in allowed:
                    raise AreaFilterError('Overpass returned an unexpected candidate element type')
                osm_id = element.get('id')
                if isinstance(osm_id, bool) or not isinstance(osm_id, int) or osm_id <= 0:
                    raise AreaFilterError('Overpass candidate has an invalid OSM ID')
                if self._matches(element, shape, prepared):
                    ids[element['type']].add(osm_id)
            self.selections[cache_key] = ids
        ids = self.selections[cache_key]
        selectors = [kind + '(id:' + ','.join(str(osm_id) for osm_id in sorted(ids[kind])) + ')' + filters + ';'
                     for kind in ('node', 'way', 'relation') if ids[kind]]
        return '(\n' + '\n'.join(selectors or ['node(id:0);']) + '\n)'

    def rewrite(self, query):
        mask = _code_mask(query)
        if not re.search(r'\b(?:area|map_to_area|is_in)\b', mask):
            return query
        declarations, replacements = {}, []
        remaining = list(mask)
        for match in _DECLARATION.finditer(mask):
            name = match[2]
            if name in declarations:
                raise AreaFilterError(f'Area variable .{name} is assigned more than once')
            declarations[name] = int(match[1])
            replacements.append((match.start(), match.end(), ''))
            remaining[match.start():match.end()] = ' ' * (match.end() - match.start())
        filters = list(_FILTER.finditer(mask))
        statements = set()
        for match in filters:
            remaining[match.start():match.end()] = ' ' * (match.end() - match.start())
            if match[1]:
                area_id = int(match[1])
            elif match[2] in declarations:
                area_id = declarations[match[2]]
            else:
                raise AreaFilterError(f'Unknown area variable .{match[2]}')
            lower = mask.rfind(';', 0, match.start()) + 1
            selector_matches = list(_SELECTOR.finditer(mask, lower, match.start()))
            if not selector_matches:
                raise AreaFilterError('Area filter is not attached to a supported element selector')
            start = selector_matches[-1].start()
            end = mask.find(';', match.end())
            if end < 0 or start in statements:
                raise AreaFilterError('Unsupported area selector statement')
            statements.add(start)
            statement = query[start:end]
            statement_mask = mask[start:end]
            assignment = re.search(r'\s*->\s*\.[A-Za-z_]\w*\s*$', statement_mask)
            target = statement[assignment.start():] if assignment else ''
            if assignment:
                statement = statement[:assignment.start()]
            relative_start, relative_end = match.start() - start, match.end() - start
            hydrated = self._hydrate(area_id, statement, relative_start, relative_end)
            replacements.append((start, end + 1, hydrated + target + ';'))
        if re.search(r'\b(?:area|map_to_area|is_in)\b', ''.join(remaining)):
            raise AreaFilterError('Unsupported area syntax on an Overpass server without generated areas')
        for start, end, replacement in sorted(replacements, reverse=True):
            query = query[:start] + replacement + query[end:]
        if len(urlencode({'data': query}).encode('ascii')) > 900000:
            raise AreaFilterError('Area fallback produced more than 900 KB of selected IDs; refusing to truncate the query')
        return query
