"""Add infoslides and update ProPresenter presentations."""
import argparse
import logging
import re
import sys
import uuid
from enum import Enum
from importlib import resources
from pathlib import Path

from protobuf import presentation_pb2 as pb
from protobuf.cue_pb2 import Cue

from propresenter.constants import (
    DEFAULT_DB_PATH,
    SLIDE_HEIGHT,
    SLIDE_MARGIN,
    SLIDE_WIDTH,
    TEMPLATE_FONT_FACE,
    TEMPLATE_FONT_FAMILY,
    TEMPLATE_FONT_NAME,
    VALID_BOOKS,
)
from propresenter.database import load_song, save_song
from propresenter.model import Song
from propresenter.utils import normalize, normalize2, setup_logging

# Set up logger
logger = logging.getLogger(__name__)


# --- Action types ---
class ActionType(Enum):
    """ProPresenter action types."""
    MEDIA = 2
    CLEAR = 5
    MESSAGE = 8
    PRESENTATION_SLIDE = 11


# --- I/O helpers ---
def load_presentation(filepath: Path) -> pb.Presentation:
    pres = pb.Presentation()
    pres.ParseFromString(filepath.read_bytes())
    return pres


def write_presentation(out_dir: Path, song: Song, pres: pb.Presentation) -> Path:
    dst = out_dir / f"{song.book} {song.number:03d} - {song.title.replace("?", "")}.pro"
    dst.write_bytes(pres.SerializeToString())
    return dst


def cleanup_slide_text(lines: list[str], intro: bool = False, song: Song | None = None) -> list[str]:
    # Remove tabs, strip leading and trailing whitespace
    lines = [line.replace(r"\tab", "").replace(r"\par", "").strip() for line in lines]
    
    # Remove word explanations
    lines = [line.replace("*", "") for line in lines if not line.startswith("*")]
    
    # Remove weird characters seen
    lines = [line.replace(r"\u8232?", "") for line in lines]
    
    # Remove copyright lines
    lines = [line for line in lines if not line.startswith(normalize("©")) and not line.startswith(normalize2("©"))]
    
    # Remove verse lines
    lines = [line for line in lines if not re.match(r"verse?\s*\d+", line, re.IGNORECASE)]
    
    # Strip whitespace
    lines = [line.strip() for line in lines]
    
    if intro:
        # For info slides, remove all empty lines
        lines = [line for line in lines if line != ""]
    else:
        # For normal slides, remove only from the start and end
        while lines and lines[0] in ("", "."):
            lines.pop(0)

        while lines and lines[-1] in ("", "-", "."):
            lines.pop()

    # Remove existing info inserted into some song slides
    if not intro and song is not None:
        info_lines1 = [normalize(line).lower() for line in song.info]
        info_lines2 = [normalize2(line).lower() for line in song.info]
        lines = [
            line for line in lines
            if not (l := line.lower()).startswith(f"{song.book} {song.number:03d}".lower())
            and not l.startswith(f"{song.book} {song.number}".lower())
            and l not in info_lines1
            and l not in info_lines2
            and l.replace(", ", ". ") not in info_lines1
            and l.replace(", ", ". ") not in info_lines2
        ]

    # No lines left after removals
    if len(lines) == 0:
        return []

    # Move verse number down if alone on first line
    if len(lines) > 1 and re.match(r"^\d{,2}\.?$", lines[0]):
        lines[1] = f"{lines[0].rstrip(".")}. {lines[1]}"
        del lines[0]

    # Insert relevant spacing to center the text
    if lines[0] == "..." and lines[-1] != "...":
        lines.append("")
    elif lines[-1] == "..." and lines[0] != "...":
        lines.insert(0, "")
    
    return lines


def generate_slide_rtf(lines: list[str], intro: bool = False, font_size: int = 180) -> str:
    # Set line heights and formatting for intro slide
    if intro:
        lines = [
            f"\\sl288\\slmult1 {lines[0]}",
            f"\\sl360\\slmult1 {lines[1]}",
            *[f"\\sl288\\slmult1\\i {info}" for info in lines[2:]]  # Cursive info lines
        ]
    
    # Normalize special characters
    lines = [normalize(line) for line in lines]

    # Format as RTF
    return f"{{\\rtf1\\ansi\\uc1\\deff0{{\\fonttbl{{\\f0\\fnil Arial;}}}}\\pard\\qc\\sa0\\sb0\\fs{font_size}\\f0 " + r"\par ".join(lines) + "}"


