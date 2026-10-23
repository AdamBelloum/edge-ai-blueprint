"""Grading script for Assignment 1 (URL shortener).

The script sends HTTP requests to a running service and checks the answers
against the assignment. Every check belongs to a line of the grading rubric.
Run the file directly to see the points per line:

    python test_api.py                          # service on http://127.0.0.1:5000
    python test_api.py --url http://HOST:PORT
    python -m unittest -v test_api              # pass/fail only

Start the service first. The checks create mappings, and every test ends
with DELETE /, which removes all mappings in the service.

Request bodies are JSON, as in the course test script: POST / sends
{"value": URL} and PUT /<id> sends {"url": URL}. For GET /<id>, status 301
with either a Location header or the URL in a JSON body counts.

Only what can be observed over HTTP is tested. The points that need the
TA's judgement (code, presentation, report) are listed after the results.
Requires the requests package.
"""
import argparse
import csv
import os
import random
import re
import sys
import unittest
import uuid
from pathlib import Path
from urllib.parse import unquote

import requests

BASE_URL = os.environ.get("SHORTENER_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
TIMEOUT = (5, 30)  # seconds to connect, seconds to wait for the answer

# Rubric lines checked here: (description, points, tests that must all pass).
# Methods are worth 10 points: 7 for the test functions of the course test
# script, the rest for additional effort.
RUBRIC = [
    ("Methods: GET /:id answers 301 with the URL", 1, ["TestApi.test_get_request_with_id_success"]),
    ("Methods: GET /:id answers 404 for an unknown id", 1, ["TestApi.test_get_request_with_id_expect_404"]),
    ("Methods: PUT /:id (200, 400, 404)", 1, ["TestApi.test_put_id"]),
    ("Methods: DELETE /:id (204, 404)", 1, ["TestApi.test_deletion_id"]),
    ("Methods: GET / lists the keys", 1, ["TestApi.test_get_all"]),
    ("Methods: POST / (201, 400)", 1, ["TestApi.test_post"]),
    ("Methods: DELETE / (404, mappings removed)", 1, ["TestApi.test_deletion_all"]),
    ("Hash function: unique ids, no conflicts after deletes", 2,
     ["TestIdentifiers.test_ids_are_unique", "TestIdentifiers.test_deletes_cause_no_conflicts"]),
    ("URL validity: invalid URLs are rejected with 400", 2, ["TestUrlValidation.test_invalid_urls_are_rejected"]),
    ("URL validity: other input, such as \"uva.nl\"", 1, ["TestUrlValidation.test_other_input"]),
]
NOT_TESTED = [
    ("Methods: additional effort", 3),
    ("Hash function: extra settings", 1),
    ("Presentation", 4),
    ("Report", 20),
    ("Question", 5),
]

URL_COLUMNS = ("url_to_shorten_1", "url_to_shorten_2", "url_after_update")
# Clearly not URLs. Together with invalid_url from read_from.csv, any sensible
# check rejects these, also one that adds a missing "https://".
INVALID_URLS = ["not a url", "http//example.com", "www"]
# Input a TA may try during the demo.
OTHER_VALID_URLS = [
    "https://www.uva.nl",
    "https://www.uva.nl/en/education?lang=en#programmes",
    "http://example.com:8080/index.html",
]
OTHER_INVALID_INPUT = ["http://", "https://www.uva .nl", "javascript:alert(1)", 12345]

CSV_ROWS = []
NOTES = []  # observations printed after the points


def setUpModule():
    path = Path(__file__).with_name("read_from.csv")
    with path.open(encoding="utf-8", newline="") as stream:
        CSV_ROWS.extend(row for row in csv.DictReader(stream) if row.get("url_to_shorten_1"))
    call("GET", "/")  # fails early if the service is not running


def call(method, path, **kwargs):
    """Send a request to the service. Redirects are not followed."""
    url = BASE_URL + path
    try:
        return requests.request(method, url, allow_redirects=False, timeout=TIMEOUT, **kwargs)
    except requests.ConnectionError:
        raise AssertionError(f"{method} {url}: cannot connect; is the service running?") from None
    except requests.Timeout:
        raise AssertionError(f"{method} {url}: no answer within {TIMEOUT[1]} seconds") from None


def body_of(response):
    """The decoded JSON body of a response, or None."""
    try:
        return response.json()
    except ValueError:
        return None


def describe(response):
    """Status code and the start of the body, for failure messages."""
    text = " ".join(response.text.split())
    if len(text) > 100:
        text = text[:97] + "..."
    return f"{response.status_code} {text}".strip()


def returned_id(response):
    """The identifier in the answer to POST /, or None."""
    body = body_of(response)
    if isinstance(body, dict):
        for key in ("id", "key", "short_id", "identifier"):
            value = body.get(key)
            if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value):
                return str(value)
        values = [value for value in body.values() if isinstance(value, str) and value]
        return values[0] if len(values) == 1 else None
    if isinstance(body, (str, int)) and not isinstance(body, bool):
        return str(body)
    text = response.text.strip()
    if body is None and text and len(text) <= 64 and not any(char.isspace() for char in text):
        return text
    return None


