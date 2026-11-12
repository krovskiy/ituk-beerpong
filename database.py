import sqlite3
import config
from tournament import match_definitions




def connect_database():
    # FastAPI may finish a request on a different worker thread. Each request
    # still owns its own connection; it is never shared with another request.
    connection = sqlite3.connect(config.DATABASE_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def create_tables():
    config.DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    schema = config.SCHEMA_PATH.read_text(encoding="utf-8")
    connection = connect_database()
    try:
        connection.executescript(schema)
        columns = []
        for column in connection.execute("PRAGMA table_info(Team)"):
            columns.append(column["name"])
        if "second_player" not in columns:
            connection.execute("ALTER TABLE Team ADD COLUMN second_player TEXT NOT NULL DEFAULT ''")
        match_columns = []
        for column in connection.execute("PRAGMA table_info(Matches)"):
            match_columns.append(column["name"])
        if "in_progress" not in match_columns:
            connection.execute("ALTER TABLE Matches ADD COLUMN in_progress INTEGER NOT NULL DEFAULT 0")
        state_columns = []
        for column in connection.execute("PRAGMA table_info(TournamentState)"):
            state_columns.append(column["name"])
        if "registration_closed" not in state_columns:
            connection.execute("ALTER TABLE TournamentState ADD COLUMN registration_closed INTEGER NOT NULL DEFAULT 0")
            # A previously started tournament had already closed registration.
            connection.execute("UPDATE TournamentState SET registration_closed = started")
        history_columns = []
        for column in connection.execute("PRAGMA table_info(ResultHistory)"):
            history_columns.append(column["name"])
        if "registration_closed" not in history_columns:
            connection.execute("ALTER TABLE ResultHistory ADD COLUMN registration_closed INTEGER NOT NULL DEFAULT 0")
        if "teams_json" not in history_columns:
            connection.execute("ALTER TABLE ResultHistory ADD COLUMN teams_json TEXT NOT NULL DEFAULT '[]'")
            connection.execute("ALTER TABLE ResultHistory ADD COLUMN waitlist_json TEXT NOT NULL DEFAULT '[]'")
            # Legacy snapshots cannot restore the new roster and match locks.
            connection.execute("DELETE FROM ResultHistory")
        existing_count = connection.execute("SELECT COUNT(*) FROM Matches").fetchone()[0]
        definitions = match_definitions()
        if existing_count != 0 and existing_count != len(definitions):
            raise ValueError("The saved tournament has a different capacity. Use a new database path for a new tournament.")
        for match in definitions:
            connection.execute(
                "INSERT OR IGNORE INTO Matches (match_id, round_number) VALUES (?, ?)",
                (match["match_id"], match["round_number"]),
            )
        # Preserve an event already in progress from the previous version.
        state = connection.execute("SELECT started FROM TournamentState WHERE id = 1").fetchone()
        results = connection.execute("SELECT COUNT(*) FROM Matches WHERE winner_team_id IS NOT NULL").fetchone()[0]
        if not state["started"] and results:
            connection.execute("UPDATE TournamentState SET started = 1, registration_closed = 1 WHERE id = 1")
        connection.commit()
    finally:
        connection.close()


def get_database():
    # FastAPI opens a connection for each request and closes it afterward.
    connection = connect_database()
    try:
        yield connection
    finally:
        connection.close()
