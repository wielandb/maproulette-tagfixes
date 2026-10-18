import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from shared.challenge_builder import Overpass


FRANCE_URL = "https://overpass.openstreetmap.fr/api/interpreter"
OTHER_URL = "https://another.example.invalid/api/interpreter"
AREA_QUERY = '[out:json];node["highway"="give_way"][!"direction"](area:3600051477);out geom;'
ELEMENTS = [{"type": "node", "id": 123, "lat": 50.5, "lon": 8.5}]
CANDIDATES = ELEMENTS + [{"type": "node", "id": 999, "lat": 52, "lon": 8.5}]


def response(elements=None, *, status=200, age=timedelta(hours=1), remark=None):
    payload = {
        "osm3s": {
            "timestamp_osm_base": (datetime.now(timezone.utc) - age).isoformat(),
        },
        "elements": ELEMENTS if elements is None else elements,
    }
    if remark is not None:
        payload["remark"] = remark
    result = Mock(status_code=status, text=remark or "Overpass response", headers={})
    result.json.return_value = payload
    return result


def boundary(*, relation_id=51477, closed=True):
    coordinates = [(50, 8), (50, 9), (51, 9), (51, 8)]
    if closed:
        coordinates.append(coordinates[0])
    return {
        "type": "relation",
        "id": relation_id,
        "members": [{
            "type": "way",
            "ref": 321,
            "role": "outer",
            "geometry": [{"lat": lat, "lon": lon} for lat, lon in coordinates],
        }],
    }


class FranceOverpassTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=False)
        environment.start()
        os.environ.pop("OVERPASS_URLS", None)
        self.addCleanup(environment.stop)
        post = patch("shared.challenge_builder.requests.post")
        self.post = post.start()
        self.addCleanup(post.stop)
        get = patch("shared.challenge_builder.requests.get")
        self.get = get.start()
        self.get.side_effect = AssertionError("Unexpected OSM API request")
        self.addCleanup(get.stop)
        sleep = patch("shared.challenge_builder.sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)

    def client(self):
        return Overpass(overpass_urls=[FRANCE_URL, OTHER_URL], max_attempts=2)

    def test_rate_limit_during_boundary_lookup_also_waits_thirty_seconds(self):
        self.post.side_effect = [response(status=429), response()]
        self.assertEqual(self.client().getElementsFromQuery(AREA_QUERY), ELEMENTS)
        self.sleep.assert_called_once_with(30)
        self.assertEqual(self.post.call_args.args[0], OTHER_URL)

    def sent_queries(self):
        return [request.kwargs["data"]["data"] for request in self.post.call_args_list]

    def test_default_client_prefers_france_and_identifies_the_project(self):
        self.post.return_value = response()

        self.assertEqual(Overpass().getElementsFromQuery('[out:json];node(1);out;'), ELEMENTS)

        self.assertEqual(Overpass.DEFAULT_URLS[0], FRANCE_URL)
        self.post.assert_called_once()
        self.assertEqual(self.post.call_args.args[0], FRANCE_URL)
        user_agent = self.post.call_args.kwargs["headers"]["User-Agent"]
        self.assertIn("maproulette-tagfixes", user_agent)
        self.assertIn("https://github.com/wielandb/maproulette-tagfixes", user_agent)

    def test_country_area_query_fetches_boundary_and_candidates_before_sending_selected_ids(self):
        self.post.side_effect = [response([boundary()]), response(CANDIDATES), response()]

        self.assertEqual(self.client().getElementsFromQuery(AREA_QUERY), ELEMENTS)

        boundary_query, candidate_query, task_query = self.sent_queries()
        self.assertIn('relation(51477);out geom;', boundary_query)
        self.assertIn('(50.0000000,8.0000000,51.0000000,9.0000000)', candidate_query)
        self.assertIn('["highway"="give_way"][!"direction"]', candidate_query)
        self.assertIn('node(id:123)', task_query)
        self.assertNotIn('999', task_query)
        self.assertIn('["highway"="give_way"][!"direction"]', task_query)
        self.assertNotIn('(area:', task_query)
        self.assertNotIn('(poly:', task_query)
        self.assertTrue(task_query.endswith('out geom;'))
        self.assertEqual([request.args[0] for request in self.post.call_args_list], [FRANCE_URL] * 3)
        self.sleep.assert_not_called()

    def test_named_area_declaration_is_replaced_without_losing_selection_or_output(self):
        query = ('[out:json];area(id:3600051477)->.searchArea;'
                 'nwr["amenity"="nursing_home"](area.searchArea);out center;')
        self.post.side_effect = [response([boundary()]), response(CANDIDATES), response()]

        self.assertEqual(self.client().getElementsFromQuery(query), ELEMENTS)

        task_query = self.sent_queries()[2]
        self.assertIn('node(id:123)["amenity"="nursing_home"]', task_query)
        self.assertNotIn('999', task_query)
        self.assertNotIn('area(', task_query)
        self.assertNotIn('(area.searchArea)', task_query)
        self.assertTrue(task_query.endswith('out center;'))

    def test_successive_queries_reuse_the_boundary_within_the_client(self):
        self.post.side_effect = [
            response([boundary()]), response(CANDIDATES), response(),
            response(CANDIDATES), response(),
        ]
        client = self.client()

        self.assertEqual(client.getElementsFromQuery(AREA_QUERY), ELEMENTS)
        self.assertEqual(client.getElementsFromQuery(AREA_QUERY.replace('give_way', 'stop')), ELEMENTS)

        queries = self.sent_queries()
        self.assertEqual(len(queries), 5)
        self.assertEqual(sum('relation(51477);out geom;' in query for query in queries), 1)
        self.assertIn('node(id:123)["highway"="stop"]', queries[-1])

    def test_node_inside_the_bbox_but_outside_the_country_is_excluded(self):
        triangle = boundary()
        triangle["members"][0]["geometry"] = [
            {"lat": 50, "lon": 8}, {"lat": 50, "lon": 9},
            {"lat": 51, "lon": 8}, {"lat": 50, "lon": 8},
        ]
        inside = {"type": "node", "id": 123, "lat": 50.1, "lon": 8.1}
        outside = {"type": "node", "id": 999, "lat": 50.9, "lon": 8.9}
        self.post.side_effect = [response([triangle]), response([inside, outside]), response([inside])]

        self.assertEqual(self.client().getElementsFromQuery(AREA_QUERY), [inside])

        self.assertIn('node(id:123)', self.sent_queries()[-1])
        self.assertNotIn('999', self.sent_queries()[-1])

    def test_missing_or_invalid_boundary_falls_back_with_the_original_area_query(self):
        for elements in ([], [boundary(relation_id=999)], [boundary(closed=False)]):
            with self.subTest(elements=elements):
                self.post.reset_mock()
                self.sleep.reset_mock()
                self.post.side_effect = [response(elements), response()]

                self.assertEqual(self.client().getElementsFromQuery(AREA_QUERY), ELEMENTS)

                self.assertEqual([request.args[0] for request in self.post.call_args_list], [FRANCE_URL, OTHER_URL])
                self.assertEqual(self.sent_queries()[1], AREA_QUERY)
                self.sleep.assert_called_once_with(5)

    def test_boundary_http_failure_falls_back_without_querying_france_with_area_syntax(self):
        self.post.side_effect = [response(status=500), response()]

        self.assertEqual(self.client().getElementsFromQuery(AREA_QUERY), ELEMENTS)

        self.assertEqual(self.sent_queries()[1], AREA_QUERY)
        self.assertEqual(self.post.call_args_list[1].args[0], OTHER_URL)
        self.assertEqual(self.post.call_count, 2)

    def test_translated_query_parse_error_is_not_repeated_on_another_server(self):
        for status in (400, 200):
            with self.subTest(status=status):
                self.post.reset_mock()
                self.sleep.reset_mock()
                self.post.side_effect = [
                    response([boundary()]),
                    response(CANDIDATES),
                    response([], status=status, remark='line 1: parse error: Unknown type'),
                ]

                with self.assertRaisesRegex(ValueError, 'parse error'):
                    self.client().getElementsFromQuery(AREA_QUERY)

                self.assertEqual([request.args[0] for request in self.post.call_args_list], [FRANCE_URL] * 3)
                self.sleep.assert_not_called()

    def test_stale_http_200_data_is_rejected_and_fresh_alternative_is_used(self):
        stale = [{"type": "node", "id": 999}]
        self.post.side_effect = [response(stale, age=timedelta(days=8)), response()]
        client = self.client()
        query = '[out:json];node(1);out;'

        self.assertEqual(client.getElementsFromQuery(query), ELEMENTS)

        self.assertEqual([request.args[0] for request in self.post.call_args_list], [FRANCE_URL, OTHER_URL])
        self.assertEqual(self.sent_queries(), [query, query])
        self.assertEqual(client.overpass_url, OTHER_URL)

    def test_stale_boundary_is_not_cached_or_used_for_country_selection(self):
        self.post.side_effect = [
            response([boundary()], age=timedelta(days=8)), response(),
            response(status=503), response([boundary()]), response(CANDIDATES), response(),
        ]
        client = self.client()

        self.assertEqual(client.getElementsFromQuery(AREA_QUERY), ELEMENTS)

        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(self.post.call_args_list[1].args[0], OTHER_URL)
        self.assertEqual(self.sent_queries()[1], AREA_QUERY)
        # Return to France after the other server fails: the country boundary
        # must be fetched again, rather than using the earlier stale response.
        self.assertEqual(client.getElementsFromQuery(AREA_QUERY), ELEMENTS)
        queries = self.sent_queries()
        self.assertEqual(sum('relation(51477);out geom;' in query for query in queries), 2)
        self.assertIn('node(id:123)', queries[-1])

    def test_incomplete_boundary_way_is_fully_replaced_and_the_repair_is_cached(self):
        complete = boundary()["members"][0]["geometry"]
        first, second = boundary(), boundary()
        for relation in (first, second):
            relation["members"][0]["geometry"] = [complete[0], None, complete[-1]]
        self.post.side_effect = [response([first]), response([second])]
        nodes = [
            {"type": "node", "id": index + 1, **point}
            for index, point in enumerate(complete[:-1])
        ]
        self.get.side_effect = None
        self.get.return_value = response([
            {"type": "way", "id": 321, "nodes": [1, 2, 3, 4, 1]}, *nodes,
        ])
        client = self.client()

        for _ in range(2):
            result = client._fetch_boundary(FRANCE_URL, 51477)
            self.assertEqual(result["members"][0]["geometry"], complete)

        self.get.assert_called_once()
        self.assertEqual(self.get.call_args.args[0], "https://api.openstreetmap.org/api/0.6/way/321/full.json")

    def test_changed_repair_endpoints_fail_closed(self):
        self.get.side_effect = None
        self.get.return_value = response([
            {"type": "way", "id": 321, "nodes": [1, 2, 3]},
            {"type": "node", "id": 1, "lat": 50, "lon": 8},
            {"type": "node", "id": 2, "lat": 50.5, "lon": 8.4},
            {"type": "node", "id": 3, "lat": 51, "lon": 9},
        ])

        with self.assertRaisesRegex(ValueError, "endpoints have changed"):
            self.client()._repair_boundary_way(321, [
                {"lat": 50, "lon": 8}, None, {"lat": 51, "lon": 8},
            ])

        self.get.assert_called_once()
        self.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
