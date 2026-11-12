import json
import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

with (ROOT / "settings.json").open(encoding="utf-8") as file:
    settings = json.load(file)

SITE_NAME = settings["site_name"]
HOST = os.environ.get("HOST", settings["host"])
PORT = int(os.environ.get("PORT", settings["port"]))
ORGANIZER_KEY = os.environ.get("ORGANIZER_KEY", "")
DATABASE_PATH = ROOT / settings["database_path"]
UPLOADS_PATH = ROOT / settings["uploads_path"]
STATIC_PATH = ROOT / settings["static_path"]
SCHEMA_PATH = ROOT / settings["schema_path"]
TEAM_CAPACITY = settings["team_capacity"]
WAITLIST_CAPACITY = settings["waitlist_capacity"]
TEAM_NAME_MAX_LENGTH = settings["team_name_max_length"]
PLAYERS_MAX_LENGTH = settings["players_max_length"]
DEFAULT_TEAM_IMAGE = settings["default_team_image"]
IMAGE_MAX_BYTES = settings["image_max_bytes"]
IMAGE_MAX_PIXELS = settings["image_max_pixels"]
IMAGE_THUMBNAIL_SIZE = settings["image_thumbnail_size"]
IMAGE_FORMATS = settings["image_formats"]
REQUEST_MAX_BYTES = settings["request_max_bytes"]
REFRESH_INTERVAL_MS = settings["refresh_interval_ms"]
REGISTRATION_RATE_LIMIT = settings["registration_requests_per_window"]
ADMIN_RATE_LIMIT = settings["admin_requests_per_window"]
RATE_LIMIT_WINDOW = settings["rate_limit_window_seconds"]
RATE_LIMIT_MAX_CLIENTS = settings["rate_limit_max_clients"]
ALLOWED_HOSTS = settings["allowed_hosts"]
ALLOWED_ORIGINS = settings["allowed_origins"]

# The fixed knockout bracket needs a power-of-two number of slots.
if TEAM_CAPACITY < 4 or TEAM_CAPACITY & (TEAM_CAPACITY - 1):
    raise ValueError("team_capacity must be a power of two, starting at 4.")
if REQUEST_MAX_BYTES <= IMAGE_MAX_BYTES:
    raise ValueError("request_max_bytes must leave room for the image and form fields.")

for name in ["registration_requests_per_window", "admin_requests_per_window",
             "rate_limit_window_seconds", "rate_limit_max_clients",
             "image_max_bytes", "image_max_pixels", "image_thumbnail_size",
             "refresh_interval_ms", "team_name_max_length", "players_max_length", "waitlist_capacity"]:
    if settings[name] <= 0:
        raise ValueError(name + " must be positive.")
