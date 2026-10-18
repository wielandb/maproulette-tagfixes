import unittest
from unittest.mock import Mock

from shapely.geometry import Point

from shared.overpass_areas import AreaFilterError, AreaFilterResolver


def member(ref, points, role='outer', nodes=None):
    result = {'type': 'way', 'ref': ref, 'role': role,
              'geometry': [{'lat': lat, 'lon': lon} for lat, lon in points]}
    if nodes is not None:
        result['nodes'] = nodes
    return result


def boundary(*members):
    return {'type': 'relation', 'id': 51477, 'members': list(members)}


SQUARE = [(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)]


class OverpassAreaTests(unittest.TestCase):
    def resolver(self, relation=None):
        fetch = Mock(return_value=relation or boundary(member(1, SQUARE)))
        select = Mock(return_value=[{'type': 'node', 'id': 1, 'lat': 5, 'lon': 5}])
        return AreaFilterResolver(fetch, select), fetch

    def test_inline_and_named_filters_use_same_cached_boundary(self):
        resolver, fetch = self.resolver()
        result = resolver.rewrite('[out:json];area(id:3600051477)->.searchArea;'
                                  'nwr["amenity"="nursing_home"](area.searchArea);out geom;')
        self.assertNotIn('area(id:', result)
        self.assertNotIn('(area.searchArea)', result)
        self.assertIn('node(id:1)["amenity"="nursing_home"]', result)
        self.assertTrue(result.endswith(';out geom;'))
        resolver.rewrite('node(area:3600051477);out;')
        fetch.assert_called_once_with(51477)

    def test_query_without_area_or_with_area_in_strings_and_comments_is_unchanged(self):
        resolver, fetch = self.resolver()
        query = '[out:json];node["note"~"area:3600051477"];/* area(12); */out; // (area:42)'
        self.assertEqual(resolver.rewrite(query), query)
        fetch.assert_not_called()

    def test_reversed_member_ways_join_by_node_references(self):
        resolver, _ = self.resolver(boundary(
            member(10, [(0, 0), (0, 10), (10, 10)], nodes=[1, 2, 3]),
            member(11, [(0, 0), (10, 0), (10, 10)], nodes=[1, 4, 3]),
        ))
        resolver.rewrite('node(area:3600051477);out;')
        shape = resolver.shapes[3600051477][0]
        self.assertEqual(shape.geom_type, 'Polygon')
        self.assertEqual(set(shape.exterior.coords), {(lon, lat) for lat, lon in SQUARE})

    def test_disconnected_outers_use_union_preserving_intermediate_set_and_recursion(self):
        island = [(20, 20), (20, 21), (21, 21), (21, 20), (20, 20)]
        resolver, _ = self.resolver(boundary(member(1, SQUARE), member(2, island)))
        result = resolver.rewrite('area(id:3600051477)->.searchArea;'
                                  'nwr["railway"="station"](area.searchArea)->.stations;'
                                  'way(bn.stations);(._;>;);out body;')
        self.assertIn('node(id:1)["railway"="station"]', result)
        self.assertEqual(result.count('->.stations'), 1)
        self.assertIn('\n)->.stations;way(bn.stations);(._;>;);out body;', result)
        shape = resolver.shapes[3600051477][0]
        self.assertEqual(shape.geom_type, 'MultiPolygon')
        self.assertTrue(shape.covers(Point(5, 5)))
        self.assertTrue(shape.covers(Point(20.5, 20.5)))
        self.assertFalse(shape.covers(Point(15, 15)))

    def test_hole_is_excluded_and_island_inside_hole_is_included(self):
        hole = [(3, 3), (3, 7), (7, 7), (7, 3), (3, 3)]
        island = [(4, 4), (4, 5), (5, 5), (5, 4), (4, 4)]
        resolver, _ = self.resolver(boundary(member(1, SQUARE), member(2, hole, 'inner'), member(3, island)))
        resolver.rewrite('nwr["test"](area:3600051477);out geom;')
        shape = resolver.shapes[3600051477][0]
        self.assertTrue(shape.covers(Point(1, 1)))
        self.assertFalse(shape.covers(Point(6, 6)))
        self.assertTrue(shape.covers(Point(4.5, 4.5)))

    def test_touching_rings_do_not_need_artificial_connectors(self):
        resolver, _ = self.resolver(boundary(
            member(1, [(0, 0), (0, 1), (1, 1)]),
            member(2, [(1, 1), (1, 0), (0, 0)]),
            member(3, [(1, 1), (1, 2), (2, 2)]),
            member(4, [(2, 2), (2, 1), (1, 1)]),
        ))
        resolver.rewrite('node(area:3600051477);out;')
        shape = resolver.shapes[3600051477][0]
        self.assertTrue(shape.covers(Point(0.5, 0.5)))
        self.assertTrue(shape.covers(Point(1.5, 1.5)))
        self.assertFalse(shape.covers(Point(1.5, 0.5)))

    def test_touching_hole_keeps_jungholz_outside(self):
        hole = [(0, 0), (2, 1), (1, 2), (0, 0)]
        resolver, _ = self.resolver(boundary(member(1, SQUARE), member(2, hole, 'inner')))
        resolver.rewrite('node(area:3600051477);out;')
        shape = resolver.shapes[3600051477][0]
        self.assertFalse(shape.covers(Point(1, 1)))
        self.assertTrue(shape.covers(Point(5, 5)))

    def test_labels_and_subareas_are_not_boundary_rings(self):
        resolver, _ = self.resolver(boundary(member(1, SQUARE),
                                            {'type': 'node', 'ref': 2, 'role': 'admin_centre'},
                                            {'type': 'relation', 'ref': 3, 'role': 'subarea'}))
        resolver.rewrite('node(area:3600051477);out;')
        self.assertEqual(resolver.shapes[3600051477][0].area, 100)

    def test_incomplete_geometry_never_becomes_an_empty_or_approximate_area(self):
        invalid_members = [
            {'type': 'way', 'ref': 1, 'role': 'outer'},
            {'type': 'way', 'ref': 1, 'role': 'outer', 'geometry': [None, {'lat': 0, 'lon': 0}]},
            member(1, [(0, 0), (0, 1), (1, 1)]),
            member(1, [(0, 0), (0, 0), (0, 0), (0, 0)]),
            {'type': 'relation', 'ref': 1, 'role': 'outer'},
            member(1, [(0, 0), (0, float('nan')), (1, 1), (0, 0)]),
        ]
        for invalid in invalid_members:
            with self.subTest(invalid=invalid):
                resolver, _ = self.resolver(boundary(invalid))
                with self.assertRaises(AreaFilterError):
                    resolver.rewrite('node(area:3600051477);out;')
                self.assertEqual(resolver.shapes, {})

    def test_different_node_references_at_same_position_do_not_join(self):
        resolver, _ = self.resolver(boundary(
            member(1, [(0, 0), (0, 10), (10, 10)], nodes=[1, 2, 3]),
            member(2, [(10, 10), (10, 0), (0, 0)], nodes=[30, 4, 1]),
        ))
        with self.assertRaises(AreaFilterError):
            resolver.rewrite('node(area:3600051477);out;')

    def test_wrong_missing_relation_and_uncontained_hole_fail(self):
        for relation in ({'type': 'relation', 'id': 123, 'members': []},
                         boundary(),
                         boundary(member(1, SQUARE), member(2, [(20, 20), (20, 21), (21, 20), (20, 20)], 'inner'))):
            with self.subTest(relation=relation):
                resolver, _ = self.resolver(relation)
                with self.assertRaises(AreaFilterError):
                    resolver.rewrite('node(area:3600051477);out;')

    def test_detached_or_partially_outside_hole_is_rejected_before_selecting_candidates(self):
        for points in ([(20, 20), (20, 21), (21, 20), (20, 20)],
                       [(9, 9), (9, 11), (11, 11), (11, 9), (9, 9)]):
            with self.subTest(points=points):
                resolver, _ = self.resolver(boundary(member(1, SQUARE), member(2, points, 'inner')))
                with self.assertRaisesRegex(AreaFilterError, 'hole is not enclosed'):
                    resolver.rewrite('node(area:3600051477);out;')
                resolver.fetch_candidates.assert_not_called()
                self.assertEqual(resolver.shapes, {})

    def test_unsupported_area_syntax_fails_explicitly(self):
        for query in ('area["name"="Germany"];node(area);out;',
                      'node(area.unknown);out;',
                      'node(area:123);out;',
                      'rel(51477);map_to_area;node(area);out;',
                      'is_in(50,8);out;',
                      'node(area:3600051477)(area:3600051477);out;'):
            with self.subTest(query=query):
                resolver, _ = self.resolver()
                with self.assertRaises(AreaFilterError):
                    resolver.rewrite(query)


