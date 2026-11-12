import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

import database
import server
import config
import security
import tournament


class TournamentTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        root = Path(self.folder.name)
        uploads = root / "uploads"
        uploads.mkdir()
        security.attempts.clear()
        self.database_patch = patch.object(config, "DATABASE_PATH", root / "test.sqlite3")
        self.upload_patch = patch.object(config, "UPLOADS_PATH", uploads)
        self.key_patch = patch.object(config, "ORGANIZER_KEY", "test-key")
        self.database_patch.start()
        self.upload_patch.start()
        self.key_patch.start()
        self.client = TestClient(server.app, base_url="http://localhost")
        self.client.__enter__()
        self.headers = {"X-Organizer-Key": "test-key"}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.key_patch.stop()
        self.upload_patch.stop()
        self.database_patch.stop()
        self.folder.cleanup()

    def register(self, name):
        return self.client.post("/api/teams", data={"team_name": name, "players": "Alex, Sam"})

    def fill_tournament(self):
        for number in range(16):
            response = self.register("Team " + str(number + 1))
            self.assertEqual(response.status_code, 201, response.text)

    def state(self):
        return self.client.get("/api/tournament").json()

    def match(self, match_id):
        for match in self.state()["matches"]:
            if match["match_id"] == match_id:
                return match
        self.fail("Match not found")

    def win(self, match_id, team_id):
        match = self.match(match_id)
        if not match["in_progress"] and match["winner_team_id"] is None:
            self.start_match(match_id)
        response = self.client.put(
            "/api/matches/" + str(match_id) + "/winner",
            json={"team_id": team_id}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 200, response.text)

    def start(self, close_registration=True):
        response = self.client.post("/api/admin/start", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        if close_registration:
            self.close_registration()

    def close_registration(self):
        response = self.client.post("/api/admin/close-registration", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    def start_match(self, match_id):
        response = self.client.post("/api/admin/matches/" + str(match_id) + "/start", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)

    def test_registration_and_persistence(self):
        response = self.register("Crafty Cups")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["image_url"], "/default-team.svg")
        self.assertEqual(self.match(8)["team1_id"], response.json()["team_id"])
        self.assertEqual(self.register("crafty cups").status_code, 409)
        self.assertEqual(self.register("   ").status_code, 400)
        database.create_tables()
        self.assertEqual(len(self.state()["teams"]), 1)

    def test_capacity(self):
        self.fill_tournament()
        self.assertEqual(self.register("One too many").status_code, 409)
        self.assertEqual(len(self.state()["teams"]), 16)
        self.assertEqual(len(self.state()["matches"]), 16)

    def test_images(self):
        image_bytes = BytesIO()
        Image.new("RGB", (400, 300), "green").save(image_bytes, format="PNG")
        response = self.client.post(
            "/api/teams", data={"team_name": "Picture team", "players": "Sam"},
            files={"image": ("team.png", image_bytes.getvalue(), "image/png")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        stored_path = config.UPLOADS_PATH / Path(response.json()["image_url"]).name
        with Image.open(stored_path) as image:
            self.assertEqual(image.size, (256, 192))
        response = self.client.post(
            "/api/teams", data={"team_name": "Invalid", "players": "Sam"},
            files={"image": ("fake.png", b"not an image", "image/png")},
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            "/api/teams", data={"team_name": "Too big", "players": "Sam"},
            files={"image": ("huge.png", b"x" * (config.IMAGE_MAX_BYTES + 1), "image/png")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.state()["teams"]), 1)

    def test_result_access_and_readiness(self):
        self.register("Team one")
        self.register("Team two")
        url = "/api/matches/8/winner"
        self.assertEqual(self.client.put(url, json={"team_id": 1}).status_code, 403)
        self.assertEqual(self.client.put(url, json={"team_id": 1}, headers=self.headers).status_code, 409)
        for number in range(14):
            self.assertEqual(self.register("Extra " + str(number)).status_code, 201)
        self.start()
        self.assertEqual(self.client.put(url, json={"team_id": 16}, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.put("/api/matches/1/winner", json={"team_id": 1}, headers=self.headers).status_code, 409)

    def test_full_bracket_and_correcting_results(self):
        self.fill_tournament()
        self.start()
        for match_id in [8, 9, 10, 11, 12, 13, 14, 15, 4, 5, 6, 7, 2, 3, 1, 16]:
            self.win(match_id, self.match(match_id)["team1_id"])
        self.assertEqual(self.match(1)["winner_team_id"], 1)
        left_runner_up = self.match(2)["team2_id"]
        right_runner_up = self.match(3)["team2_id"]
        self.assertEqual(self.match(16)["team1_id"], left_runner_up)
        self.assertEqual(self.match(16)["team2_id"], right_runner_up)
        self.assertEqual(self.match(16)["winner_team_id"], left_runner_up)
        unaffected_finalist = self.match(1)["team2_id"]

        self.win(8, 1)
        self.assertEqual(self.match(1)["winner_team_id"], 1)
        self.win(8, 2)
        self.assertEqual(self.match(4)["team1_id"], 2)
        self.assertIsNone(self.match(4)["winner_team_id"])
        self.assertIsNone(self.match(2)["team1_id"])
        self.assertIsNone(self.match(1)["winner_team_id"])
        self.assertIsNone(self.match(1)["team1_id"])
        self.assertEqual(self.match(1)["team2_id"], unaffected_finalist)
        self.assertIsNone(self.match(16)["team1_id"])
        self.assertIsNone(self.match(16)["winner_team_id"])
        self.assertEqual(self.match(16)["team2_id"], right_runner_up)
        self.assertEqual(self.match(3)["winner_team_id"], unaffected_finalist)

    def test_optional_second_player(self):
        self.assertEqual(self.register("Solo team").status_code, 201)
        response = self.client.post("/api/teams", data={"team_name": "Duo team", "players": "Alex", "second_player": "Sam"})
        self.assertEqual(response.status_code, 201)
        data = self.client.get("/api/admin/tournament", headers=self.headers).json()
        self.assertEqual(data["teams"][0]["second_player"], "")
        self.assertEqual(data["teams"][1]["players"], "Alex")
        self.assertEqual(data["teams"][1]["second_player"], "Sam")
        self.assertNotIn("second_player", self.state()["teams"][1])

    def test_odd_and_even_team_counts_finish(self):
        for count in range(2, 17):
            with self.subTest(teams=count):
                connection = database.connect_database()
                with connection:
                    connection.execute("DELETE FROM Matches")
                    connection.execute("DELETE FROM Team")
                    connection.execute("DELETE FROM ResultHistory")
                    connection.execute("UPDATE TournamentState SET started = 0, registration_closed = 0 WHERE id = 1")
                    connection.execute("DELETE FROM Waitlist")
                connection.close()
                database.create_tables()
                security.attempts.clear()
                for number in range(count):
                    self.assertEqual(self.register("Team " + str(number + 1)).status_code, 201)
                self.start()
                self.assertEqual(self.register("Late team").status_code, 409)
                self.assertEqual(len(self.state()["matches"]), 16)
                played = 0
                while True:
                    ready = []
                    for match in self.state()["matches"]:
                        if match["status"] == "ready":
                            ready.append(match)
                    if not ready:
                        break
                    for match in ready:
                        self.win(match["match_id"], match["team1_id"])
                        if match["match_id"] != 16:
                            played += 1
                self.assertEqual(played, count - 1)
                self.assertIsNotNone(self.match(1)["winner_team_id"])
                if count >= 4:
                    self.assertEqual(self.match(16)["status"], "finished")
                if count == 3:
                    self.assertEqual(self.match(16)["status"], "bye")
                if count == 2:
                    self.assertIsNone(self.match(16)["winner_team_id"])
                    self.assertIsNotNone(self.state()["runner_up_id"])
                    self.assertNotEqual(self.state()["runner_up_id"], self.match(1)["winner_team_id"])

    def test_start_clear_undo_and_reopen(self):
        self.assertEqual(self.client.post("/api/admin/start", headers=self.headers).status_code, 409)
        for number in range(5):
            self.assertEqual(self.register("Team " + str(number)).status_code, 201)
        preview = self.state()
        self.assertEqual(self.client.post("/api/admin/start").status_code, 403)
        self.start()
        ready = None
        for match in self.state()["matches"]:
            if match["status"] == "ready":
                ready = match
                break
        before_match = self.state()
        self.start_match(ready["match_id"])
        playing = self.state()
        self.win(ready["match_id"], ready["team1_id"])
        after_result = self.state()
        url = "/api/matches/" + str(ready["match_id"]) + "/winner"
        self.assertEqual(self.client.delete(url, headers=self.headers).status_code, 200)
        self.assertEqual(self.state(), before_match)
        self.assertEqual(self.client.post("/api/admin/undo", headers=self.headers).status_code, 200)
        self.assertEqual(self.state(), after_result)
        self.assertEqual(self.client.post("/api/admin/undo", headers=self.headers).status_code, 200)
        self.assertEqual(self.state(), playing)
        self.assertEqual(self.client.post("/api/admin/undo", headers=self.headers).status_code, 200)
        self.assertEqual(self.state(), before_match)
        self.assertEqual(self.client.post("/api/admin/undo", headers=self.headers).status_code, 200)
        self.assertTrue(self.state()["started"])
        self.assertFalse(self.state()["registration_closed"])
        self.assertEqual(self.client.post("/api/admin/undo", headers=self.headers).status_code, 200)
        self.assertEqual(self.state(), preview)
        self.start()
        started = self.state()
        self.assertEqual(self.client.post("/api/admin/reopen", headers=self.headers).status_code, 200)
        self.assertFalse(self.state()["started"])
        self.assertEqual(self.client.post("/api/admin/undo", headers=self.headers).status_code, 200)
        self.assertEqual(self.state(), started)

    def test_late_arrivals_keep_matches_and_results(self):
        for name in ["Early A", "Early B", "Early C", "Early D"]:
            self.assertEqual(self.register(name).status_code, 201)
        self.start(close_registration=False)
        self.assertFalse(self.state()["registration_closed"])
        self.assertIsNone(self.match(1)["winner_team_id"])
        self.start_match(8)
        locked = self.match(8)
        self.assertEqual(self.register("Late E").status_code, 201)
        self.assertEqual(self.match(8), locked)
        self.win(8, locked["team1_id"])
        finished = self.match(8)
        self.assertEqual(self.register("Late F").status_code, 201)
        self.assertEqual(self.match(8), finished)
        self.assertEqual(len(self.state()["teams"]), 6)
        self.assertEqual(self.match(10)["team1_id"], 5)
        self.assertEqual(self.match(10)["team2_id"], 6)
        self.assertIsNone(self.match(12)["winner_team_id"])
        self.assertIsNone(self.match(1)["winner_team_id"])

    def test_previous_database_migrates_without_losing_results(self):
        legacy_path = Path(self.folder.name) / "legacy.sqlite3"
        with patch.object(config, "DATABASE_PATH", legacy_path):
            connection = database.connect_database()
            connection.executescript("""
                CREATE TABLE Team (team_id INTEGER PRIMARY KEY, team_name TEXT NOT NULL UNIQUE,
                    players TEXT NOT NULL, second_player TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE Matches (match_id INTEGER PRIMARY KEY, round_number INTEGER NOT NULL,
                    team1_id INTEGER, team2_id INTEGER, winner_team_id INTEGER);
                CREATE TABLE TournamentState (id INTEGER PRIMARY KEY, started INTEGER NOT NULL);
                INSERT INTO TournamentState VALUES (1, 1);
                CREATE TABLE ResultHistory (history_id INTEGER PRIMARY KEY, description TEXT NOT NULL,
                    matches_json TEXT NOT NULL, started INTEGER NOT NULL);
                INSERT INTO Team (team_id, team_name, players, image_url)
                    VALUES (1, 'Existing A', 'Alex', '/default-team.svg');
                INSERT INTO Team (team_id, team_name, players, image_url)
                    VALUES (2, 'Existing B', 'Sam', '/default-team.svg');
            """)
            for match in tournament.match_definitions():
                connection.execute("INSERT INTO Matches (match_id, round_number) VALUES (?, ?)", (match["match_id"], match["round_number"]))
            connection.execute("UPDATE Matches SET team1_id = 1, team2_id = 2, winner_team_id = 1 WHERE match_id = 8")
            connection.commit()
            connection.close()
            database.create_tables()
            migrated = self.state()
            self.assertTrue(migrated["started"])
            self.assertTrue(migrated["registration_closed"])
            self.assertEqual(migrated["teams"][0]["team_name"], "Existing A")
            self.assertEqual(self.match(8)["winner_team_id"], 1)
            self.assertEqual(self.match(8)["in_progress"], 0)

    def test_cutoff_waiting_list_and_protected_match_start(self):
        for name in ["A", "B", "C"]:
            self.register(name)
        self.start(close_registration=False)
        self.assertEqual(self.match(12)["team1_id"], 3)
        self.assertIsNone(self.match(12)["winner_team_id"])
        self.assertEqual(self.client.post("/api/admin/matches/8/start").status_code, 403)
        self.assertEqual(self.client.put("/api/matches/8/winner", json={"team_id": 1}, headers=self.headers).status_code, 409)
        self.close_registration()
        self.assertEqual(self.match(12)["status"], "bye")
        self.assertEqual(self.register("Too late").status_code, 409)
        before_matches = self.state()["matches"]
        response = self.client.post("/api/waitlist", data={"team_name": "Late team", "players": "Alex", "second_player": "Sam"})
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(self.state()["matches"], before_matches)
        self.assertEqual(len(self.state()["teams"]), 3)
        self.assertNotIn("waiting_list", self.state())
        admin = self.client.get("/api/admin/tournament", headers=self.headers).json()
        self.assertEqual(admin["waiting_list"][0]["second_player"], "Sam")
        self.assertEqual(self.client.post("/api/waitlist", data={"team_name": "Late team", "players": "Alex"}).status_code, 409)

    def test_waiting_replacement_and_undo(self):
        for number in range(4):
            self.register("Team " + str(number))
        self.start()
        response = self.client.post("/api/waitlist", data={"team_name": "Replacement", "players": "New player"})
        self.assertEqual(response.status_code, 201)
        waiting_id = response.json()["waiting_id"]
        before = self.state()
        url = "/api/admin/teams/1/replace"
        self.assertEqual(self.client.post(url, json={"waiting_id": waiting_id}).status_code, 403)
        response = self.client.post(url, json={"waiting_id": waiting_id}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.state()["matches"], before["matches"])
        self.assertEqual(self.state()["teams"][0]["team_name"], "Replacement")
        self.assertEqual(self.client.post("/api/admin/undo", headers=self.headers).status_code, 200)
        self.assertEqual(self.state(), before)
        self.start_match(8)
        self.assertEqual(self.client.post(url, json={"waiting_id": waiting_id}, headers=self.headers).status_code, 409)
        self.win(8, 1)
        self.assertEqual(self.client.post(url, json={"waiting_id": waiting_id}, headers=self.headers).status_code, 409)

    def test_later_rounds_wait_for_cutoff(self):
        self.fill_tournament()
        self.start(close_registration=False)
        self.win(8, self.match(8)["team1_id"])
        self.win(9, self.match(9)["team1_id"])
        self.assertIsNotNone(self.match(4)["team1_id"])
        self.assertIsNotNone(self.match(4)["team2_id"])
        self.assertEqual(self.client.post("/api/admin/matches/4/start", headers=self.headers).status_code, 409)
        self.close_registration()
        self.start_match(4)

    def test_waitlist_is_unavailable_when_regular_places_exist(self):
        response = self.client.post("/api/waitlist", data={"team_name": "Too early", "players": "Alex"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.register("Normal registration").status_code, 201)

    def test_pages(self):
        if not config.STATIC_PATH.exists():
            self.skipTest("Build the frontend first with npm run build")
        for url in ["/", "/register.html", "/rules.html", "/default-team.svg", "/admin", "/admin/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/api/not-a-route").status_code, 404)

    def test_private_admin_data_and_public_bracket(self):
        self.register("Test team")
        self.assertNotIn("players", self.state()["teams"][0])
        self.assertEqual(self.client.get("/api/admin/tournament").status_code, 403)
        response = self.client.get("/api/admin/tournament", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["teams"][0]["players"], "Alex, Sam")
        self.assertNotIn("Organizer controls", self.client.get("/").text)
        for url in ["/docs", "/openapi.json"]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_security_headers_hosts_and_origins(self):
        response = self.client.get("/api/tournament")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("frame-ancestors 'none'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.get("/admin").headers["x-robots-tag"], "noindex, nofollow")
        self.assertEqual(self.client.get("/", headers={"Host": "evil.example"}).status_code, 400)
        response = self.client.post("/api/teams", data={"team_name": "Bad origin", "players": "Sam"}, headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self.state()["teams"]), 0)

    def test_body_limits_including_chunked_requests(self):
        with patch.object(config, "REQUEST_MAX_BYTES", 100):
            response = self.client.post("/api/teams", content=b"x" * 101)
            self.assertEqual(response.status_code, 413)
            def chunks():
                yield b"x" * 60
                yield b"x" * 60
            response = self.client.post("/api/teams", content=chunks())
            self.assertEqual(response.status_code, 413)

    def test_lightweight_rate_limits(self):
        with patch.object(config, "REGISTRATION_RATE_LIMIT", 2):
            self.assertEqual(self.register("First").status_code, 201)
            self.assertEqual(self.register("Second").status_code, 201)
            response = self.register("Third")
            self.assertEqual(response.status_code, 429)
            self.assertIn("retry-after", response.headers)
        with patch.object(config, "ADMIN_RATE_LIMIT", 2):
            self.assertEqual(self.client.get("/api/admin/tournament").status_code, 403)
            self.assertEqual(self.client.get("/api/admin/tournament").status_code, 403)
            self.assertEqual(self.client.get("/api/admin/tournament").status_code, 429)
            self.assertEqual(self.client.get("/api/admin/tournament", headers=self.headers).status_code, 200)
        with patch.object(config, "ORGANIZER_KEY", ""):
            self.assertEqual(self.client.get("/api/admin/tournament", headers=self.headers).status_code, 503)


if __name__ == "__main__":
    unittest.main()
