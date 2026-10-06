import unittest
import requests
import csv
import random
import time
import uuid
from urllib.parse import unquote

class TestApi(unittest.TestCase):
    # modify these to your local server settings if needed
    base_url = "http://127.0.0.1:5000"
    auth_url = "http://127.0.0.1:5001"

    @classmethod
    def populate_variables_from_csv_static(cls):
        with open("read_from.csv", "r") as f:
            reader = csv.reader(f)
            next(reader, None)
            data = [row for row in reader if len(row) >= 5]
            random_row = random.choice(data)
            return random_row

    def populate_variables_from_csv(self):
        return self.populate_variables_from_csv_static()

    @classmethod
    def setUpClass(cls):
        # use a unique username each run so re-running tests does not fail on duplicate registration
        unique_suffix = str(int(time.time())) + "_" + uuid.uuid4().hex[:6]
        cls.test_username = f"test_{unique_suffix}"
        cls.test_password = "test"

        cls.url_create = f"{cls.auth_url}/users"
        cls.url_login = f"{cls.auth_url}/users/login"

        # create user
        response_create = requests.post(
            cls.url_create,
            json={"username": cls.test_username, "password": cls.test_password}
        )

        if response_create.status_code not in {201, 409}:
            raise AssertionError(
                f"Expected status code 201 or 409 when creating user, but got {response_create.status_code}"
            )

        # login
        response_login = requests.post(
            cls.url_login,
            json={"username": cls.test_username, "password": cls.test_password}
        )

        if response_login.status_code != 200:
            raise AssertionError(
                f"Expected status code 200 for login, but got {response_login.status_code}"
            )

        try:
            login_body = response_login.json()
        except Exception:
            raise AssertionError("POST /users/login should return a JSON response body.")

        if not isinstance(login_body, dict):
            raise AssertionError("Login response should be a JSON object.")

        token = None
        for key in ["token", "access_token", "jwt"]:
            if key in login_body and isinstance(login_body[key], str) and login_body[key]:
                token = login_body[key]
                break

        if token is None:
            string_values = [v for v in login_body.values() if isinstance(v, str) and v]
            if len(string_values) == 1:
                token = string_values[0]

        if token is None:
            raise AssertionError("Login should return a token in the response body.")

        cls.token = token
        cls.headers = {"Authorization": f"Bearer {cls.token}"}
        cls.headers_wrong = {"Authorization": "Bearer wrong"}

    def extract_id_from_response(self, response):
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
            "POST / should return a newly created identifier in the response body."
        )

        return returned_id

    def assert_redirect_points_to(self, response, expected_value, fail_prefix):
        location = response.headers.get("Location")
        if location is not None:
            self.assertEqual(
                unquote(location),
                unquote(expected_value),
                f"{fail_prefix}: expected Location header to be {expected_value}, but got {location}"
            )
        else:
            try:
                body = response.json()
            except Exception:
                self.fail(
                    f"{fail_prefix}: response should either include a Location header "
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
                expected_value,
                possible_values,
                f"{fail_prefix}: expected redirected URL {expected_value} to be present in response body."
            )

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
            response = requests.post(url, headers=self.headers, json={"value": str(url_to_shorten)})

            self.assertEqual(
                response.status_code,
                201,
                f"Expected status code 201, but got {response.status_code}"
            )

            return self.extract_id_from_response(response)

        self.id_shortened_url_1 = do_post(self.url_to_shorten_1)
        self.id_shortened_url_2 = do_post(self.url_to_shorten_2)

    def tearDown(self):
        url = f"{self.base_url}/"
        try:
            requests.delete(url, headers=self.headers)
        except Exception:
            pass

    def test_get_request_with_id_success(self):
        id_ = self.id_shortened_url_1
        expected_value = self.url_to_shorten_1

        url = f"{self.base_url}/{id_}"
        response = requests.get(url, allow_redirects=False)

        self.assertEqual(
            response.status_code,
            301,
            f"Expected status code 301, but got {response.status_code}"
        )

        self.assert_redirect_points_to(
            response,
            expected_value,
            "GET /<id> with 301"
        )

    def test_get_request_with_id_expect_404(self):
        id_ = "Unseen_id"
        url = f"{self.base_url}/{id_}"
        response = requests.get(url, allow_redirects=False)

        self.assertEqual(
            response.status_code,
            404,
            f"Expected status code 404, but got {response.status_code}"
        )

    def test_put_id(self):
        id_ = self.id_shortened_url_1
        url_after_update = self.url_after_update
        not_existing_id = self.not_existing_id
        invalid_url = self.invalid_url

        # wrong token -> should be rejected with 403
        url = f"{self.base_url}/{id_}"
        response = requests.put(url, headers=self.headers_wrong, json={"url": url_after_update})
        self.assertEqual(
            response.status_code,
            403,
            f"Expected status code 403, but got {response.status_code}"
        )

        # successful update
        response = requests.put(url, headers=self.headers, json={"url": url_after_update})
        self.assertEqual(
            response.status_code,
            200,
            f"Expected status code 200, but got {response.status_code}"
        )

        # GET again to verify the update was successful
        response = requests.get(url, allow_redirects=False)
        self.assertEqual(
            response.status_code,
            301,
            f"Expected status code 301 after update, but got {response.status_code}"
        )

        self.assert_redirect_points_to(
            response,
            url_after_update,
            "Updated GET /<id>"
        )

        # Invalid URL -> 400
        response = requests.put(url, headers=self.headers, json={"url": invalid_url})
        self.assertEqual(
            response.status_code,
            400,
            f"Expected status code 400, but got {response.status_code}"
        )

        # Non-existent id -> 404
        url = f"{self.base_url}/{not_existing_id}"
        response = requests.put(url, headers=self.headers, json={"url": url_after_update})
        self.assertEqual(
            response.status_code,
            404,
            f"Expected status code 404, but got {response.status_code}"
        )

    def test_deletion_id(self):
        id_ = self.id_shortened_url_1
        url = f"{self.base_url}/{id_}"

        response = requests.delete(url, headers=self.headers)
        self.assertEqual(
            response.status_code,
            204,
            f"Expected status code 204, but got {response.status_code}"
        )

        response = requests.delete(url, headers=self.headers_wrong)
        self.assertEqual(
            response.status_code,
            403,
            f"Expected status code 403, but got {response.status_code}"
        )

        response = requests.delete(url, headers=self.headers)
        self.assertEqual(
            response.status_code,
            404,
            f"Expected status code 404, but got {response.status_code}"
        )

    def test_get_all(self):
        url = f"{self.base_url}/"

        response = requests.get(url, headers=self.headers_wrong)
        self.assertEqual(
            response.status_code,
            403,
            f"Expected status code 403, but got {response.status_code}"
        )

        response = requests.get(url, headers=self.headers)
        self.assertEqual(
            response.status_code,
            200,
            f"Expected status code 200, but got {response.status_code}"
        )

        try:
            body = response.json()
        except Exception:
            self.fail("GET / should return a JSON response body.")

        self.assertIsInstance(body, dict, "GET / response should be a JSON object.")

        list_values = [v for v in body.values() if isinstance(v, list)]
        self.assertTrue(
            len(list_values) >= 1,
            "GET / should return at least one list (e.g. keys, URLs, or records)."
        )

    def test_post(self):
        url_to_shorten = "https://en.wikipedia.org/wiki/Docker_(software)"
        url = f"{self.base_url}/"

        response = requests.post(url, headers=self.headers_wrong, json={"value": str(url_to_shorten)})
        self.assertEqual(
            response.status_code,
            403,
            f"Expected status code 403, but got {response.status_code}"
        )

        response = requests.post(url, headers=self.headers, json={"value": str(url_to_shorten)})
        self.assertEqual(
            response.status_code,
            201,
            f"Expected status code 201, but got {response.status_code}"
        )

        returned_id = self.extract_id_from_response(response)

        get_url = f"{self.base_url}/{returned_id}"
        response = requests.get(get_url, allow_redirects=False)
        self.assertEqual(
            response.status_code,
            301,
            f"Expected status code 301, but got {response.status_code}"
        )

        self.assert_redirect_points_to(
            response,
            url_to_shorten,
            "GET /<id> after POST"
        )

        response = requests.post(url, headers=self.headers, json={"value": ""})
        self.assertEqual(
            response.status_code,
            400,
            f"Expected status code 400, but got {response.status_code}"
        )

    def test_deletion_all(self):
        url = f"{self.base_url}/"

        response = requests.delete(url, headers=self.headers_wrong)
        self.assertEqual(
            response.status_code,
            403,
            f"Expected status code 403, but got {response.status_code}"
        )

        response = requests.delete(url, headers=self.headers)
        self.assertEqual(
            response.status_code,
            404,
            f"Expected status code 404, but got {response.status_code}"
        )

        # GET again to check the service is in "empty" state for this user
        response = requests.get(url, headers=self.headers)
        self.assertEqual(
            response.status_code,
            200,
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

        self.assertTrue(
            any(len(v) == 0 for v in list_values),
            "After DELETE /, at least one returned collection should be empty."
        )


if __name__ == "__main__":
    unittest.main()