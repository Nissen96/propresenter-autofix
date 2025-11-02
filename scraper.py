"""Scrape song information from online sources and save to database."""
import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from propresenter.constants import DEFAULT_DB_PATH, VALID_BOOKS
from propresenter.database import init_database, save_song
from propresenter.model import Song
from propresenter.utils import setup_logging

# Set up logger
logger = logging.getLogger(__name__)


# --- Scraping functions ---
def get_dds_song(number: int) -> Song:
    """Scrape DDS song information from dendanskesalmebogonline.dk."""
    html = requests.get(
        f"https://www.dendanskesalmebogonline.dk/salme/{number}",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
        },
    ).text

    soup = BeautifulSoup(html, features="lxml")
    if "Denne salmetekst er ikke til rådighed" in soup.text:
        logger.warning(f"Song text not available for DDS {number}, might miss an author.")

    # Extract info such as authors - all info are in divs with class "salme-forfatter"
    # Exclude word explanations, those have a <sup> tag with a superscript number
    authors = soup.select("div.salme-forfatter:not(:has(sup))")

    # Melody info is in the top with a different class (salme-melodi)
    # All info is in a single div, lines split with <br>
    melody = soup.find(class_="salme-melodi").get_text("\n")

    song = Song(
        book="DDS",
        number=number,
        title=soup.find(class_="salme-navn").text,
        info=[
            *[t.strip(".") for author in authors for t in author.text.split("\n") if author.text and t],
            *[m.strip(".") for m in melody.split("\n")[1:] if m],
        ],
    )
    return song


def get_sos_bible_references(sang_id: int) -> list[str]:
    references = []
    with sqlite3.connect("data/sos.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT bogID, kapitel, vers FROM bibelhenvisning WHERE sangID = ?",
            (sang_id,)
        )
        for bog_id, kapitel, vers in cursor.fetchall():
            cursor.execute(
                "SELECT bog FROM bibelens_boeger WHERE id = ?",
                (bog_id,)
            )
            bog_navn = cursor.fetchone()[0]
            references.append(f"{bog_navn} {kapitel}{"," + vers if vers else ""}")
    return references


def get_sos_song(number: int) -> Song:
    with sqlite3.connect("data/sos.sqlite") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, titel, historie, melodiangivelse FROM sang WHERE endeligt_nr = ?",
            (str(number),)
        )
        sang_id, titel, historie, melodiangivelse = cursor.fetchone()
    
    bible_references = get_sos_bible_references(sang_id)

    return Song(
        book="SOS",
        number=number,
        title=titel.strip().replace(" (ny titel)", "").replace(" (Ny titel)", ""),
        info=[line for line in [
                ". ".join(bible_references) if bible_references else None,
                *[h.strip().strip(".") for h in historie.replace("\\r\\n", "\n").split("\n") if h],
                *[
                    "Mel.: " + m.strip().strip(".")
                    for m in melodiangivelse.replace("\\r\\n", "\n").split("\n")
                    if m and not m.lower().startswith("sats:")
                ],
        ] if line],
    )


def get_fs4_song(number: int) -> Song:
    with sqlite3.connect("data/fs4.db") as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT title, author FROM presentation WHERE title LIKE 'FS4 ' || ? || '%'",
            (str(number).zfill(3),)
        )
        title, author = cursor.fetchone()
    
    return Song(
        book="FS4",
        number=number,
        title=" ".join(title.split(" ")[2:]),
        info=[author],
    )


def scrape_songs(book: str, start: int, end: int, db_path: Path) -> None:
    """Scrape songs for a given book and range of numbers, saving to database."""
    init_database(db_path)
    
    logger.info(f"Scraping {book} songs {start} through {end}...")
    
    for number in range(start, end + 1):
        logger.debug(f"Processing {book} {number}...")
        
        try:
            if book == "DDS":
                song = get_dds_song(number)
            elif book == "SOS":
                song = get_sos_song(number)
            elif book == "FS4":
                song = get_fs4_song(number)
            else:
                logger.error(f"Unknown book: {book}")
                continue
        except Exception as e:
            logger.error(f"{book} {number}: Scraping failed - {str(e)}", exc_info=True)
            continue
        
        save_song(db_path, song)
        logger.info(f"{book} {number}: {song.title} - {len(song.info)} info lines")
    
    logger.info(f"Scraping complete for {book}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="scraper",
        description="Scrape song information and save to database."
    )
    parser.add_argument(
        "--book",
        type=str,
        required=True,
        help="Sangbog (e.g. DDS)"
    )
    parser.add_argument(
        "--start",
        type=int,
        default=1,
        help="Start sangnummer (default: %(default)s)"
    )
    parser.add_argument(
        "--end",
        type=int,
        required=True,
        help="Slut sangnummer"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Database path (default: %(default)s)"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    
    # Set up logging
    setup_logging()
    logger.info(f"Starting scraper for book: {args.book}")
    
    book = args.book.upper()
    if book not in VALID_BOOKS:
        logger.error(f"Unknown book: {book}")
        sys.exit(1)
    
    db_path = Path(args.db)
    
    if args.start < 1:
        logger.error("Start number must be at least 1")
        sys.exit(1)
    
    if args.end < args.start:
        logger.error("End number must be greater than or equal to start number")
        sys.exit(1)
    
    scrape_songs(book, args.start, args.end, db_path)


if __name__ == "__main__":
    main()