class OverpassAreaHydrationTests(unittest.TestCase):
    def resolver(self, candidates, relation=None):
        fetch = Mock(return_value=relation or boundary(member(1, SQUARE)))
        select = Mock(return_value=candidates)
        return AreaFilterResolver(fetch, select), fetch, select

    def test_bbox_fetch_filters_nodes_against_real_boundary_and_keeps_border(self):
        triangle = [(0, 0), (0, 10), (10, 0), (0, 0)]
        candidates = [{'type': 'node', 'id': 1, 'lat': 1, 'lon': 1},
                      {'type': 'node', 'id': 2, 'lat': 8, 'lon': 8},
                      {'type': 'node', 'id': 3, 'lat': 0, 'lon': 5}]
        resolver, fetch, select = self.resolver(candidates, boundary(member(1, triangle)))
        result = resolver.rewrite('[out:json];node["highway"="stop"](area:3600051477);way(bn);(._;>;);out body;')
        self.assertIn('node(id:1,3)["highway"="stop"]', result)
        self.assertNotIn('id:2', result)
        self.assertTrue(result.endswith(';way(bn);(._;>;);out body;'))
        select.assert_called_once_with('[out:json][timeout:250];node["highway"="stop"](0.0000000,0.0000000,10.0000000,10.0000000);out skel geom;')
        fetch.assert_called_once_with(51477)

    def test_way_crossing_country_with_no_nodes_inside_is_included(self):
        candidates = [dict(member(1, [(-1, 5), (11, 5)]), id=1, type='way'),
                      dict(member(2, [(-1, 5), (0, 5)]), id=2, type='way'),
                      dict(member(3, [(0, 0), (0, 10)]), id=3, type='way'),
                      dict(member(4, [(3, 3), (4, 4)]), id=4, type='way')]
        resolver, _, _ = self.resolver(candidates)
        result = resolver.rewrite('way["test"](area:3600051477);out geom;')
        self.assertIn('way(id:1,4)["test"]', result)

    def test_relation_checks_direct_members_interior_and_ignores_nested_relations(self):
        candidates = [{'type': 'relation', 'id': 1, 'members': [{'type': 'node', 'ref': 9, 'lat': 5, 'lon': 5}]},
                      {'type': 'relation', 'id': 2, 'members': [{'type': 'node', 'ref': 9, 'lat': 0, 'lon': 5}]},
                      {'type': 'relation', 'id': 3, 'members': [member(3, [(-1, 5), (11, 5)])]},
                      {'type': 'relation', 'id': 4, 'members': [{'type': 'relation', 'ref': 1}]}]
        resolver, _, _ = self.resolver(candidates)
        result = resolver.rewrite('rel["test"](area:3600051477);out geom;')
        self.assertIn('relation(id:1,3)["test"]', result)

    def test_intermediate_station_set_is_hydrated_before_around_and_difference(self):
        resolver, _, select = self.resolver([{'type': 'node', 'id': 1, 'lat': 5, 'lon': 5}])
        query = ('area(id:3600051477)->.searchArea;'
                 'nwr["railway"="station"](area.searchArea)->.stations;'
                 'rel["public_transport"="stop_area"](around.stations:1000)->.stops;'
                 '(.stations; - .stops;);out geom;')
        result = resolver.rewrite(query)
        self.assertIn('node(id:1)["railway"="station"];\n)->.stations;', result)
        self.assertTrue(result.endswith('rel["public_transport"="stop_area"](around.stations:1000)->.stops;'
                                        '(.stations; - .stops;);out geom;'))
        self.assertNotIn('stop_area', select.call_args.args[0])

    def test_holes_and_islands_in_holes_filter_candidates_exactly(self):
        hole = [(3, 3), (3, 7), (7, 7), (7, 3), (3, 3)]
        island = [(4, 4), (4, 5), (5, 5), (5, 4), (4, 4)]
        relation = boundary(member(1, SQUARE), member(2, hole, 'inner'), member(3, island))
        candidates = [{'type': 'node', 'id': 1, 'lat': 1, 'lon': 1},
                      {'type': 'node', 'id': 2, 'lat': 6, 'lon': 6},
                      {'type': 'node', 'id': 3, 'lat': 4.5, 'lon': 4.5},
                      dict(member(4, [(5.5, 5.5), (6.5, 6.5)]), id=4, type='way')]
        resolver, _, _ = self.resolver(candidates, relation)
        result = resolver.rewrite('nwr["test"](area:3600051477);out;')
        self.assertIn('node(id:1,3)["test"]', result)
        self.assertNotIn('way(id:', result)

    def test_selection_and_shape_are_cached_and_ids_stay_separate_by_type(self):
        candidates = [{'type': 'node', 'id': 5, 'lat': 1, 'lon': 1},
                      dict(member(5, [(1, 1), (2, 2)]), id=5, type='way')]
        resolver, fetch, select = self.resolver(candidates)
        query = 'nwr["test"](area:3600051477);out;'
        first = resolver.rewrite(query)
        self.assertEqual(first, resolver.rewrite(query))
        self.assertIn('node(id:5)["test"]', first)
        self.assertIn('way(id:5)["test"]', first)
        fetch.assert_called_once()
        select.assert_called_once()

    def test_count_tags_condition_does_not_count_requested_geometry(self):
        resolver, _, select = self.resolver([{'type': 'node', 'id': 1, 'lat': 5, 'lon': 5}])
        query = 'nwr["note"~"bgerissen"](if:count_tags()==1)(area:3600051477);out tags geom;'
        result = resolver.rewrite(query)
        self.assertIn('(if:count_tags()==1)', result)
        self.assertIn('(if:count_tags()==1)', select.call_args.args[0])

    def test_empty_selection_is_represented_by_explicit_empty_id_query(self):
        resolver, _, _ = self.resolver([])
        result = resolver.rewrite('node(area:3600051477)->.a;out;')
        self.assertEqual(result, '(\nnode(id:0);\n)->.a;out;')

    def test_dependent_input_or_spatial_selectors_are_rejected(self):
        for query in ('node.a["x"](area:3600051477);out;',
                      'node(around.a:20)(area:3600051477);out;',
                      'nwr(if:.a.count(nodes)>0)(area:3600051477);out;'):
            with self.subTest(query=query):
                resolver, _, select = self.resolver([])
                with self.assertRaises(AreaFilterError):
                    resolver.rewrite(query)
                select.assert_not_called()

    def test_missing_candidate_geometry_never_silently_drops_objects(self):
        for candidate in ({'type': 'way', 'id': 1},
                          {'type': 'way', 'id': 1, 'geometry': [None]},
                          {'type': 'node', 'id': 1},
                          {'type': 'relation', 'id': 1, 'members': [{'type': 'node', 'ref': 1}]},
                          {'type': 'node', 'id': -1, 'lat': 5, 'lon': 5}):
            with self.subTest(candidate=candidate):
                resolver, _, _ = self.resolver([candidate])
                with self.assertRaises(AreaFilterError):
                    resolver.rewrite('nwr(area:3600051477);out;')


if __name__ == '__main__':
    unittest.main()
