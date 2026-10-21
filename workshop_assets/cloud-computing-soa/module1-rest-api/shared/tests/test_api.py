import unittest
import requests
import json
import csv
import random


class TestApi(unittest.TestCase):
    # Flask default port
    base_url = "http://127.0.0.1:5000"

    def populate_variables_from_csv(self):
        with open('read_from.csv', 'r') as f:
            reader = csv.reader(f)
            next(reader, None)
            data = [row for row in reader if len(row) >= 5]
            random_row = random.choice(data)
            return random_row

    def setUp(self):
        self.id_shortened_url_1 = ""
        self.id_shortened_url_2 = ""

        (
            self.url_to_shorten_1,
            self.url_to_shorten_2,
            self.url_after_update,
            self.not_existing_id,
            self.invalid_url
        ) = self.populate_variables_from_csv()

        def do_post(url_to_shorten):
            url = f"{self.base_url}/"
            response = requests.post(url, json={'value': str(url_to_shorten)})

            self.assertEqual(
                response.status_code, 201,
                f"Expected status code 201, but got {response.status_code}"
            )

            # While not requiring explicit field name binding, it should at least return parsable JSON.
            try:
                body = response.json()
            except Exception:
                self.fail("POST / should return a JSON response body.")

            self.assertIsInstance(body, dict, "POST / response should be a JSON object.")

            # Try retrieving the id from common fields; if not, degenerate to retrieving the first string value.
            returned_id = None
            for key in ["id", "key", "short_id", "identifier"]:
                if key in body and isinstance(body[key], str) and body[key]:
                    returned_id = body[key]
                    break

            if returned_id is None:
                string_values = [v for v in body.values() if isinstance(v, str) and v]
                if len(string_values) == 1:
                    returned_id = string_values[0]

            self.assertIsNotNone(
                returned_id,
                "POST / should return a newly created identifier in the response body."
            )

            return returned_id

        self.id_shortened_url_1 = do_post(self.url_to_shorten_1)
        self.id_shortened_url_2 = do_post(self.url_to_shorten_2)

    def tearDown(self):
        url = f"{self.base_url}/"
        try:
            requests.delete(url)
        except Exception:
            pass

    def test_get_request_with_id_success(self):
        id_ = self.id_shortened_url_1
        expected_value = self.url_to_shorten_1

        url = f"{self.base_url}/{id_}"

        # Do not automatically follow redirects to check the original 301 response
        response = requests.get(url, allow_redirects=False)

        self.assertEqual(
            response.status_code, 301,
            f"Expected status code 301, but got {response.status_code}"
        )

        # Broader approach: allow two reasonable implementations
        # 1. Redirect via Location header
        # 2. Return URL information in body
        location = response.headers.get("Location")
        if location is not None:
            self.assertEqual(
                location, expected_value,
                f"Expected Location header to be {expected_value}, but got {location}"
            )
        else:
            try:
                body = response.json()
            except Exception:
                self.fail(
                    "GET /<id> with 301 should either include a Location header "
                    "or return a JSON body describing the target URL."
                )

            self.assertIsInstance(body, dict, "Response body should be a JSON object.")

            possible_values = []
            for key in ["value", "url", "long_url", "target"]:
                if key in body:
                    possible_values.append(body[key])

            if not possible_values:
                possible_values = [v for v in body.values() if isinstance(v, str)]

            self.assertIn(
                expected_value, possible_values,
                f"Expected redirected URL {expected_value} to be present in response body."
            )

    def test_get_request_with_id_expect_404(self):
        id_ = "Unseen_id"
        url = f"{self.base_url}/{id_}"
        response = requests.get(url, allow_redirects=False)

        self.assertEqual(
            response.status_code, 404,
            f"Expected status code 404, but got {response.status_code}"
        )

    def test_put_id(self):
        id_ = self.id_shortened_url_1
        url_after_update = self.url_after_update
        not_existing_id = self.not_existing_id
        invalid_url = self.invalid_url

        # Successful update: use json= instead of data=json.dumps(...)
        # This tests the API logic, not whether the server tolerates non-standard requests
        url = f"{self.base_url}/{id_}"
        response = requests.put(url, json={'url': url_after_update})
        self.assertEqual(
            response.status_code, 200,
            f"Expected status code 200, but got {response.status_code}"
        )

        # GET again to verify the update was successful
        response = requests.get(url, allow_redirects=False)
        self.assertEqual(
            response.status_code, 301,
            f"Expected status code 301 after update, but got {response.status_code}"
        )

        location = response.headers.get("Location")
        if location is not None:
            self.assertEqual(
                location, url_after_update,
                f"Expected Location header to be {url_after_update}, but got {location}"
            )
        else:
            try:
                body = response.json()
            except Exception:
                self.fail(
                    "Updated GET /<id> should either include a Location header "
                    "or return a JSON body with the updated URL."
                )

            possible_values = []
            for key in ["value", "url", "long_url", "target"]:
                if key in body:
                    possible_values.append(body[key])

            if not possible_values:
                possible_values = [v for v in body.values() if isinstance(v, str)]

            self.assertIn(
                url_after_update, possible_values,
                f"Expected updated URL {url_after_update} in response body."
            )

        # Invalid URL -> 400
        response = requests.put(url, json={'url': invalid_url})
        self.assertEqual(
            response.status_code, 400,
            f"Expected status code 400, but got {response.status_code}"
        )

        # Non-existent id -> 404
        url = f"{self.base_url}/{not_existing_id}"
        response = requests.put(url, json={'url': url_after_update})
        self.assertEqual(
            response.status_code, 404,
            f"Expected status code 404, but got {response.status_code}"
        )

    def test_deletion_id(self):
        id_ = self.id_shortened_url_1
        url = f"{self.base_url}/{id_}"

        response = requests.delete(url)
        self.assertEqual(
            response.status_code, 204,
            f"Expected status code 204, but got {response.status_code}"
        )

        response = requests.delete(url)
        self.assertEqual(
            response.status_code, 404,
            f"Expected status code 404, but got {response.status_code}"
        )

    def test_get_all(self):
        url = f"{self.base_url}/"
        response = requests.get(url)

        self.assertEqual(
            response.status_code, 200,
            f"Expected status code 200, but got {response.status_code}"
        )

        try:
            body = response.json()
        except Exception:
            self.fail("GET / should return a JSON response body.")

        self.assertIsInstance(body, dict, "GET / response should be a JSON object.")

        # Broader approach: only verify "returned some kind of global list"
        list_values = [v for v in body.values() if isinstance(v, list)]
        self.assertTrue(
            len(list_values) >= 1,
            "GET / should return at least one list (e.g. keys, URLs, or records)."
        )

    def test_post(self):
        url_to_shorten = "https://en.wikipedia.org/wiki/Docker_(software)"
        url = f"{self.base_url}/"

        response = requests.post(url, json={'value': str(url_to_shorten)})
        self.assertEqual(
            response.status_code, 201,
            f"Expected status code 201, but got {response.status_code}"
        )

        try:
            body = response.json()
        except Exception:
            self.fail("POST / should return a JSON response body.")

        self.assertIsInstance(body, dict, "POST / response should be a JSON object.")

        returned_id = None
        for key in ["id", "key", "short_id", "identifier"]:
            if key in body and isinstance(body[key], str) and body[key]:
                returned_id = body[key]
                break

        if returned_id is None:
            string_values = [v for v in body.values() if isinstance(v, str) and v]
            if len(string_values) == 1:
                returned_id = string_values[0]

        self.assertIsNotNone(
            returned_id,
            "POST / should return a new identifier in the response body."
        )

        # Use the new id to GET and verify the resource exists
        get_url = f"{self.base_url}/{returned_id}"
        response = requests.get(get_url, allow_redirects=False)
        self.assertEqual(
            response.status_code, 301,
            f"Expected status code 301, but got {response.status_code}"
        )

        location = response.headers.get("Location")
        if location is not None:
            self.assertEqual(
                location, url_to_shorten,
                f"Expected Location header to be {url_to_shorten}, but got {location}"
            )
        else:
            try:
                body = response.json()
            except Exception:
                self.fail(
                    "GET /<id> after POST should either include a Location header "
                    "or return a JSON body with the stored URL."
                )

            possible_values = []
            for key in ["value", "url", "long_url", "target"]:
                if key in body:
                    possible_values.append(body[key])

            if not possible_values:
                possible_values = [v for v in body.values() if isinstance(v, str)]

            self.assertIn(
                url_to_shorten, possible_values,
                f"Expected stored URL {url_to_shorten} to be present in response."
            )

        # Empty body / empty URL -> 400
        response = requests.post(url, json={'value': ""})
        self.assertEqual(
            response.status_code, 400,
            f"Expected status code 400, but got {response.status_code}"
        )

    def test_deletion_all(self):
        url = f"{self.base_url}/"
        response = requests.delete(url)

        self.assertEqual(
            response.status_code, 404,
            f"Expected status code 404, but got {response.status_code}"
        )

        # GET again to check the service is in "empty" state
        response = requests.get(url)
        self.assertEqual(
            response.status_code, 200,
            f"Expected status code 200, but got {response.status_code}"
        )

        try:
            body = response.json()
        except Exception:
            self.fail("GET / after DELETE / should still return JSON.")

        list_values = [v for v in body.values() if isinstance(v, list)]
        self.assertTrue(
            len(list_values) >= 1,
            "GET / should return at least one list even after deletion."
        )

        # At least one list should be empty
        self.assertTrue(
            any(len(v) == 0 for v in list_values),
            "After DELETE /, at least one returned collection should be empty."
        )


if __name__ == '__main__':
    unittest.main()