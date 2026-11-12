-- SQLite creates the database file automatically.
CREATE TABLE IF NOT EXISTS Team (
    team_id INTEGER PRIMARY KEY,
    team_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    players TEXT NOT NULL,
    second_player TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS Matches (
    match_id INTEGER PRIMARY KEY,
    round_number INTEGER NOT NULL,
    team1_id INTEGER REFERENCES Team(team_id),
    team2_id INTEGER REFERENCES Team(team_id),
    winner_team_id INTEGER REFERENCES Team(team_id),
    in_progress INTEGER NOT NULL DEFAULT 0,
    CHECK (team1_id IS NULL OR team2_id IS NULL OR team1_id != team2_id),
    CHECK (winner_team_id IS NULL OR winner_team_id = team1_id OR winner_team_id = team2_id)
);

-- Match positions are generated from settings.json by tournament.py.
CREATE TABLE IF NOT EXISTS TournamentState (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    started INTEGER NOT NULL DEFAULT 0,
    registration_closed INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO TournamentState (id) VALUES (1);

CREATE TABLE IF NOT EXISTS ResultHistory (
    history_id INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    matches_json TEXT NOT NULL,
    started INTEGER NOT NULL,
    registration_closed INTEGER NOT NULL DEFAULT 0,
    teams_json TEXT NOT NULL DEFAULT '[]',
    waitlist_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS Waitlist (
    waiting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    players TEXT NOT NULL,
    second_player TEXT NOT NULL DEFAULT '',
    image_url TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);