def target_of(response):
    """The URL a 301 answer points to: the Location header, or the URL in the JSON body."""
    location = response.headers.get("Location")
    if location:
        return location
    body = body_of(response)
    if isinstance(body, dict):
        for key in ("value", "url", "long_url", "target"):
            if isinstance(body.get(key), str):
                return body[key]
        values = [value for value in body.values() if isinstance(value, str)]
        return values[0] if len(values) == 1 else None
    return body if isinstance(body, str) else None


def same_url(first, second):
    """Compare URLs, ignoring percent-encoding (a Location header must be ASCII)."""
    return first is not None and second is not None and unquote(first) == unquote(second)


def listed_items(value):
    """What a JSON answer lists: dictionary keys, strings, and numbers in lists."""
    if isinstance(value, dict):
        found = {str(key) for key in value}
        for item in value.values():
            found |= listed_items(item)
        return found
    if isinstance(value, list):
        found = set()
        for item in value:
            if isinstance(item, int) and not isinstance(item, bool):
                found.add(str(item))
            else:
                found |= listed_items(item)
        return found
    return {value} if isinstance(value, str) else set()


def unknown_id():
    """An identifier the service does not know.

    read_from.csv has a column not_existing_id ("1", "2"), but those are valid
    identifiers when ids come from a counter, so a random one is used instead.
    """
    return "unknown" + uuid.uuid4().hex[:10]


class GradingTest(unittest.TestCase):
    longMessage = False

    def tearDown(self):
        try:
            call("DELETE", "/")
        except AssertionError:
            pass

    def assert_status(self, response, expected, action):
        self.assertEqual(expected, response.status_code,
                         f"{action}: expected {expected}, got {describe(response)}")

    def create(self, url):
        """POST / with url and return the new identifier."""
        response = call("POST", "/", json={"value": url})
        self.assert_status(response, 201, f"POST / with {url!r}")
        short_id = returned_id(response)
        self.assertTrue(short_id, f"POST / with {url!r}: no id in the answer {describe(response)}")
        return short_id

    def assert_points_to(self, short_id, url):
        response = call("GET", f"/{short_id}")
        self.assert_status(response, 301, f"GET /{short_id}")
        target = target_of(response)
        self.assertTrue(same_url(target, url), f"GET /{short_id}: expected {url!r}, got {target!r}")


