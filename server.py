from contextlib import asynccontextmanager
from io import BytesIO
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

import config
import tournament
from database import create_tables, get_database
from security import RequestProtection, SecurityHeaders, require_organizer


Image.MAX_IMAGE_PIXELS = config.IMAGE_MAX_PIXELS


@asynccontextmanager
async def lifespan(app):
    config.UPLOADS_PATH.mkdir(parents=True, exist_ok=True)
    create_tables()
    yield


app = FastAPI(title=config.SITE_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(RequestProtection)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=config.ALLOWED_HOSTS)
app.add_middleware(SecurityHeaders)


class WinnerRequest(BaseModel):
    team_id: int = Field(gt=0)


class ReplacementRequest(BaseModel):
    waiting_id: int = Field(gt=0)


def save_team_image(upload):
    contents = upload.file.read(config.IMAGE_MAX_BYTES + 1)
    if len(contents) > config.IMAGE_MAX_BYTES:
        raise HTTPException(400, "The image exceeds the upload size limit.")
    try:
        image = Image.open(BytesIO(contents))
        if image.format not in config.IMAGE_FORMATS:
            raise HTTPException(400, "Choose a supported image format.")
        if image.width * image.height > config.IMAGE_MAX_PIXELS:
            raise HTTPException(400, "Your image has too many pixels.")
        image.load()
        image = image.convert("RGBA")
        image.thumbnail((config.IMAGE_THUMBNAIL_SIZE, config.IMAGE_THUMBNAIL_SIZE))
        filename = uuid4().hex + ".png"
        image.save(config.UPLOADS_PATH / filename, format="PNG")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "This image could not be read. Try another image.")
    return "/uploads/" + filename


def tournament_data(database, include_players=False):
    columns = "team_id, team_name, image_url"
    if include_players:
        columns = "team_id, team_name, image_url, players, second_player"
    team_rows = database.execute("SELECT " + columns + " FROM Team ORDER BY team_id").fetchall()
    match_rows = database.execute("SELECT * FROM Matches ORDER BY match_id").fetchall()
    teams = []
    matches = []
    definitions = {}
    for definition in tournament.match_definitions():
        definitions[definition["match_id"]] = definition
    for row in team_rows:
        team = dict(row)
        if include_players:
            team["can_replace"] = tournament.can_replace_team(database, team["team_id"])
        teams.append(team)
    for row in match_rows:
        match = dict(row)
        match["display_number"] = definitions[match["match_id"]]["display_number"]
        matches.append(match)
    data = tournament.public_settings()
    data["teams"] = teams
    data["matches"] = matches
    data["started"] = tournament.is_started(database)
    data["registration_closed"] = tournament.is_registration_closed(database)
    data["runner_up_id"] = tournament.branch_runner_up(database, tournament.FINAL_MATCH)
    data["available_places"] = len(tournament.available_slots(database))
    waiting_count = database.execute("SELECT COUNT(*) FROM Waitlist").fetchone()[0]
    data["waitlist_available_places"] = max(0, config.WAITLIST_CAPACITY - waiting_count)
    history = database.execute("SELECT description FROM ResultHistory ORDER BY history_id DESC LIMIT 1").fetchone()
    if include_players:
        data["waiting_list"] = []
        for row in database.execute("SELECT * FROM Waitlist ORDER BY waiting_id"):
            data["waiting_list"].append(dict(row))
        data["undo_description"] = None
        if history is not None:
            data["undo_description"] = history["description"]
    tournament.describe_matches(data)
    return data


@app.get("/api/tournament")
def read_tournament(database=Depends(get_database)):
    return tournament_data(database)


@app.get("/api/admin/tournament", dependencies=[Depends(require_organizer)])
def read_admin_tournament(database=Depends(get_database)):
    return tournament_data(database, include_players=True)


