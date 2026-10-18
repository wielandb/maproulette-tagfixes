import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import Mock, call, patch

import requests

from shared.challenge_builder import Overpass


FIRST_URL = "https://first.example.invalid/api/interpreter"
SECOND_URL = "https://second.example.invalid/api/interpreter"
THIRD_URL = "https://third.example.invalid/api/interpreter"
QUERY = '[out:json];node["highway"="stop"];out;'
ELEMENTS = [{"type": "node", "id": 123, "lat": 50, "lon": 8}]


def response(status=200, payload=None, body="test response"):
    result = Mock(status_code=status, text=body, headers={})
    result.json.return_value = {"elements": ELEMENTS} if payload is None else payload
    return result


class OverpassFailoverTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        os.environ.pop("OVERPASS_URLS", None)
        self.addCleanup(self.environment.stop)
        self.post = patch("shared.challenge_builder.requests.post").start()
        self.sleep = patch("shared.challenge_builder.sleep").start()
        self.addCleanup(patch.stopall)

    def client(self, **kwargs):
        kwargs.setdefault("overpass_urls", [FIRST_URL, SECOND_URL])
        return Overpass(**kwargs)

    def called_urls(self):
        return [item.args[0] for item in self.post.call_args_list]

    def test_http_406_uses_another_server_after_a_thirty_second_pause(self):
        self.post.side_effect = [response(406), response()]
        self.assertEqual(self.client().getElementsFromQuery(QUERY), ELEMENTS)
        self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL])
        self.sleep.assert_called_once_with(30)

    def test_transient_http_failures_switch_servers(self):
        for status in (403, 408, 429, 500, 501, 502, 503, 504, 599):
            with self.subTest(status=status):
                self.post.reset_mock()
                self.sleep.reset_mock()
                self.post.side_effect = [response(status), response()]
                self.assertEqual(self.client().getElementsFromQuery(QUERY), ELEMENTS)
                self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL])
                self.sleep.assert_called_once_with(30 if status == 429 else 5)

    def test_transport_failures_switch_servers(self):
        for failure in (requests.Timeout("read timed out"), requests.ConnectionError("offline")):
            with self.subTest(failure=failure):
                self.post.reset_mock()
                self.sleep.reset_mock()
                self.post.side_effect = [failure, response()]
                self.assertEqual(self.client().getElementsFromQuery(QUERY), ELEMENTS)
                self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL])
                self.sleep.assert_called_once_with(5)

    def test_invalid_json_fails_over_instead_of_crashing_on_html(self):
        html = response(body="<html><h1>Service unavailable</h1></html>")
        html.json.side_effect = ValueError("not JSON")
        self.post.side_effect = [html, response()]
        self.assertEqual(self.client().getElementsFromQuery(QUERY), ELEMENTS)
        self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL])
        self.sleep.assert_called_once_with(5)

    def test_unusable_success_responses_are_retried(self):
        for payload in ([], {"elements": {}}, {}, {"remark": "runtime error: out of memory"}):
            with self.subTest(payload=payload):
                self.post.reset_mock()
                self.sleep.reset_mock()
                self.post.side_effect = [response(payload=payload), response()]
                self.assertEqual(self.client().getElementsFromQuery(QUERY), ELEMENTS)
                self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL])
                self.sleep.assert_called_once_with(5)

    def test_partial_results_with_runtime_error_are_discarded(self):
        self.post.side_effect = [
            response(payload={"elements": [{"id": 999}], "remark": "runtime error: Query timed out"}),
            response(),
        ]
        self.assertEqual(self.client().getElementsFromQuery(QUERY), ELEMENTS)
        self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL])

    def test_attempt_budget_is_total_across_servers_and_backoff_is_capped(self):
        self.post.return_value = response(503, body="<h1>Service unavailable</h1>")
        with self.assertRaises(ValueError) as failure:
            self.client(max_attempts=7).getElementsFromQuery(QUERY)
        self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL, FIRST_URL, SECOND_URL, FIRST_URL, SECOND_URL, FIRST_URL])
        self.assertEqual(self.sleep.call_args_list, [call(5), call(10), call(20), call(40), call(60), call(60)])
        self.assertIn(FIRST_URL, str(failure.exception))
        self.assertIn(SECOND_URL, str(failure.exception))
        self.assertIn("503", str(failure.exception))

    def test_single_attempt_never_sleeps_or_contacts_another_server(self):
        self.post.return_value = response(503)
        with self.assertRaises(ValueError):
            self.client(max_attempts=1).getElementsFromQuery(QUERY)
        self.assertEqual(self.called_urls(), [FIRST_URL])
        self.sleep.assert_not_called()

    def test_successful_server_is_reused_for_the_next_query(self):
        self.post.side_effect = [response(503), response(), response()]
        client = self.client()
        self.assertEqual(client.getElementsFromQuery(QUERY), ELEMENTS)
        self.assertEqual(client.getElementsFromQuery("second query"), ELEMENTS)
        self.assertEqual(self.called_urls(), [FIRST_URL, SECOND_URL, SECOND_URL])
        self.sleep.assert_called_once_with(5)

    def test_syntax_errors_do_not_repeat_on_another_server(self):
        for status, payload, body in (
            (400, None, "<p>parse error: Unknown type foo</p>"),
            (200, {"elements": [], "remark": "line 1: parse error: Unknown type foo"}, "test response"),
        ):
            with self.subTest(status=status):
                self.post.reset_mock()
                self.sleep.reset_mock()
                self.post.side_effect = None
                self.post.return_value = response(status, payload, body)
                with self.assertRaisesRegex(ValueError, "parse error"):
                    self.client().getElementsFromQuery(QUERY)
                self.assertEqual(self.called_urls(), [FIRST_URL])
                self.sleep.assert_not_called()

    def test_request_has_identifying_headers_and_configured_timeout(self):
        self.post.return_value = response()
        self.client(request_timeout=120).getElementsFromQuery(QUERY)
        kwargs = self.post.call_args.kwargs
        self.assertEqual(kwargs["data"], {"data": QUERY})
        self.assertEqual(kwargs["timeout"], (10, 120))
        self.assertEqual(kwargs["headers"]["Accept"], "application/json")
        self.assertIn("maproulette", kwargs["headers"]["User-Agent"].lower())

    def test_error_details_are_single_line_plain_text(self):
        self.post.return_value = response(503, body="<html>\r\n<h1>Service unavailable</h1>\r<center>nginx</center>\n</html>")
        with self.assertRaises(ValueError) as failure:
            self.client(max_attempts=1).getElementsFromQuery(QUERY)
        message = str(failure.exception)
        self.assertIn("Service unavailable", message)
        self.assertNotIn("\r", message)
        self.assertNotIn("\n", message)
        self.assertNotIn("<h1>", message)
        self.assertNotIn("</html>", message)

    def test_retry_diagnostics_identify_server_attempt_status_and_delay(self):
        self.post.side_effect = [response(503), response()]
        messages = io.StringIO()
        with redirect_stderr(messages):
            self.client().getElementsFromQuery(QUERY)
        diagnostic = messages.getvalue()
        self.assertIn(FIRST_URL, diagnostic)
        self.assertIn("503", diagnostic)
        self.assertIn("1/6", diagnostic)
        self.assertRegex(diagnostic, r"5(?:\.0)?\s*s")

    def test_environment_urls_are_trimmed_and_used_in_order(self):
        os.environ["OVERPASS_URLS"] = f" {SECOND_URL} , {THIRD_URL} "
        self.post.side_effect = [response(503), response()]
        self.assertEqual(Overpass().getElementsFromQuery(QUERY), ELEMENTS)
        self.assertEqual(self.called_urls(), [SECOND_URL, THIRD_URL])

    def test_explicit_urls_override_the_environment(self):
        os.environ["OVERPASS_URLS"] = THIRD_URL
        self.post.return_value = response()
        self.assertEqual(self.client(overpass_urls=(FIRST_URL,)).getElementsFromQuery(QUERY), ELEMENTS)
        self.assertEqual(self.called_urls(), [FIRST_URL])

    def test_invalid_configuration_is_rejected_before_requesting(self):
        for options in (
            {"max_attempts": 0}, {"max_attempts": -1}, {"max_attempts": 1.5}, {"max_attempts": True},
            {"retry_delay": -1}, {"retry_delay": float("inf")}, {"retry_delay": float("nan")},
            {"request_timeout": 0}, {"request_timeout": -1},
            {"request_timeout": float("inf")}, {"request_timeout": float("nan")},
            {"overpass_urls": []}, {"overpass_urls": [""]},
            {"overpass_urls": ["ftp://example.invalid"]}, {"overpass_urls": FIRST_URL},
        ):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.client(**options)
        self.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
