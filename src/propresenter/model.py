"""Domain models for the ProPresenter application."""
from dataclasses import dataclass


@dataclass
class Song:
    """Represents a song with metadata."""
    book: str
    number: int
    title: str
    info: list[str]

    def __str__(self) -> str:
        return f"{self.book} {self.number}: {self.title}\n  " + "\n  ".join(self.info)