class TestApi(GradingTest):
    """The seven test functions of the course test script."""

    def setUp(self):
        row = random.choice(CSV_ROWS)
        self.url_1 = row["url_to_shorten_1"]
        self.url_2 = row["url_to_shorten_2"]
        self.url_after_update = row["url_after_update"]
        self.invalid_url = row["invalid_url"]
        self.id_1 = self.create(self.url_1)
        self.id_2 = self.create(self.url_2)

    def test_get_request_with_id_success(self):
        self.assert_points_to(self.id_1, self.url_1)

    def test_get_request_with_id_expect_404(self):
        self.assert_status(call("GET", f"/{unknown_id()}"), 404, "GET /<unknown id>")

    def test_put_id(self):
        path = f"/{self.id_1}"
        response = call("PUT", path, json={"url": self.url_after_update})
        self.assert_status(response, 200, f"PUT {path} with a valid URL")
        self.assert_points_to(self.id_1, self.url_after_update)
        response = call("PUT", path, json={"url": self.invalid_url})
        self.assert_status(response, 400, f"PUT {path} with {self.invalid_url!r}")
        response = call("PUT", f"/{unknown_id()}", json={"url": self.url_after_update})
        self.assert_status(response, 404, "PUT /<unknown id>")

    def test_deletion_id(self):
        path = f"/{self.id_1}"
        self.assert_status(call("DELETE", path), 204, f"DELETE {path}")
        self.assert_status(call("GET", path), 404, f"GET {path} after deleting it")
        self.assert_status(call("DELETE", path), 404, f"DELETE {path} a second time")
        self.assert_points_to(self.id_2, self.url_2)

    def test_get_all(self):
        response = call("GET", "/")
        self.assert_status(response, 200, "GET /")
        listed = listed_items(body_of(response))
        for short_id, url in ((self.id_1, self.url_1), (self.id_2, self.url_2)):
            self.assertTrue(short_id in listed or url in listed,
                            f"GET /: id {short_id!r} is not in the answer {describe(response)}")

    def test_post(self):
        url = "https://en.wikipedia.org/wiki/Docker_(software)"
        self.assert_points_to(self.create(url), url)
        self.assert_status(call("POST", "/", json={"value": ""}), 400, "POST / with an empty URL")
        self.assert_status(call("POST", "/", json={}), 400, "POST / without a URL")

    def test_deletion_all(self):
        self.assert_status(call("DELETE", "/"), 404, "DELETE /")
        response = call("GET", "/")
        self.assert_status(response, 200, "GET / after DELETE /")
        left = listed_items(body_of(response)) & {self.id_1, self.id_2, self.url_1, self.url_2}
        self.assertFalse(left, f"GET / after DELETE / still lists {sorted(left)}")
        self.assert_status(call("GET", f"/{self.id_1}"), 404, f"GET /{self.id_1} after DELETE /")


class TestIdentifiers(GradingTest):
    """Rubric: every new URL gets a unique id that causes no conflicts."""

    def test_ids_are_unique(self):
        run = uuid.uuid4().hex[:8]
        urls = [f"https://example.com/{run}/page-{number}" for number in range(100)]
        ids = [self.create(url) for url in urls]
        self.assertEqual(len(ids), len(set(ids)), "different URLs got the same id")
        for short_id, url in zip(ids, urls):
            self.assert_points_to(short_id, url)
        lengths = sorted(len(short_id) for short_id in ids)
        NOTES.append(f"The 100 new ids are {lengths[0]} to {lengths[-1]} characters long.")

    def test_deletes_cause_no_conflicts(self):
        run = uuid.uuid4().hex[:8]
        urls = {name: f"https://example.com/{run}/{name}" for name in "abcde"}
        ids = {name: self.create(urls[name]) for name in "abc"}
        self.assert_status(call("DELETE", f"/{ids['b']}"), 204, f"DELETE /{ids['b']}")
        for name in "de":
            ids[name] = self.create(urls[name])
            self.assertNotIn(ids[name], (ids["a"], ids["c"]),
                             f"after a delete, a new URL got the id {ids[name]!r} of an existing mapping")
        for name in "acde":
            self.assert_points_to(ids[name], urls[name])


