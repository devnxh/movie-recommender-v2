from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, jsonify, request, session
from werkzeug.security import check_password_hash

from accounts import COOKIE, favorite_sets, init_accounts, transaction


def build_test_app():
    app = Flask(__name__)
    init_accounts(app, lambda ids: [{"id": i, "title": f"Film {i}"} for i in ids if i in (1, 2, 3)])

    @app.route("/watchlist", methods=["GET", "DELETE"])
    def watchlist():
        if request.method == "DELETE":
            session.pop("watchlist", None)
            return "", 204
        return jsonify(session.get("watchlist", []))

    return app


class AccountTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory = temporary.name
        environment = patch.dict(os.environ, {
            "CINEWATCH_DB_PATH": str(Path(directory) / "accounts.sqlite3"),
            "DATABASE_URL": "", "RENDER": "1", "VERCEL": "", "FLASK_SECRET_KEY": "",
            "RENDER_EXTERNAL_URL": "",
        })
        environment.start()
        self.addCleanup(environment.stop)
        self.app = build_test_app()
        self.client = self.app.test_client()
        self.credentials = {"username": "Movie_Fan", "password": "violet quartz river"}

    def register(self):
        response = self.client.post("/api/account/register", json=self.credentials)
        self.assertEqual(response.status_code, 201)
        return response.json["user"]["id"]

    def test_session_rotation_revocation_and_favorite_persistence(self):
        member = self.register()
        original = self.client.get_cookie(COOKIE).value
        self.assertEqual(self.client.put("/api/favorites/1", json={}).json["favorite_ids"], [1])
        self.assertEqual(self.client.put("/api/favorites/2", json={}).json["favorite_ids"], [2, 1])
        self.assertEqual(self.client.put("/api/favorites/1", json={}).json["favorite_ids"], [2, 1])
        self.assertEqual(self.client.put("/api/favorites/99", json={}).status_code, 404)
        login = self.client.post("/api/account/login", json={**self.credentials, "username": "movie_fan"})
        self.assertEqual(login.json["favorite_ids"], [2, 1])
        rotated = self.client.get_cookie(COOKIE).value
        self.assertNotEqual(rotated, original)
        other = self.app.test_client()
        other.set_cookie(COOKIE, original)
        self.assertEqual(other.get("/api/favorites").status_code, 401)
        self.assertEqual(self.client.get("/api/favorites").json["movies"][0]["title"], "Film 2")
        self.assertEqual(self.client.delete("/api/favorites/2", json={}).json["favorite_ids"], [1])
        self.client.post("/api/account/logout", json={})
        other.set_cookie(COOKIE, rotated)
        self.assertIsNone(other.get("/api/account").json["user"])
        new_process = build_test_app().test_client()
        self.assertEqual(new_process.post("/api/account/login", json=self.credentials).json["favorite_ids"], [1])
        with self.app.app_context(), transaction() as query:
            stored = query("SELECT password_hash FROM cw_users WHERE id=?", (member,)).fetchone()[0]
            self.assertTrue(check_password_hash(stored, self.credentials["password"]))
            self.assertEqual(favorite_sets(member), {member: {1}})

    def test_cross_origin_invalid_inputs_and_throttling(self):
        self.assertEqual(self.client.put("/api/favorites/1", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/account/register", data=self.credentials).status_code, 415)
        self.assertEqual(self.client.post("/api/account/register", json=self.credentials,
                                         headers={"Origin": "https://another.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/account/register", json={}).status_code, 400)
        self.register()
        self.assertEqual(self.client.post("/api/account/register", json=self.credentials).status_code, 409)
        for _ in range(12):
            result = self.client.post("/api/account/login", json={"username": "movie_fan", "password": "incorrect"})
            self.assertEqual(result.status_code, 401)
        response = self.client.post("/api/account/login", json=self.credentials)
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response.headers["Retry-After"]), 0)

    def test_concurrent_saves_are_idempotent_and_separate_accounts_are_private(self):
        self.register()
        token = self.client.get_cookie(COOKIE).value

        def put(movie_id):
            client = self.app.test_client()
            client.set_cookie(COOKIE, token)
            return client.put(f"/api/favorites/{movie_id}", json={}).status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            self.assertEqual(list(pool.map(put, [1, 2, 1, 3, 1])), [200] * 5)
        self.assertEqual(set(self.client.get("/api/favorites").json["favorite_ids"]), {1, 2, 3})
        other = self.app.test_client()
        self.assertEqual(other.post("/api/account/register", json={**self.credentials, "username": "another"}).status_code, 201)
        self.assertEqual(other.get("/api/favorites").json["favorite_ids"], [])

    def test_legacy_guest_list_survives_upgrade_and_cannot_sign_in(self):
        legacy = Flask(__name__)
        legacy.secret_key = "cinewatch_secret_key"
        serializer = legacy.session_interface.get_signing_serializer(legacy)
        self.client.set_cookie("session", serializer.dumps({"user_id": 5, "watchlist": [{"id": 1, "title": "Film 1"}]}))
        self.assertEqual(self.client.get("/watchlist").json, [{"id": 1, "title": "Film 1"}])
        self.assertIsNone(self.client.get("/api/account").json["user"])
        with self.client.session_transaction() as upgraded:
            self.assertNotIn("user_id", upgraded)
            self.assertEqual(upgraded["watchlist"], [{"id": 1, "title": "Film 1"}])
        self.assertEqual(self.client.delete("/watchlist").status_code, 204)
        self.assertEqual(self.client.get("/watchlist").json, [])

    def test_unreachable_storage_preserves_guest_sessions(self):
        parent = Path(os.environ["CINEWATCH_DB_PATH"]).parent / "unavailable"
        parent.touch()
        with patch.dict(os.environ, CINEWATCH_DB_PATH=str(parent / "accounts.sqlite3")):
            with self.assertLogs(level="WARNING"):
                client = build_test_app().test_client()
            self.assertEqual(client.get("/api/account").status_code, 503)
            with client.session_transaction() as guest:
                guest["watchlist"] = [{"id": 1, "title": "Film 1"}]
            self.assertEqual(client.get("/watchlist").json, [{"id": 1, "title": "Film 1"}])

    def test_hosted_without_storage_keeps_guest_features_available(self):
        with patch.dict(os.environ, CINEWATCH_DB_PATH=""):
            client = build_test_app().test_client()
            self.assertFalse(client.get("/api/account").json["available"])
            self.assertEqual(client.post("/api/account/register", json=self.credentials).status_code, 503)
            self.assertEqual(client.get("/watchlist").json, [])
