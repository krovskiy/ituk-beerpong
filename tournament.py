import json

import config


# Match IDs form a binary tree: a match advances to match_id // 2.
# These are structural positions, not settings for a particular event.
FINAL_MATCH = 1
LEFT_SEMIFINAL = 2
RIGHT_SEMIFINAL = 3
FIRST_OPENING_MATCH = config.TEAM_CAPACITY // 2
THIRD_PLACE_MATCH = config.TEAM_CAPACITY
ROUND_COUNT = config.TEAM_CAPACITY.bit_length() - 1


def round_name(round_number):
    teams_remaining = config.TEAM_CAPACITY // (2 ** (round_number - 1))
    if teams_remaining == 2:
        return "Final"
    if teams_remaining == 4:
        return "Semifinals"
    if teams_remaining == 8:
        return "Quarterfinals"
    return "Round of " + str(teams_remaining)


def match_definitions():
    matches = []
    display_number = 1
    for round_number in range(1, ROUND_COUNT + 1):
        first_match = config.TEAM_CAPACITY // (2 ** round_number)
        for match_id in range(first_match, first_match * 2):
            matches.append({
                "match_id": match_id,
                "round_number": round_number,
                "display_number": display_number,
            })
            display_number += 1
    matches.append({
        "match_id": THIRD_PLACE_MATCH,
        "round_number": ROUND_COUNT,
        "display_number": display_number,
    })
    return matches


def public_settings():
    rounds = []
    for number in range(1, ROUND_COUNT + 1):
        rounds.append({"number": number, "name": round_name(number)})
    return {
        "capacity": config.TEAM_CAPACITY,
        "rounds": rounds,
        "first_opening_match": FIRST_OPENING_MATCH,
        "final_match": FINAL_MATCH,
        "third_place_match": THIRD_PLACE_MATCH,
        "default_image": config.DEFAULT_TEAM_IMAGE,
        "image_max_bytes": config.IMAGE_MAX_BYTES,
        "image_formats": config.IMAGE_FORMATS,
        "team_name_max_length": config.TEAM_NAME_MAX_LENGTH,
        "players_max_length": config.PLAYERS_MAX_LENGTH,
        "refresh_interval_ms": config.REFRESH_INTERVAL_MS,
    }


def is_started(database):
    row = database.execute("SELECT started FROM TournamentState WHERE id = 1").fetchone()
    return bool(row["started"])


def is_registration_closed(database):
    row = database.execute("SELECT registration_closed FROM TournamentState WHERE id = 1").fetchone()
    return bool(row["registration_closed"])


def available_slots(database):
    # Fill a waiting team's opponent first, then use a completely empty match.
    # Never touch a match which has started or already has a result.
    opponents = []
    empty_matches = []
    rows = database.execute(
        "SELECT * FROM Matches WHERE round_number = 1 AND in_progress = 0 AND winner_team_id IS NULL ORDER BY match_id"
    ).fetchall()
    by_id = {}
    for match in rows:
        by_id[match["match_id"]] = match
    # Spread pairs across the left and right halves, while letting the next
    # arrival complete an existing pair immediately.
    order = [FIRST_OPENING_MATCH]
    step = FIRST_OPENING_MATCH // 2
    while step:
        additions = []
        for match_id in order:
            additions.append(match_id + step)
        order.extend(additions)
        step //= 2
    for match_id in order:
        if match_id not in by_id:
            continue
        match = by_id[match_id]
        if match["team1_id"] is not None and match["team2_id"] is None:
            opponents.append((match["match_id"], 2))
        elif match["team1_id"] is None and match["team2_id"] is not None:
            opponents.append((match["match_id"], 1))
        elif match["team1_id"] is None and match["team2_id"] is None:
            empty_matches.append((match["match_id"], 1))
            empty_matches.append((match["match_id"], 2))
    return opponents + empty_matches


def place_team(database, team_id):
    slots = available_slots(database)
    if not slots:
        return False
    match_id, slot = slots[0]
    if slot == 1:
        database.execute("UPDATE Matches SET team1_id = ? WHERE match_id = ?", (team_id, match_id))
    else:
        database.execute("UPDATE Matches SET team2_id = ? WHERE match_id = ?", (team_id, match_id))
    return True


