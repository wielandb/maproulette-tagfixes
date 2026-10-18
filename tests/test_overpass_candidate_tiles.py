import re
import unittest
from unittest.mock import Mock, patch

import requests

from shared.challenge_builder import Overpass


URL = 'https://overpass.openstreetmap.fr/api/interpreter'
QUERY = '[out:json][timeout:250];node["highway"="give_way"](48,8,49,9);out skel geom;'


def response(elements=(), *, status=200, remark=None):
    result = Mock(status_code=status, text=remark or 'Service unavailable')
    result.json.return_value = {'elements': list(elements)}
    if remark:
        result.json.return_value['remark'] = remark
    return result


class CandidateTileTests(unittest.TestCase):
    def setUp(self):
        self.client = Overpass(overpass_urls=[URL], max_attempts=1)
        patcher = patch('shared.challenge_builder.requests.post')
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.post.return_value = response()
        quiet = patch('builtins.print')
        quiet.start()
        self.addCleanup(quiet.stop)

    def queries(self):
        return [call.kwargs['data']['data'] for call in self.post.call_args_list]

    def bboxes(self):
        return [tuple(map(float, re.search(r'\((-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\)', query).groups()))
                for query in self.queries()]

    def test_small_bbox_uses_one_request_and_preserves_the_selector(self):
        node = {'type': 'node', 'id': 1, 'lat': 48.5, 'lon': 8.5}
        self.post.return_value = response([node])

        self.assertEqual(self.client._fetch_area_candidates(URL, QUERY), [node])

        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.queries(), [QUERY.replace('[timeout:250]', '[timeout:60]').replace('(48,8,49,9)', '(48.0000000,8.0000000,49.0000000,9.0000000)')])
        self.assertEqual(self.post.call_args.kwargs['timeout'], (10, 90))

    def test_tiles_cover_the_rectangle_without_gaps_and_deduplicate_by_type_and_id(self):
        query = QUERY.replace('(48,8,49,9)', '(46,5,54,15)')
        node, way = {'type': 'node', 'id': 7}, {'type': 'way', 'id': 7}
        self.post.return_value = response([node, way])

        self.assertEqual(self.client._fetch_area_candidates(URL, query), [node, way])

        boxes = self.bboxes()
        self.assertGreater(len(boxes), 1)
        self.assertLessEqual(len(boxes), 128)
        self.assertAlmostEqual(sum((n - s) * (e - w) for s, w, n, e in boxes), 80)
        self.assertTrue(all(46 <= s < n <= 54 and 5 <= w < e <= 15 and max(n-s, e-w) <= 2 for s,w,n,e in boxes))
        # Every grid midpoint belongs to exactly one tile; shared edges remain inclusive.
        for lat in [46 + i / 4 + .125 for i in range(32)]:
            for lon in [5 + i / 4 + .125 for i in range(40)]:
                self.assertEqual(sum(s < lat < n and w < lon < e for s,w,n,e in boxes), 1)

    def test_real_query_timeout_discards_partial_data_and_splits_the_longer_axis(self):
        abandoned = {'type': 'node', 'id': 999}
        kept = {'type': 'node', 'id': 1}
        self.post.side_effect = [response([abandoned], remark='runtime error: Query timed out in "query" after 61 seconds.'), response([kept]), response([kept])]

        self.assertEqual(self.client._fetch_area_candidates(URL, QUERY), [kept])

        self.assertEqual(self.bboxes(), [(48,8,49,9), (48,8,48.5,9), (48.5,8,49,9)])

    def test_query_out_of_memory_and_read_timeout_also_split(self):
        for failed in (response(remark='runtime error: Query run out of memory in "query".'), requests.ReadTimeout('response timed out')):
            with self.subTest(failed=failed):
                self.post.reset_mock()
                self.post.side_effect = [failed, response(), response()]
                self.assertEqual(self.client._fetch_area_candidates(URL, QUERY), [])
                self.assertEqual(self.post.call_count, 3)

    def test_http_errors_and_unrelated_errors_never_trigger_subdivision(self):
        for failed in [response(status=status) for status in (403,406,429,500,502,503,504)] + [response(remark='runtime error: Dispatcher_Client::request_read_and_idx::timeout'), response(remark='line 1: parse error: Unknown type'), response(remark='unexpected backend error')]:
            with self.subTest(failed=failed):
                self.post.reset_mock()
                self.post.side_effect = None
                self.post.return_value = failed
                with self.assertRaises(ValueError):
                    self.client._fetch_area_candidates(URL, QUERY)
                self.assertEqual(self.post.call_count, 1)

    def test_tiny_bbox_failure_and_adaptive_depth_limit_return_no_partial_result(self):
        timeout = response(remark='runtime error: Query timed out after 61 seconds.')
        for query, max_calls in ((QUERY.replace('(48,8,49,9)', '(48,8,48.01,8.01)'), 1), (QUERY, 9)):
            with self.subTest(query=query):
                self.post.reset_mock()
                self.post.return_value = timeout
                with self.assertRaises(ValueError):
                    self.client._fetch_area_candidates(URL, query)
                self.assertLessEqual(self.post.call_count, max_calls)

    def test_request_budget_is_enforced_without_returning_collected_elements(self):
        node = {'type': 'node', 'id': 1}
        def results(*args, **kwargs):
            if self.post.call_count % 3 == 1:
                return response(remark='runtime error: Query timed out after 61 seconds.')
            return response([node])
        self.post.side_effect = results
        with self.assertRaisesRegex(ValueError, '128 requests'):
            self.client._fetch_area_candidates(URL, QUERY.replace('(48,8,49,9)', '(40,0,56,16)'))
        self.assertEqual(self.post.call_count, 128)

    def test_invalid_bbox_or_identity_fails_closed(self):
        for query in (QUERY.replace('(48,8,49,9)', ''), QUERY.replace('(48,8,49,9)', '(49,8,48,9)'), QUERY.replace('(48,8,49,9)', '(48,8,49,9)(48,8,49,9)')):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.client._fetch_area_candidates(URL, query)
        self.post.assert_not_called()
        self.post.return_value = response([{'type':'node','id':True}])
        with self.assertRaisesRegex(ValueError, 'invalid element identity'):
            self.client._fetch_area_candidates(URL, QUERY)

    def test_bbox_and_timeout_text_inside_tag_values_is_preserved(self):
        query = QUERY.replace('["highway"="give_way"]', '["note"="[timeout:250] (1,2,3,4)"]')
        self.client._fetch_area_candidates(URL, query)
        self.assertIn('["note"="[timeout:250] (1,2,3,4)"]', self.queries()[0])

    def test_failed_candidate_tiles_fall_back_with_the_complete_original_query(self):
        original = '[out:json];node["highway"="give_way"](area:3600051477);out geom;'
        other = 'https://another.example.invalid/api/interpreter'
        client = Overpass(overpass_urls=[URL, other], max_attempts=2, retry_delay=0)
        boundary = {'type':'relation','id':51477,'members':[{'type':'way','ref':1,'role':'outer','geometry':[{'lat':48,'lon':8},{'lat':48,'lon':9},{'lat':49,'lon':9},{'lat':49,'lon':8},{'lat':48,'lon':8}]}]}
        node = {'type':'node','id':7}
        self.post.side_effect = [response([boundary]),response(status=503),response([node])]
        with patch('shared.challenge_builder.sleep'):
            self.assertEqual(client.getElementsFromQuery(original), [node])
        self.assertEqual(self.post.call_count,3)
        self.assertEqual(self.post.call_args.args[0],other)
        self.assertEqual(self.queries()[-1],original)


if __name__ == '__main__':
    unittest.main()
