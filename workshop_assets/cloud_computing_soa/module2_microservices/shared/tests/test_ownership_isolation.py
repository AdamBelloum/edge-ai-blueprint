import time
import unittest
import uuid

import requests


class TestOwnershipIsolation(unittest.TestCase):
    """Verify that one valid user cannot manage another user's URL mappings."""

    base_url = "http://127.0.0.1:5000"
    auth_url = "http://127.0.0.1:5001"

    @classmethod
    def create_and_login(cls, label):
        username = f"{label}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        password = "workshop-test-password"

        create = requests.post(
            f"{cls.auth_url}/users",
            json={"username": username, "password": password},
            timeout=5,
        )
        if create.status_code != 201:
            raise AssertionError(
                f"Could not create {label}: expected 201, got {create.status_code}"
            )

        login = requests.post(
            f"{cls.auth_url}/users/login",
            json={"username": username, "password": password},
            timeout=5,
        )
        if login.status_code != 200:
            raise AssertionError(
                f"Could not log in {label}: expected 200, got {login.status_code}"
            )

        token = login.json().get("token")
        if not token:
            raise AssertionError(f"Login response for {label} did not contain a token.")

        return {"Authorization": f"Bearer {token}"}

    @classmethod
    def setUpClass(cls):
        cls.alice_headers = cls.create_and_login("alice")
        cls.bob_headers = cls.create_and_login("bob")

    @classmethod
    def tearDownClass(cls):
        for headers in (cls.alice_headers, cls.bob_headers):
            try:
                requests.delete(f"{cls.base_url}/", headers=headers, timeout=5)
            except requests.RequestException:
                pass

    def test_valid_second_user_cannot_manage_first_users_mapping(self):
        created = requests.post(
            f"{self.base_url}/",
            headers=self.alice_headers,
            json={"value": "https://example.org/alice-private-resource"},
            timeout=5,
        )
        self.assertEqual(created.status_code, 201)
        mapping_id = created.json().get("id")
        self.assertTrue(mapping_id)

        alice_list = requests.get(
            f"{self.base_url}/", headers=self.alice_headers, timeout=5
        )
        self.assertEqual(alice_list.status_code, 200)
        self.assertIn(mapping_id, alice_list.json().get("keys", []))

        bob_list = requests.get(
            f"{self.base_url}/", headers=self.bob_headers, timeout=5
        )
        self.assertEqual(bob_list.status_code, 200)
        self.assertNotIn(mapping_id, bob_list.json().get("keys", []))

        bob_update = requests.put(
            f"{self.base_url}/{mapping_id}",
            headers=self.bob_headers,
            json={"url": "https://example.org/bob-attempt"},
            timeout=5,
        )
        self.assertEqual(bob_update.status_code, 403)

        bob_delete = requests.delete(
            f"{self.base_url}/{mapping_id}",
            headers=self.bob_headers,
            timeout=5,
        )
        self.assertEqual(bob_delete.status_code, 403)

        alice_delete = requests.delete(
            f"{self.base_url}/{mapping_id}",
            headers=self.alice_headers,
            timeout=5,
        )
        self.assertEqual(alice_delete.status_code, 204)


if __name__ == "__main__":
    unittest.main()
