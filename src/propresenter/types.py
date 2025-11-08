"""Presentation content types with data and methods."""
import re
from dataclasses import dataclass
from pathlib import Path

from protobuf import presentation_pb2 as pb


@dataclass
class FormattedLine:
    """A formatted text line."""
    formatting: str = ""
    text: str = ""
    
    def replace(self, pattern: str, replacement: str) -> "FormattedLine":
        return FormattedLine(formatting=self.formatting, text=self.text.replace(pattern, replacement))
    
    def startswith(self, prefix: str) -> bool:
        return self.text.startswith(prefix)
    
    def strip(self) -> "FormattedLine":
        return FormattedLine(formatting=self.formatting, text=self.text.strip())
    
    def lower(self) -> "FormattedLine":
        return FormattedLine(formatting=self.formatting, text=self.text.lower())

    def __len__(self) -> int:
        return len(self.text)
    
    def __str__(self) -> str:
        return f"{self.formatting} {self.text}"


@dataclass
class Song:
    """Represents a song (songbook songs have book/number, others don't)."""
    title: str
    info: list[str]
    book: str = ""  # Empty for non-songbook songs
    number: int = 0  # 0 for non-songbook songs
    
    def __str__(self) -> str:
        if self.book and self.number:
            return f"{self.book} {self.number}: {self.title}\n  " + "\n  ".join(self.info)
        return f"{self.title}\n  " + "\n  ".join(self.info)
    
    @classmethod
    def load_from_db(cls, db_path: Path, book: str, number: int) -> "Song | None":
        """Load song from database."""
        from .database import load_song
        return load_song(db_path, book, number)
    
    @staticmethod
    def get_file_patterns(book: str | None, number: int) -> list[str]:
        """Get patterns for song files (handles optional space)."""
        if book is None:
            return ["*.pro"]
        
        book_upper = book.upper()
        return [
            f"{book_upper} {number:03d} *.pro",
            f"{book_upper}{number:03d} *.pro",
        ]
    
    @staticmethod
    def get_all_file_patterns(book: str | None) -> list[str]:
        """Get patterns to find all songs."""
        if book is None:
            return ["*.pro"]
        book_upper = book.upper()
        return [
            f"{book_upper} *.pro",
            f"{book_upper}*.pro",
        ]
    
    @staticmethod
    def extract_number_from_filename(book: str | None, filename: str) -> int | None:
        """Extract song number from filename."""
        if book is None:
            return None
        
        pattern = rf"^{re.escape(book.upper())}\s*(\d+)(?:[a-z]| -)?"
        match = re.match(pattern, filename, re.IGNORECASE)
        if match:
            return int(match.group(1))
        return None
    
    def format_filename(self) -> str:
        """Format song filename."""
        if self.book and self.number:
            return f"{self.book} {self.number:03d} - {self.title.replace('?', '')}.pro"
        return f"{self.title.replace('?', '')}.pro"
    
    def format_presentation_name(self) -> str:
        """Format song presentation name."""
        if self.book and self.number:
            return f"{self.book} {self.number:03d} - {self.title}"
        return self.title
    
    def set_ccli_info(self, pres: pb.Presentation) -> None:
        """Set CCLI for songs."""
        if self.book and self.number:
            pres.ccli.author = self.book
            pres.ccli.song_number = self.number
        else:
            pres.ccli.author = ""
            pres.ccli.song_number = 0
        pres.ccli.song_title = self.title
        pres.ccli.display = True
    
    def get_info_slide_content(self) -> list[FormattedLine]:
        """Get song infoslide content."""
        if self.book and self.number:
            return [
                FormattedLine(formatting="\\sl288\\slmult1", text=f"{self.book} {self.number:03d}"),
                FormattedLine(formatting="\\sl360\\slmult1", text=self.title),
                *[FormattedLine(formatting="\\sl288\\slmult1\\i", text=info) for info in self.info]
            ]
        return [
            FormattedLine(formatting="\\sl360\\slmult1", text=self.title),
            *[FormattedLine(formatting="\\sl288\\slmult1\\i", text=info) for info in self.info]
        ]
    
    def should_add_dash_to_last_slide(self) -> bool:
        """Whether to add '-' to the last slide."""
        return True


@dataclass
class BibleText:
    """Represents a Bible text presentation (just the reference)."""
    reference: str  # e.g., "Rom 10, 1-8" or "Matt 22, 1"
    
    def __str__(self) -> str:
        return self.reference
    
    @classmethod
    def load_from_db(cls, db_path: Path, identifier: str | int) -> "BibleText | None":
        """Load Bible text from database."""
        # TODO: Implement when Bible database is available
        return None
    
    @staticmethod
    def get_file_patterns(identifier: str | int) -> list[str]:
        """Get patterns for Bible text files."""
        return [f"{identifier} *.pro"]
    
    def format_filename(self) -> str:
        """Format Bible text filename."""
        return f"{self.reference}.pro"
    
    def format_presentation_name(self) -> str:
        """Format Bible text presentation name."""
        return self.reference
    
    def set_ccli_info(self, pres: pb.Presentation) -> None:
        """Set CCLI for Bible texts."""
        pres.ccli.author = "Bible"
        pres.ccli.song_number = 0
        pres.ccli.song_title = self.reference
        pres.ccli.display = True

    def should_add_dash_to_last_slide(self) -> bool:
        """Whether to add '-' to the last slide."""
        return True


