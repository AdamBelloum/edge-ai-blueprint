"""Multi-user checks for Assignment 2: a user cannot see or change another
user's mappings.

These checks are part of the grading script: python test_microservices.py
runs them and counts them in the points for the shortener. To run only them:

    python -m unittest -v test_ownership_isolation

The service URLs come from SHORTENER_BASE_URL and AUTH_BASE_URL, as for
test_microservices.py.
"""
import unittest
import uuid

import test_microservices as grading


class TestOwnershipIsolation(grading.GradingTest):
    """Alice and Bob each manage only their own mappings."""

    @classmethod
    def setUpClass(cls):
        cls.alice = grading.signed_up("alice")
        cls.bob = grading.signed_up("bob")

    def setUp(self):
        run = uuid.uuid4().hex[:8]
        self.alice_url = f"https://example.org/{run}/alice"
        self.bob_url = f"https://example.org/{run}/bob"
        self.alice_id = self.create(self.alice, self.alice_url)

    def tearDown(self):
        self.alice.delete_all()
        self.bob.delete_all()

    def test_list_shows_only_own_mappings(self):
        bob_id = self.create(self.bob, self.bob_url)
        alice_list, bob_list = self.listed_by(self.alice), self.listed_by(self.bob)
        self.assertIn(self.alice_id, alice_list, "GET / as Alice does not list her mapping")
        self.assertIn(bob_id, bob_list, "GET / as Bob does not list his mapping")
        self.assertFalse({self.alice_id, self.alice_url} & bob_list, "GET / as Bob lists Alice's mapping")
        self.assertFalse({bob_id, self.bob_url} & alice_list, "GET / as Alice lists Bob's mapping")

    def test_other_user_cannot_update(self):
        path = f"/{self.alice_id}"
        response = self.bob.request("PUT", path, json={"url": self.bob_url})
        self.assert_status(response, 403, f"PUT {path} by Bob, for Alice's mapping")
        self.assert_points_to(self.alice_id, self.alice_url)
        response = self.alice.request("PUT", path, json={"url": self.bob_url})
        self.assert_status(response, 200, f"PUT {path} by Alice")

    def test_other_user_cannot_delete(self):
        path = f"/{self.alice_id}"
        self.assert_status(self.bob.request("DELETE", path), 403, f"DELETE {path} by Bob, for Alice's mapping")
        self.assert_points_to(self.alice_id, self.alice_url)
        self.assert_status(self.alice.request("DELETE", path), 204, f"DELETE {path} by Alice")

    def test_same_url_keeps_owners_apart(self):
        # Bob shortens the URL that Alice already shortened. He must get a
        # mapping of his own, and Alice must keep hers.
        bob_id = self.create(self.bob, self.alice_url)
        self.assertNotEqual(self.alice_id, bob_id,
                            "Alice and Bob got the same id for the same URL, so one of them "
                            "cannot manage it: each user needs a mapping of their own")
        self.assertIn(self.alice_id, self.listed_by(self.alice),
                      "after Bob shortened the same URL, GET / as Alice no longer lists her mapping")
        path = f"/{self.alice_id}"
        self.assert_status(self.bob.request("DELETE", path), 403,
                           f"DELETE {path} by Bob, after he shortened the same URL")
        self.assert_status(self.alice.request("DELETE", path), 204, f"DELETE {path} by Alice")
        self.assert_points_to(bob_id, self.alice_url)

    def test_delete_all_keeps_other_users_mappings(self):
        bob_id = self.create(self.bob, self.bob_url)
        self.assert_status(self.alice.request("DELETE", "/"), 404, "DELETE / by Alice")
        response = grading.call("GET", f"{grading.SHORTENER_URL}/{self.alice_id}")
        self.assert_status(response, 404, f"GET /{self.alice_id} after Alice's DELETE /")
        self.assert_points_to(bob_id, self.bob_url)
        self.assertIn(bob_id, self.listed_by(self.bob), "Alice's DELETE / removed Bob's mapping")


if __name__ == "__main__":
    unittest.main()