@app.post("/api/teams", status_code=201)
def register_team(
    team_name: str = Form(min_length=1, max_length=config.TEAM_NAME_MAX_LENGTH),
    players: str = Form(min_length=1, max_length=config.PLAYERS_MAX_LENGTH),
    second_player: str = Form(default="", max_length=config.PLAYERS_MAX_LENGTH),
    image: UploadFile | None = File(default=None),
    database=Depends(get_database),
):
    team_name = team_name.strip()
    players = players.strip()
    second_player = second_player.strip()
    if not team_name or not players:
        raise HTTPException(400, "Please enter a team name and player names.")
    if any(ord(character) < 32 for character in team_name):
        raise HTTPException(400, "The team name contains unsupported characters.")

    with database:
        database.execute("BEGIN IMMEDIATE")
        if tournament.is_registration_closed(database):
            raise HTTPException(409, "Registration is closed. You can join the waiting list.")
        team_count = database.execute("SELECT COUNT(*) FROM Team").fetchone()[0]
        if team_count >= config.TEAM_CAPACITY:
            raise HTTPException(409, "Registration is full.")
        if not tournament.available_slots(database):
            raise HTTPException(409, "No unstarted first-round slots remain. You can join the waiting list.")
        existing_team = database.execute(
            "SELECT team_id FROM Team WHERE team_name = ?", (team_name,)
        ).fetchone()
        if existing_team is not None:
            raise HTTPException(409, "That team name is already registered.")
        waiting = database.execute("SELECT waiting_id FROM Waitlist WHERE team_name = ?", (team_name,)).fetchone()
        if waiting is not None:
            raise HTTPException(409, "That team is already on the waiting list.")

        image_url = config.DEFAULT_TEAM_IMAGE
        if image is not None and image.filename:
            image_url = save_team_image(image)
        cursor = database.execute(
            "INSERT INTO Team (team_name, players, second_player, image_url) VALUES (?, ?, ?, ?)",
            (team_name, players, second_player, image_url),
        )
        team_id = cursor.lastrowid
        tournament.place_team(database, team_id)
        # Old undo snapshots belong to the previous roster.
        database.execute("DELETE FROM ResultHistory")
    return {"team_id": team_id, "team_name": team_name, "image_url": image_url}


def set_match_team(database, match_id, slot, team_id):
    if slot == 1:
        database.execute(
            "UPDATE Matches SET team1_id = ?, winner_team_id = NULL, in_progress = 0 WHERE match_id = ?", (team_id, match_id)
        )
    else:
        database.execute(
            "UPDATE Matches SET team2_id = ?, winner_team_id = NULL, in_progress = 0 WHERE match_id = ?", (team_id, match_id)
        )


def clear_later_results(database, match_id):
    if match_id == tournament.THIRD_PLACE_MATCH:
        return
    while match_id > tournament.FINAL_MATCH:
        if match_id == tournament.LEFT_SEMIFINAL:
            set_match_team(database, tournament.THIRD_PLACE_MATCH, 1, None)
        if match_id == tournament.RIGHT_SEMIFINAL:
            set_match_team(database, tournament.THIRD_PLACE_MATCH, 2, None)
        next_match_id = match_id // 2
        slot = 1
        if match_id % 2 != 0:
            slot = 2
        set_match_team(database, next_match_id, slot, None)
        match_id = next_match_id