def set_slide_settings(slide: pb.Slide) -> None:
    # Set slide size
    slide.size.width = SLIDE_WIDTH
    slide.size.height = SLIDE_HEIGHT

    # Set background color to white
    slide.draws_background_color = True
    slide.background_color.red = 1
    slide.background_color.green = 1
    slide.background_color.blue = 1
    slide.background_color.alpha = 1
    
    # Delete all other elements than the first (main text box)
    del slide.elements[1:]
    
    # Set attributes on slide element (text box)
    elem = slide.elements[0]

    # Set textbox location and size
    box = elem.element.bounds
    box.origin.x = SLIDE_MARGIN
    box.origin.y = SLIDE_MARGIN
    box.size.width = SLIDE_WIDTH - 2 * SLIDE_MARGIN
    box.size.height = SLIDE_HEIGHT - 2 * SLIDE_MARGIN
    
    # Set text attributes
    text = elem.element.text
    
    # Set font type in attributes and in RTF data
    text.attributes.font.name = TEMPLATE_FONT_NAME
    text.attributes.font.family = TEMPLATE_FONT_FAMILY
    text.attributes.font.face = TEMPLATE_FONT_FACE
    
    # Set font color black in attributes and in RTF data
    text.attributes.text_solid_fill.red = 0
    text.attributes.text_solid_fill.green = 0
    text.attributes.text_solid_fill.blue = 0
    
    # Set stroke off
    text.attributes.stroke_width = 0


