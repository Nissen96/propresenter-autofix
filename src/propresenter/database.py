"""Database operations for song storage and retrieval."""
import sqlite3
from pathlib import Path

from .types import Song


def init_database(db_path: Path) -> None:
    """Initialize the SQLite database with the songs table if it doesn't exist."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS songs (
                book TEXT NOT NULL,
                number INTEGER NOT NULL,
                title TEXT NOT NULL,
                info TEXT NOT NULL,
                PRIMARY KEY (book, number)
            )
        """)
        conn.commit()


def save_song(db_path: Path, song: Song) -> None:
    """Save song information to the database."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        # Join info lines with newlines for storage
        info_text = "\n".join(song.info)
            
        cursor.execute(
            "INSERT OR REPLACE INTO songs (book, number, title, info) VALUES (?, ?, ?, ?)",
            (song.book, song.number, song.title, info_text)
        )
        conn.commit()


def load_song(db_path: Path, book: str, number: int) -> Song | None:
    """Retrieve song information from the database."""
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, info FROM songs WHERE book = ? AND number = ?",
            (book, number)
        )
        
        result = cursor.fetchone()
    
    if result is None:
        return None
    
    title, info_text = result
    info = info_text.split("\n") if info_text else []
    
    return Song(book=book, number=number, title=title, info=info)

