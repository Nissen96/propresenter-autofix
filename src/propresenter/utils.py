"""Shared utility functions."""
import logging

# Configure logging
def setup_logging(log_file: str = "propresenter.log", level: int = logging.INFO) -> None:
    """Configure logging to both file and console."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def log_error(message: str) -> None:
    """Log an error message. Deprecated: use logging.error() instead."""
    logging.error(message)


def normalize(text: str) -> str:
    r"""
    Normalize text by keeping ASCII characters, showing non-ASCII as \uXXXX ?,
    # and adding a space after digit commas.
    """
    new_text = []
    for c in text:
        v = ord(c)
        new_text.append(c if 32 <= v <= 127 else f"\\u{v} ?")
    return "".join(new_text)


def normalize2(text: str) -> str:
    r"""
    Normalize text by keeping ASCII characters, showing non-ASCII as \'XX,
    # and adding a space after digit commas.
    """
    new_text = []
    for c in text:
        v = ord(c)
        new_text.append(c if 32 <= v <= 127 else f"\\'{v:x}")
    return "".join(new_text)