def set_song_settings(song: Song, pres: pb.Presentation) -> None:
    # Set CCLI info
    pres.ccli.author = song.book
    pres.ccli.song_number = song.number
    pres.ccli.song_title = song.title
    pres.ccli.display = True
    
    # Set title
    pres.name = f"{song.book} {song.number:03d} - {song.title}"
    
    default_font_size = None
    
    identifiers = [
        identifier
        for cue_group in pres.cue_groups
        for identifier in cue_group.cue_identifiers
    ]
    
    for i in range(len(pres.cues) - 1, -1, -1):
        cue = pres.cues[i]

        # Enable slide
        cue.isEnabled = True

        # Iterate backwards for safe action deletions
        for j in range(len(cue.actions) - 1, -1, -1):
            action = cue.actions[j]
            action_type = ActionType(action.type)
            
            if action_type is ActionType.PRESENTATION_SLIDE:
                # Enable slide
                action.isEnabled = True
                
                # Remove transitions
                action.slide.presentation.ClearField("transition")

                # Settings for each slide's contents
                base_slide = action.slide.presentation.base_slide
                set_slide_settings(base_slide)
                
                text = base_slide.elements[0].element.text
                
                # Extract font size from RTF data
                font_sizes = {int(size) for size in re.findall(r"\\fs(\d+)", text.rtf_data.decode())}
                if len(font_sizes) == 0:
                    font_size = 180  # Size 90 in PP
                elif len(font_sizes) == 1:
                    font_size = int(font_sizes.pop())
                elif default_font_size is not None and default_font_size in font_sizes:
                    font_size = default_font_size
                else:
                    logger.warning(f"{song.book} {song.number:03d} - Slide {i + 1} har flere skriftstørrelser sat: {[size // 2 for size in font_sizes]}")
                    if default_font_size is not None:
                        print(f"Skriftstørrelse fra sangens andre slides: {default_font_size // 2}")
                        font_sizes.add(default_font_size)
                    font_size = choice("Vælg størrelse: ", [size // 2 for size in font_sizes]) * 2
                default_font_size = font_size

                # Get slide text from original song based on a few identified patterns
                patterns = [
                    r"(\\b0?\\i0?\\ul0?\\strike0?).*?\\cb\d+ ?(.*?)(\\par|\})",
                    r"(\\b0?\\i0?\\ul0?\\strike0?).*?\\nosupersub ?(.*?)(\\par|\})",
                    r"(\\b0?\\i0?\\ul0?\\strike0?).*?\\ltrch ?(.*?)()\}",
                ]
                
                for pattern in patterns:
                    song_lines = [f"{match[0]} {match[1].strip()}" for match in re.findall(pattern, text.rtf_data.decode())]
                    if len(song_lines) > 0:
                        break

                # Generate slide text with song lines
                cleaned_lines = cleanup_slide_text(song_lines, intro=False, song=song)
                
                # Remove empty slides
                if len(cleaned_lines) == 0:
                    logger.warning(f"{song.book} {song.number:03d} - Slide {i + 1} er tomt efter cleanup og fjernes")
                    del pres.cues[i]
                    del identifiers[i]
                    continue
                
                # If only one line, check if it should be removed
                if len(cleaned_lines) == 1:
                    line = re.sub(r"\\b0?\\i0?\\ul0?\\strike0?", "", cleaned_lines[0]).strip()
                    print(f"{song.book} {song.number:03d} - Slide {i + 1} har kun én linje:\n    \"{line}\"")
                    ans = input("Fjern dette slide? [Y/n] ")
                    if not ans or ans[0].lower() != "n":
                        logger.warning(f"{song.book} {song.number:03d} - Slide {i + 1} fjernes")
                        del pres.cues[i]
                        del identifiers[i]
                        continue
                
                # If last slide, add a dash at the end and insert empty line at the start if not "..."
                if i == len(pres.cues) - 1:
                    if cleaned_lines[0] == "...":
                        cleaned_lines[-1] = "-"
                    else:
                        cleaned_lines.append("-")
                        cleaned_lines.insert(0, "")
                
                # Set slide text based on cleaned and formatted lines
                text.rtf_data = generate_slide_rtf(cleaned_lines, font_size=font_size).encode()
        
            elif action_type in [ActionType.MEDIA, ActionType.MESSAGE, ActionType.CLEAR]:
                # Remove media and message actions
                del cue.actions[j]

    # Replace all groupings with a single group with non-deleted slides
    pres.ClearField("cue_groups")
    pres.cue_groups.add()
    for identifier in identifiers:
        pres.cue_groups[0].cue_identifiers.append(identifier)
    
    if len(pres.cues) == 0:
        logger.warning(f"{song.book} {song.number:03d} - Sangen har ingen slides efter cleanup")


# --- Build a new Infoslide cue ---
def make_infoslide(song: Song) -> Cue:
    """Create an infoslide cue from template with song information."""
    # Get info cue from package data
    template_path = resources.files("propresenter") / "info_template.pro"
    with resources.as_file(template_path) as path:
        info_pres = load_presentation(path)

    cue = info_pres.cues[0]

    # Set new UUID
    cue.uuid.string = str(uuid.uuid4())
    cue.name = ""
    
    # Set slide settings
    slide = cue.actions[0].slide.presentation.base_slide
    set_slide_settings(slide)

    # Insert song information with line lengths prepended
    all_info = cleanup_slide_text([f"{song.book} {song.number}", song.title, *song.info], intro=True)
    text = slide.elements[0].element.text
    text.rtf_data = generate_slide_rtf(all_info, intro=True).encode()

    # Add missing custom attributes for line lengths and sizes
    for _ in range(len(all_info)):
        text.attributes.custom_attributes.add()

    # Set line lengths (cummulative) and relative font sizes
    pos = 0
    sizes = [150, 100] + [70] * (len(all_info) - 2)
    for attr, info, size in zip(text.attributes.custom_attributes, all_info, sizes, strict=True):
        attr.range.start = pos
        attr.range.end = pos + len(info)
        attr.original_font_size = size
        pos += len(info) + 1
    
    # Add label
    cue.actions[0].label.text = "Infoslide"
    
    # Set scale behavior to auto-scale text
    text.scale_behavior = pb.action__pb2.graphicsData__pb2._GRAPHICS_TEXT_SCALEBEHAVIOR.values_by_name["SCALE_BEHAVIOR_SCALE_FONT_DOWN"].number

    return cue


def insert_slide(pres: pb.Presentation, slide: pb.Slide, index: int) -> None:
    """Insert slide at the given index."""
    pres.cues.insert(index, slide)
    pres.cue_groups[0].cue_identifiers.insert(index, pb.basicTypes__pb2.UUID(string=slide.uuid.string))


def choice(prompt: str, choices: list[str | int]) -> str | int:
    print(prompt)
    for i, c in enumerate(choices, 1):
        print(f"    [{i}]: {c}")
    
    try:
        c = int(input("> ")) - 1
        print()
        if c < 0:
            raise ValueError
        return choices[c]
    except (ValueError, IndexError):
        print("Ugyldigt valg, prøv igen")
        return choice(prompt, choices)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="propresenter",
        description="Tilføj infoslides og opdater ProPresenter præsentationer."
    )
    parser.add_argument(
        "input_library",
        type=str,
        help="Sti til ProPresenter input library"
    )
    parser.add_argument(
        "output_library",
        type=str,
        help="Sti til ProPresenter output library"
    )
    parser.add_argument(
        "--book",
        type=str,
        required=True,
        help="Sangbog (e.g. DDS)"
    )
    parser.add_argument(
        "--song",
        type=int,
        help="Sangnummer (udelad for ALLE sange eller brug --start og --end)"
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
        help="Slut sangnummer (udelad for ALLE sange)"
    )
    parser.add_argument(
        "--db",
        type=str,
        default=DEFAULT_DB_PATH,
        help="Database sti (default: %(default)s)"
    )
    parser.add_argument(
        "--add-infoslide",
        action="store_true",
        help="Tilføj infoslide til alle sange"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    if args.song is not None:
        args.start = args.song
        args.end = args.song
    
    # Set up logging
    setup_logging()
    logger.info(f"Starter ProPresenter processering for sangbog: {args.book}")
    
    pp_in = Path(args.input_library)
    if not pp_in.exists():
        logger.error(f"Input library ikke fundet: {pp_in}")
        sys.exit(1)
    
    pp_out = Path(args.output_library)
    pp_out.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output sti: {pp_out}")
    
    db_path = Path(args.db)
    if not db_path.exists():
        logger.error(f"Database ikke fundet: {db_path}")
        sys.exit(1)

    book = args.book.upper()
    if book not in VALID_BOOKS:
        logger.error(f"Ukendt sangbog: {book}")
        sys.exit(1)
        
    if args.end is None:
        args.end = max(int(song.name.split()[1].rstrip("a").rstrip("b")) for song in pp_in.glob(f"{book} *.pro"))

    for i in range(args.start, args.end + 1):
        print()
        song_matches = [*pp_in.glob(f"{book} {i:03d} *.pro")]
        if len(song_matches) == 0:
            logger.warning(f"{book} {i:03d} - Eksisterende sang ikke fundet")
            continue
        
        if len(song_matches) > 1:
            #song_file = song_matches[-1]
            song_file = choice("[*] Flere sange matcher, vælg:", song_matches)
        else:
            song_file = song_matches[0]
        
        pres = load_presentation(song_file)
        
        if len(pres.cues) == 0:
            logger.warning(f"{book} {i:03d} - Sangen har ingen slides, springer over")
            continue

        # Fetch song info from database or if not possible, enter manually
        song = load_song(db_path, book, i)
        if song is None:
            logger.error(f"{book} {i:03d} - Sanginfo ikke fundet i database, indtast manuelt:")
            default_title = " - ".join(song_file.stem.split(" - ")[1:])
            title = input(f"Sangtitel (default: \"{default_title}\"): ")
            if title == "":
                title = default_title
            info = []
            j = 1
            while True:
                info_input = input(f"Infolinje {j} (ENTER uden tekst for at stoppe): ")
                if not info_input:
                    break
                info.append(info_input)
                j += 1
            song = Song(book, i, title, info)
            save_song(db_path, song)

        # Set song settings to make all slides identically configured
        set_song_settings(song, pres)
        
        # Create and prepend slide with song information
        if args.add_infoslide:
            # Optionally, replace existing Infoslide if present
            add_infoslide = True
            if pres.cues and pres.cues[0].actions[0].label.text == "Infoslide":
                ans = input("Sangen har allerede et infoslide - udskift? [y/N] ")
                if ans.lower()[0] == "y":
                    # Remove info cue and its identifier
                    del pres.cues[0]
                    del pres.cue_groups[0].cue_identifiers[0]
                else:
                    add_infoslide = False

            if add_infoslide:
                info_slide = make_infoslide(song)
                insert_slide(pres, info_slide, 0)

        # Write result to output library
        out = write_presentation(pp_out, song, pres)
        print(f"[*] {book} {i:03d} opdateret\n    Sti: {out}\n    Info: {str(song).replace("  ", "      ")}")


if __name__ == "__main__":
    main()