@app.put("/api/matches/{match_id}/winner", dependencies=[Depends(require_organizer)])
def record_winner(match_id: int, result: WinnerRequest, database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        match = database.execute("SELECT * FROM Matches WHERE match_id = ?", (match_id,)).fetchone()
        if match is None:
            raise HTTPException(404, "This match does not exist.")
        if not tournament.is_started(database):
            raise HTTPException(409, "Start the tournament from the admin page first.")
        if match["team1_id"] is None or match["team2_id"] is None:
            raise HTTPException(409, "Both teams must be decided before recording a winner.")
        if result.team_id not in [match["team1_id"], match["team2_id"]]:
            raise HTTPException(400, "The winner must be one of the teams in this match.")
        if match["winner_team_id"] == result.team_id:
            return {"message": "This result is already saved."}
        if not match["in_progress"] and match["winner_team_id"] is None:
            raise HTTPException(409, "Start this match before recording its winner.")

        tournament.remember_action(database, "record winner for match " + str(match_id))
        clear_later_results(database, match_id)
        database.execute("UPDATE Matches SET winner_team_id = ?, in_progress = 0 WHERE match_id = ?", (result.team_id, match_id))
        if match_id not in [tournament.FINAL_MATCH, tournament.THIRD_PLACE_MATCH]:
            slot = 1
            if match_id % 2 != 0:
                slot = 2
            set_match_team(database, match_id // 2, slot, result.team_id)

        if match_id in [tournament.LEFT_SEMIFINAL, tournament.RIGHT_SEMIFINAL]:
            losing_team_id = match["team1_id"]
            if losing_team_id == result.team_id:
                losing_team_id = match["team2_id"]
            slot = 1
            if match_id == tournament.RIGHT_SEMIFINAL:
                slot = 2
            set_match_team(database, tournament.THIRD_PLACE_MATCH, slot, losing_team_id)
        tournament.resolve_byes(database)
    return {"message": "Result saved."}


@app.post("/api/admin/start", dependencies=[Depends(require_organizer)])
def start_tournament(database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        if tournament.is_started(database):
            raise HTTPException(409, "The tournament is already started.")
        count = database.execute("SELECT COUNT(*) FROM Team").fetchone()[0]
        if count < 2:
            raise HTTPException(409, "Register at least two teams before starting.")
        tournament.remember_action(database, "start tournament")
        database.execute("UPDATE TournamentState SET started = 1 WHERE id = 1")
    return {"message": "Games enabled. Registration stays open until you close it."}


@app.post("/api/admin/reopen", dependencies=[Depends(require_organizer)])
def reopen_registration(database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        if not tournament.is_started(database):
            raise HTTPException(409, "Registration is already open.")
        tournament.remember_action(database, "reopen registration")
        database.execute("UPDATE TournamentState SET started = 0, registration_closed = 0 WHERE id = 1")
        tournament.reset_results(database)
    return {"message": "Registration reopened. Match results were cleared."}


@app.post("/api/admin/undo", dependencies=[Depends(require_organizer)])
def undo_action(database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        description = tournament.undo_last_action(database)
        if description is None:
            raise HTTPException(409, "There is nothing to undo.")
    return {"message": "Undid: " + description}


@app.delete("/api/matches/{match_id}/winner", dependencies=[Depends(require_organizer)])
def clear_winner(match_id: int, database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        match = database.execute("SELECT * FROM Matches WHERE match_id = ?", (match_id,)).fetchone()
        if match is None:
            raise HTTPException(404, "This match does not exist.")
        if match["winner_team_id"] is None:
            raise HTTPException(409, "This match has no result to clear.")
        if match["team1_id"] is None or match["team2_id"] is None:
            raise HTTPException(409, "A bye is advanced automatically. Reopen registration to change the roster.")
        tournament.remember_action(database, "clear winner for match " + str(match_id))
        clear_later_results(database, match_id)
        database.execute("UPDATE Matches SET winner_team_id = NULL, in_progress = 0 WHERE match_id = ?", (match_id,))
        tournament.resolve_byes(database)
    return {"message": "Result and dependent results cleared."}


@app.post("/api/admin/close-registration", dependencies=[Depends(require_organizer)])
def close_registration(database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        if not tournament.is_started(database):
            raise HTTPException(409, "Enable games before closing registration.")
        if tournament.is_registration_closed(database):
            raise HTTPException(409, "Registration is already closed.")
        tournament.remember_action(database, "close registration")
        database.execute("UPDATE TournamentState SET registration_closed = 1 WHERE id = 1")
        tournament.resolve_byes(database)
    return {"message": "Registration closed. Remaining empty slots are byes."}


@app.post("/api/admin/matches/{match_id}/start", dependencies=[Depends(require_organizer)])
def start_match(match_id: int, database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        match = database.execute("SELECT * FROM Matches WHERE match_id = ?", (match_id,)).fetchone()
        if match is None:
            raise HTTPException(404, "This match does not exist.")
        if not tournament.is_started(database):
            raise HTTPException(409, "Enable games first.")
        if match["team1_id"] is None or match["team2_id"] is None:
            raise HTTPException(409, "Both teams must be present before starting this match.")
        if not tournament.is_registration_closed(database) and match["round_number"] != 1:
            raise HTTPException(409, "Close registration before starting later rounds.")
        if match["winner_team_id"] is not None:
            raise HTTPException(409, "This match already has a result.")
        if match["in_progress"]:
            return {"message": "This match is already in progress."}
        tournament.remember_action(database, "start match " + str(match_id))
        database.execute("UPDATE Matches SET in_progress = 1 WHERE match_id = ?", (match_id,))
    return {"message": "Match started. Its teams are locked."}


@app.post("/api/waitlist", status_code=201)
def join_waiting_list(
    team_name: str = Form(min_length=1, max_length=config.TEAM_NAME_MAX_LENGTH),
    players: str = Form(min_length=1, max_length=config.PLAYERS_MAX_LENGTH),
    second_player: str = Form(default="", max_length=config.PLAYERS_MAX_LENGTH),
    image: UploadFile | None = File(default=None),
    database=Depends(get_database),
):
    team_name = team_name.strip()
    players = players.strip()
    second_player = second_player.strip()
    if not team_name or not players:
        raise HTTPException(400, "Please enter a team name and first player.")
    if any(ord(character) < 32 for character in team_name):
        raise HTTPException(400, "The team name contains unsupported characters.")
    with database:
        database.execute("BEGIN IMMEDIATE")
        if not tournament.is_registration_closed(database) and tournament.available_slots(database):
            raise HTTPException(409, "Registration is still open. Register directly instead.")
        count = database.execute("SELECT COUNT(*) FROM Waitlist").fetchone()[0]
        if count >= config.WAITLIST_CAPACITY:
            raise HTTPException(409, "The waiting list is full. Please speak to an organizer.")
        existing = database.execute("SELECT team_id FROM Team WHERE team_name = ?", (team_name,)).fetchone()
        waiting = database.execute("SELECT waiting_id FROM Waitlist WHERE team_name = ?", (team_name,)).fetchone()
        if existing is not None or waiting is not None:
            raise HTTPException(409, "That team is already registered or on the waiting list.")
        image_url = config.DEFAULT_TEAM_IMAGE
        if image is not None and image.filename:
            image_url = save_team_image(image)
        cursor = database.execute(
            "INSERT INTO Waitlist (team_name, players, second_player, image_url) VALUES (?, ?, ?, ?)",
            (team_name, players, second_player, image_url),
        )
        # Do not let an older roster snapshot erase this new arrival on undo.
        database.execute("DELETE FROM ResultHistory")
    return {"waiting_id": cursor.lastrowid, "team_name": team_name, "waiting": True}


@app.post("/api/admin/teams/{team_id}/replace", dependencies=[Depends(require_organizer)])
def replace_withdrawn_team(team_id: int, replacement: ReplacementRequest, database=Depends(get_database)):
    with database:
        database.execute("BEGIN IMMEDIATE")
        team = database.execute("SELECT * FROM Team WHERE team_id = ?", (team_id,)).fetchone()
        waiting = database.execute("SELECT * FROM Waitlist WHERE waiting_id = ?", (replacement.waiting_id,)).fetchone()
        if team is None or waiting is None:
            raise HTTPException(404, "The team or waiting-list entry was not found.")
        if not tournament.can_replace_team(database, team_id):
            raise HTTPException(409, "A team whose first game has started or finished cannot be replaced.")
        database.execute("DELETE FROM ResultHistory")
        tournament.remember_action(database, "replace withdrawn team " + team["team_name"])
        # Keep the same bracket identity, including any automatic bye positions.
        database.execute(
            "UPDATE Team SET team_name = ?, players = ?, second_player = ?, image_url = ? WHERE team_id = ?",
            (waiting["team_name"], waiting["players"], waiting["second_player"], waiting["image_url"], team_id),
        )
        database.execute("DELETE FROM Waitlist WHERE waiting_id = ?", (waiting["waiting_id"],))
    return {"message": "Withdrawn team replaced. All bracket positions and results were kept."}


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
def unknown_api_route(path: str):
    raise HTTPException(404, "This API route does not exist.")


# The admin page isn't linked publicly. Its data and actions require the key.
@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def admin_page():
    page = config.STATIC_PATH / "admin" / "index.html"
    if not page.exists():
        raise HTTPException(503, "Build the website first.")
    return FileResponse(page)


app.mount("/uploads", StaticFiles(directory=config.UPLOADS_PATH, check_dir=False), name="uploads")
if config.STATIC_PATH.exists():
    app.mount("/", StaticFiles(directory=config.STATIC_PATH, html=True), name="website")
else:
    @app.get("/")
    def frontend_not_built():
        return JSONResponse({"message": "Build the website or start the Vite development server."})

