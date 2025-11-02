"""ProPresenter song information management."""

__version__ = "1.0.0"

# Public API
from .constants import DEFAULT_DB_PATH, VALID_BOOKS
from .database import init_database, load_song, save_song
from .model import Song
from .utils import setup_logging

__all__ = [
    "DEFAULT_DB_PATH",
    "VALID_BOOKS",
    "Song",
    "init_database",
    "load_song",
    "save_song",
    "setup_logging",
]