class TestUrlValidation(GradingTest):
    """Rubric: URLs are checked before a mapping is created or updated."""

    def test_invalid_urls_are_rejected(self):
        for url in sorted({row[column] for row in CSV_ROWS for column in URL_COLUMNS}):
            self.create(url)
        short_id = self.create("https://www.uva.nl/")
        invalid = sorted({row["invalid_url"] for row in CSV_ROWS}) + INVALID_URLS
        for value in invalid:
            self.assert_status(call("POST", "/", json={"value": value}), 400, f"POST / with {value!r}")
            response = call("PUT", f"/{short_id}", json={"url": value})
            self.assert_status(response, 400, f"PUT /{short_id} with {value!r}")
        self.assert_points_to(short_id, "https://www.uva.nl/")

    def test_other_input(self):
        for url in OTHER_VALID_URLS:
            self.assert_points_to(self.create(url), url)
        for value in OTHER_INVALID_INPUT:
            self.assert_status(call("POST", "/", json={"value": value}), 400, f"POST / with {value!r}")
        # Without a scheme, "uva.nl" may be rejected, or stored with http:// or https://.
        response = call("POST", "/", json={"value": "uva.nl"})
        if response.status_code != 400:
            self.assert_status(response, 201, "POST / with 'uva.nl'")
            target = target_of(call("GET", f"/{returned_id(response)}"))
            self.assertTrue(re.fullmatch(r"https?://uva\.nl/?", target or ""),
                            f"POST / with 'uva.nl' was stored as {target!r}, so the redirect would be "
                            "relative: reject it, or add http:// or https://")


class GradingResult(unittest.TextTestResult):
    """Keeps the outcome of every test for the points table."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def record(self, test, outcome, detail=""):
        if isinstance(test, unittest.TestCase):
            name = f"{type(test).__name__}.{test._testMethodName}"
        else:  # an error in setUpModule or setUpClass
            name = str(test)
        self.outcomes[name] = (outcome, detail)

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "pass")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "fail", str(err[1]))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", f"{err[0].__name__}: {err[1]}")

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skipped", reason)


def outcome_of(result, test_name):
    """(outcome, detail) of a test, falling back to a failed setUpClass or setUpModule."""
    if test_name in result.outcomes:
        return result.outcomes[test_name]
    class_name = test_name.split(".")[0]
    for name, outcome in result.outcomes.items():
        if name.startswith("setUpClass") and name.endswith(f".{class_name})"):
            return outcome
    for name, outcome in result.outcomes.items():
        if name.startswith("setUpModule"):
            return outcome
    return ("not run", "")


def print_report(result, title, rubric, not_tested):
    """Print the points per rubric line; return True if every line passed."""
    print(f"\n{title}\n")
    print("Points  Rubric line")
    earned = total = not_checked = 0
    for line, points, tests in rubric:
        outcomes = [outcome_of(result, name) for name in tests]
        if all(outcome in ("pass", "skipped") for outcome, _ in outcomes) and \
                any(outcome == "skipped" for outcome, _ in outcomes):
            not_checked += points
            print(f" -/{points:<4} {line}")
        else:
            passed = all(outcome == "pass" for outcome, _ in outcomes)
            earned += points if passed else 0
            total += points
            print(f"{points if passed else 0:>2}/{points:<4} {line}")
        for outcome, detail in dict.fromkeys(outcomes):
            if outcome != "pass":
                detail = " ".join(detail.split())
                print(f"          {outcome}: {detail[:160]}")
    print(f"{earned:>2}/{total:<4} tested by this script")
    if not_checked:
        print(f"{not_checked:>5}   not checked in this run (see above)")
    print()
    print("Not tested by this script:")
    for line, points in not_tested:
        print(f"{points:>5}   {line}")
    if NOTES:
        print("\nNotes:")
        for note in dict.fromkeys(NOTES):
            print(f"  {note}")
    return earned == total


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(description="Grade an Assignment 1 URL shortener over HTTP.")
    parser.add_argument("--url", default=BASE_URL,
                        help="base URL of the service (default: %(default)s, or SHORTENER_BASE_URL)")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every test while it runs")
    args = parser.parse_args()
    BASE_URL = args.url.rstrip("/")

    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2 if args.verbose else 1, resultclass=GradingResult)
    result = runner.run(suite)
    passed = print_report(result, f"Assignment 1, URL shortener at {BASE_URL}", RUBRIC, NOT_TESTED)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