def reset_results(database):
    # Keep everyone's original opening position when reopening registration.
    database.execute("UPDATE Matches SET winner_team_id = NULL, in_progress = 0")
    database.execute(
        "UPDATE Matches SET team1_id = NULL, team2_id = NULL WHERE round_number != 1"
    )


def can_replace_team(database, team_id):
    played = database.execute(
        """SELECT match_id FROM Matches
           WHERE (team1_id = ? OR team2_id = ?)
           AND (in_progress = 1 OR
                (winner_team_id IS NOT NULL AND team1_id IS NOT NULL AND team2_id IS NOT NULL))""",
        (team_id, team_id),
    ).fetchone()
    return played is None


def resolve_byes(database):
    # Process opening matches first, then their parents. A later empty slot
    # becomes a bye only when its entire source match is already resolved.
    registration_closed = is_registration_closed(database)
    resolved = {}
    for definition in match_definitions():
        match_id = definition["match_id"]
        if match_id == THIRD_PLACE_MATCH:
            continue
        match = database.execute("SELECT * FROM Matches WHERE match_id = ?", (match_id,)).fetchone()
        sources_ready = True
        if match_id < FIRST_OPENING_MATCH:
            sources_ready = resolved[match_id * 2] and resolved[match_id * 2 + 1]
        participants = []
        for team_id in [match["team1_id"], match["team2_id"]]:
            if team_id is not None:
                participants.append(team_id)
        winner = match["winner_team_id"]
        if registration_closed and sources_ready and len(participants) == 1:
            winner = participants[0]
            database.execute("UPDATE Matches SET winner_team_id = ? WHERE match_id = ?", (winner, match_id))
        resolved[match_id] = winner is not None or (registration_closed and sources_ready and len(participants) == 0)

        if match_id != FINAL_MATCH:
            if match_id % 2 == 0:
                database.execute("UPDATE Matches SET team1_id = ? WHERE match_id = ?", (winner, match_id // 2))
            else:
                database.execute("UPDATE Matches SET team2_id = ? WHERE match_id = ?", (winner, match_id // 2))

        if match_id in [LEFT_SEMIFINAL, RIGHT_SEMIFINAL]:
            loser = branch_runner_up(database, match_id)
            if match_id == LEFT_SEMIFINAL:
                database.execute("UPDATE Matches SET team1_id = ? WHERE match_id = ?", (loser, THIRD_PLACE_MATCH))
            else:
                database.execute("UPDATE Matches SET team2_id = ? WHERE match_id = ?", (loser, THIRD_PLACE_MATCH))

    count = database.execute("SELECT COUNT(*) FROM Team").fetchone()[0]
    if count < 3:
        database.execute(
            "UPDATE Matches SET team1_id = NULL, team2_id = NULL, winner_team_id = NULL WHERE match_id = ?",
            (THIRD_PLACE_MATCH,),
        )
        return
    # With three entrants, the single semifinal loser takes third place.
    bronze = database.execute("SELECT * FROM Matches WHERE match_id = ?", (THIRD_PLACE_MATCH,)).fetchone()
    if registration_closed and resolved[LEFT_SEMIFINAL] and resolved[RIGHT_SEMIFINAL]:
        if bronze["team1_id"] is None and bronze["team2_id"] is not None:
            database.execute("UPDATE Matches SET winner_team_id = team2_id WHERE match_id = ?", (THIRD_PLACE_MATCH,))
        if bronze["team2_id"] is None and bronze["team1_id"] is not None:
            database.execute("UPDATE Matches SET winner_team_id = team1_id WHERE match_id = ?", (THIRD_PLACE_MATCH,))


def branch_runner_up(database, match_id):
    # A bye can occupy a semifinal. Follow its winner back to the last played
    # match in that half to find the team eligible for the third-place game.
    while True:
        match = database.execute("SELECT * FROM Matches WHERE match_id = ?", (match_id,)).fetchone()
        winner = match["winner_team_id"]
        if winner is None:
            return None
        if match["team1_id"] is not None and match["team2_id"] is not None:
            if match["team1_id"] == winner:
                return match["team2_id"]
            return match["team1_id"]
        if match_id >= FIRST_OPENING_MATCH:
            return None
        left = database.execute("SELECT winner_team_id FROM Matches WHERE match_id = ?", (match_id * 2,)).fetchone()
        if left["winner_team_id"] == winner:
            match_id *= 2
        else:
            match_id = match_id * 2 + 1


def remember_action(database, description):
    matches = []
    teams = []
    waitlist = []
    for match in database.execute("SELECT * FROM Matches ORDER BY match_id"):
        matches.append(dict(match))
    for team in database.execute("SELECT * FROM Team ORDER BY team_id"):
        teams.append(dict(team))
    for waiting in database.execute("SELECT * FROM Waitlist ORDER BY waiting_id"):
        waitlist.append(dict(waiting))
    database.execute(
        """INSERT INTO ResultHistory
           (description, matches_json, started, registration_closed, teams_json, waitlist_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (description, json.dumps(matches), int(is_started(database)),
         int(is_registration_closed(database)), json.dumps(teams), json.dumps(waitlist)),
    )


def undo_last_action(database):
    action = database.execute("SELECT * FROM ResultHistory ORDER BY history_id DESC LIMIT 1").fetchone()
    if action is None:
        return None
    database.execute("DELETE FROM Matches")
    database.execute("DELETE FROM Team")
    database.execute("DELETE FROM Waitlist")
    for team in json.loads(action["teams_json"]):
        database.execute(
            "INSERT INTO Team (team_id, team_name, players, second_player, image_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (team["team_id"], team["team_name"], team["players"], team["second_player"], team["image_url"], team["created_at"]),
        )
    for waiting in json.loads(action["waitlist_json"]):
        database.execute(
            "INSERT INTO Waitlist (waiting_id, team_name, players, second_player, image_url, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (waiting["waiting_id"], waiting["team_name"], waiting["players"], waiting["second_player"], waiting["image_url"], waiting["created_at"]),
        )
    for match in json.loads(action["matches_json"]):
        database.execute(
            "INSERT INTO Matches (match_id, round_number, team1_id, team2_id, winner_team_id, in_progress) VALUES (?, ?, ?, ?, ?, ?)",
            (match["match_id"], match["round_number"], match["team1_id"], match["team2_id"], match["winner_team_id"], match["in_progress"]),
        )
    database.execute(
        "UPDATE TournamentState SET started = ?, registration_closed = ? WHERE id = 1",
        (action["started"], action["registration_closed"]),
    )
    database.execute("DELETE FROM ResultHistory WHERE history_id = ?", (action["history_id"],))
    return action["description"]


def describe_matches(data):
    by_id = {}
    for match in data["matches"]:
        by_id[match["match_id"]] = match
    completed = {}
    for definition in match_definitions():
        match = by_id[definition["match_id"]]
        match_id = match["match_id"]
        sources_ready = True
        if match_id == THIRD_PLACE_MATCH:
            sources_ready = completed[LEFT_SEMIFINAL] and completed[RIGHT_SEMIFINAL]
        elif match_id < FIRST_OPENING_MATCH:
            sources_ready = completed[match_id * 2] and completed[match_id * 2 + 1]
        count = int(match["team1_id"] is not None) + int(match["team2_id"] is not None)
        match["status"] = "pending"
        if count == 2:
            match["status"] = "ready"
        if match["in_progress"]:
            match["status"] = "playing"
        if match["winner_team_id"] is not None:
            match["status"] = "finished"
            if count == 1:
                match["status"] = "bye"
        elif data["registration_closed"] and sources_ready and count == 0:
            match["status"] = "empty"
        completed[match_id] = match["status"] in ["finished", "bye", "empty"]
        for slot in [1, 2]:
            label = "Open slot"
            if match_id == THIRD_PLACE_MATCH:
                label = "Semifinal runner-up"
                if sources_ready:
                    label = "No opponent"
            elif match_id >= FIRST_OPENING_MATCH:
                if data["registration_closed"]:
                    label = "Bye"
            else:
                source = by_id[match_id * 2 + slot - 1]
                label = "Winner of match " + str(source["display_number"])
                if source["status"] == "empty":
                    label = "Bye"
            match["team" + str(slot) + "_placeholder"] = label
        match["can_start"] = (
            data["started"] and count == 2 and not match["in_progress"]
            and match["winner_team_id"] is None
            and (data["registration_closed"] or match["round_number"] == 1)
        )
