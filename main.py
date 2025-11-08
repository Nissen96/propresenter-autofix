"""Add infoslides and update ProPresenter presentations."""
import argparse
import logging
import re
import sys
import uuid
from enum import Enum
from importlib import resources
from pathlib import Path
from dataclasses import dataclass

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
from propresenter.types import BibleText, FormattedLine, Song
from propresenter.utils import normalize, normalize2, setup_logging

logger = logging.getLogger(__name__)


class ActionType(Enum):
    """ProPresenter action types."""
    STAGE = 1
    MEDIA = 2
    CLEAR = 5
    MESSAGE = 8
    PRESENTATION_SLIDE = 11


def load_presentation(filepath: Path) -> pb.Presentation:
    """Load a ProPresenter presentation from file."""
    pres = pb.Presentation()
    pres.ParseFromString(filepath.read_bytes())
    return pres


def write_presentation(out_dir: Path, pres: pb.Presentation, content: Song | BibleText | None = None, original_name: str | None = None) -> Path:
    """Write presentation to output directory."""
    if content is not None:
        dst = out_dir / content.format_filename()
    elif original_name is not None:
        dst = out_dir / original_name
    else:
        name = pres.name if pres.name else "presentation"
        dst = out_dir / f"{name}.pro"
    dst.write_bytes(pres.SerializeToString())
    return dst


def cleanup_slide_text(lines: list[FormattedLine], intro: bool = False, song: Song | None = None) -> list[FormattedLine]:
    """Clean and normalize slide text lines, keeping formatting info."""
    lines = [line.replace(r"\tab", "").replace(r"\par", "").strip() for line in lines]
    lines = [line.replace("*", "") for line in lines if not line.startswith("*")]
    lines = [line.replace(r"\u8232?", "") for line in lines]
    lines = [line for line in lines if not line.startswith(normalize("©")) and not line.startswith(normalize2("©"))]
    lines = [line for line in lines if not re.match(r"verse?\s*\d+", line.text, re.IGNORECASE)]
    lines = [line.strip() for line in lines]
    
    if intro:
        lines = [line for line in lines if line.text != ""]
    else:
        while lines and lines[0].text in ("", "-", "."):
            lines.pop(0)
        while lines and lines[-1].text in ("", "-", "."):
            lines.pop()
    
    if not intro and song.book and song.number:
        info_lines1 = [normalize(line).lower() for line in song.info]
        info_lines2 = [normalize2(line).lower() for line in song.info]
        lines = [
            line for line in lines
            if not (l := line.lower()).startswith(f"{song.book} {song.number:03d}".lower())
            and not l.startswith(f"{song.book} {song.number}".lower())
            and l.text not in info_lines1
            and l.text not in info_lines2
            and l.text.replace(", ", ". ") not in info_lines1
            and l.text.replace(", ", ". ") not in info_lines2
        ]
    
    if len(lines) == 0:
        return []
    
    if len(lines) > 1 and re.match(r"^\d{,2}\.?$", lines[0].text):
        lines[1].text = f"{lines[0].text.rstrip(".")}. {lines[1].text}"
        del lines[0]
    
    if lines[0].text == "..." and lines[-1].text != "...":
        lines.append(FormattedLine())
    elif lines[-1].text == "..." and lines[0].text != "...":
        lines.insert(0, FormattedLine())
    
    return lines


def generate_slide_rtf(lines: list[FormattedLine], font_size: int = 180) -> str:
    """Generate RTF formatted text for a slide."""
    lines = [f"{line.formatting} {normalize(line.text)}" for line in lines]
    return f"{{\\rtf1\\ansi\\uc1\\deff0{{\\fonttbl{{\\f0\\fnil Arial;}}}}\\pard\\qc\\sa0\\sb0\\fs{font_size}\\f0 " + r"\par".join(lines) + "}"


def set_slide_settings(slide: pb.Slide) -> None:
    """Configure slide appearance and text box settings."""
    slide.size.width = SLIDE_WIDTH
    slide.size.height = SLIDE_HEIGHT
    
    slide.draws_background_color = True
    slide.background_color.red = 1
    slide.background_color.green = 1
    slide.background_color.blue = 1
    slide.background_color.alpha = 1
    
    del slide.elements[1:]
    
    elem = slide.elements[0]
    box = elem.element.bounds
    box.origin.x = SLIDE_MARGIN
    box.origin.y = SLIDE_MARGIN
    box.size.width = SLIDE_WIDTH - 2 * SLIDE_MARGIN
    box.size.height = SLIDE_HEIGHT - 2 * SLIDE_MARGIN
    
    text = elem.element.text
    text.attributes.font.name = TEMPLATE_FONT_NAME
    text.attributes.font.family = TEMPLATE_FONT_FAMILY
    text.attributes.font.face = TEMPLATE_FONT_FACE
    text.attributes.text_solid_fill.red = 0
    text.attributes.text_solid_fill.green = 0
    text.attributes.text_solid_fill.blue = 0
    text.attributes.stroke_width = 0


def extract_font_size(text: pb.Text, default_font_size: int | None) -> int:
    """Extract font size from RTF data, prompting user if multiple sizes found."""
    font_sizes = {int(size) for size in re.findall(r"\\fs(\d+)", text.rtf_data.decode())}
    if len(font_sizes) == 0:
        return 180
    elif len(font_sizes) == 1:
        return int(font_sizes.pop())
    elif default_font_size is not None and default_font_size in font_sizes:
        return default_font_size
    else:
        if default_font_size is not None:
            logger.info(f"Skriftstørrelse fra præsentationens andre slides: {default_font_size // 2}")
            font_sizes.add(default_font_size)
        return choice("Vælg størrelse: ", [size // 2 for size in font_sizes]) * 2


def extract_slide_text(text: pb.Text) -> list[FormattedLine]:
    """Extract text lines with their formatting from RTF data.
    
    Returns list of FormattedLine objects.
    """
    patterns = [
        r"(\\b0?\\i0?\\ul0?\\strike0?).*?\\cb\d+ ?(.*?)(\\par|\})",
        r"(\\b0?\\i0?\\ul0?\\strike0?).*?\\nosupersub ?(.*?)(\\par|\})",
        r"(\\b0?\\i0?\\ul0?\\strike0?).*?\\ltrch ?(.*?)()\}",
        r"\\par(\\b0?\\i0?\\ul0?\\strike0?) ?(.*?)(\\par|\})",
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text.rtf_data.decode())
        if matches:
            return [FormattedLine(formatting=match[0], text=match[1].strip()) for match in matches]
    return []


def process_slide(
    cue: pb.Cue,
    slide_index: int,
    total_slides: int,
    song: Song | None,
    presentation_name: str,
    default_font_size: int | None,
    add_dash_to_last: bool,
    check_single_lines: bool,
) -> tuple[int | None, bool]:
    """Process a single slide, returning new font size and whether slide should be kept."""
    action = cue.actions[0]
    if ActionType(action.type) != ActionType.PRESENTATION_SLIDE:
        return default_font_size, True
    
    action.isEnabled = True
    action.slide.presentation.ClearField("transition")
    
    base_slide = action.slide.presentation.base_slide
    set_slide_settings(base_slide)
    
    text = base_slide.elements[0].element.text
    font_size = extract_font_size(text, default_font_size)
    
    formatted_lines = extract_slide_text(text)
    cleaned_lines = cleanup_slide_text(formatted_lines, intro=False, song=song)
    
    if len(cleaned_lines) == 0:
        log_name = f"{song.book} {song.number:03d}" if song and song.book and song.number else presentation_name
        logger.warning(f"{log_name} - Slide {slide_index + 1} er tomt efter cleanup og fjernes")
        return default_font_size, False
    
    if check_single_lines and len(cleaned_lines) == 1:
        log_name = f"{song.book} {song.number:03d}" if song and song.book and song.number else presentation_name
        logger.info(f"{log_name} - Slide {slide_index + 1} har kun én linje:\n    \"{cleaned_lines[0].text}\"")
        ans = input("Fjern dette slide? [Y/n] ")
        if not ans or ans[0].lower() != "n":
            logger.warning(f"{log_name} - Slide {slide_index + 1} fjernes")
            return default_font_size, False
    
    if slide_index == total_slides - 1 and add_dash_to_last:
        if cleaned_lines[0].text == "...":
            cleaned_lines[-1] = FormattedLine(text="-")
        else:
            cleaned_lines.append(FormattedLine(text="-"))
            cleaned_lines.insert(0, FormattedLine())

    text.rtf_data = generate_slide_rtf(cleaned_lines, font_size=font_size).encode()
    return font_size, True


def cleanup_slides(
    pres: pb.Presentation,
    song: Song | None = None,
    presentation_name: str = "",
    add_dash_to_last: bool = True,
    check_single_lines: bool = False,
) -> None:
    """Clean up and standardize all slides in the presentation."""
    default_font_size = None
    identifiers = [
        identifier
        for cue_group in pres.cue_groups
        for identifier in cue_group.cue_identifiers
    ]
    
    total_slides = len(pres.cues)
    kept_cues = []
    kept_identifiers = []
    
    for i in range(len(pres.cues) - 1, -1, -1):
        cue = pres.cues[i]
        cue.isEnabled = True
        
        for j in range(len(cue.actions) - 1, -1, -1):
            action = cue.actions[j]
            action_type = ActionType(action.type)
            
            if action_type is ActionType.PRESENTATION_SLIDE:
                new_font_size, keep = process_slide(
                    cue, i, total_slides, song, presentation_name, default_font_size,
                    add_dash_to_last=add_dash_to_last, check_single_lines=check_single_lines,
                )
                if keep:
                    default_font_size = new_font_size
                    kept_cues.insert(0, cue)
                    if i < len(identifiers):
                        kept_identifiers.insert(0, identifiers[i])
                break
            elif action_type in [ActionType.MEDIA, ActionType.MESSAGE, ActionType.CLEAR, ActionType.STAGE]:
                del cue.actions[j]
    
    pres.ClearField("cues")
    for cue in kept_cues:
        pres.cues.add().CopyFrom(cue)
    pres.ClearField("cue_groups")
    pres.cue_groups.add()
    for identifier in kept_identifiers:
        pres.cue_groups[0].cue_identifiers.append(identifier)
    
    if len(pres.cues) == 0:
        log_name = f"{song.book} {song.number:03d}" if song and song.book and song.number else presentation_name
        logger.warning(f"{log_name} - Præsentationen har ingen slides efter cleanup")


def make_infoslide_from_content(content_lines: list[FormattedLine]) -> Cue:
    """Create an infoslide cue from content lines."""
    template_path = resources.files("propresenter") / "info_template.pro"
    with resources.as_file(template_path) as path:
        info_pres = load_presentation(path)
    
    cue = info_pres.cues[0]
    cue.uuid.string = str(uuid.uuid4())
    cue.name = ""
    
    slide = cue.actions[0].slide.presentation.base_slide
    set_slide_settings(slide)
    
    all_info = cleanup_slide_text(content_lines, intro=True)
    text = slide.elements[0].element.text
    text.rtf_data = generate_slide_rtf(all_info).encode()
    
    for _ in range(len(all_info)):
        text.attributes.custom_attributes.add()
    
    pos = 0
    sizes = [150, 100] + [70] * (len(all_info) - 2)
    for attr, info, size in zip(text.attributes.custom_attributes, all_info, sizes, strict=True):
        attr.range.start = pos
        attr.range.end = pos + len(info)
        attr.original_font_size = size
        pos += len(info) + 1
    
    cue.actions[0].label.text = "Infoslide"
    text.scale_behavior = pb.action__pb2.graphicsData__pb2._GRAPHICS_TEXT_SCALEBEHAVIOR.values_by_name["SCALE_BEHAVIOR_SCALE_FONT_DOWN"].number
    
    return cue


def insert_cue(pres: pb.Presentation, cue: Cue, index: int) -> None:
    """Insert cue at the given index."""
    pres.cues.insert(index, cue)
    if len(pres.cue_groups) == 0:
        pres.cue_groups.add()
    if len(pres.cue_groups[0].cue_identifiers) > 0:
        template = pres.cue_groups[0].cue_identifiers[0]
        new_id = pres.cue_groups[0].cue_identifiers.add()
        new_id.CopyFrom(template)
        new_id.string = cue.uuid.string
        identifiers = list(pres.cue_groups[0].cue_identifiers)
        identifiers.insert(index, identifiers.pop())
        pres.cue_groups[0].cue_identifiers.clear()
        pres.cue_groups[0].cue_identifiers.extend(identifiers)
    else:
        new_id = pres.cue_groups[0].cue_identifiers.add()
        new_id.string = cue.uuid.string


def choice(prompt: str, choices: list[str | int]) -> str | int:
    """Prompt user to choose from a list of options."""
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


def extract_song_from_filename(filename: Path, pres: pb.Presentation, book: str | None = None, number: int | None = None) -> Song:
    """Extract song information from filename and presentation."""
    stem = filename.stem
    
    if book and number:
        match = re.match(fr"^\s*({re.escape(book)})\s*(0*{number})\s*[-:]?\s*(.+)$", stem, re.IGNORECASE)
    elif book:
        match = re.match(fr"^\s*({re.escape(book)})\s*(\d+)\s*[-:]?\s*(.+)$", stem, re.IGNORECASE)
    else:
        match = re.match(r"^\s*([a-z]+)\s*(\d+)\s*[-:]?\s*(.+)$", stem, re.IGNORECASE)

    if match:
        book = match.group(1).upper()
        number = int(match.group(2))
        title = match.group(3)
    else:
        book = None
        number = None
        title = pres.name if pres.name else stem

    return Song(book=book, number=number, title=title, info=[])


def load_song_content(db_path: Path | None, filename: Path, pres: pb.Presentation, book: str | None = None, number: int | None = None) -> Song:
    """Load song content from database or extract from filename."""
    if db_path and db_path.exists() and book and number:
        content = Song.load_from_db(db_path, book, number)
        if content:
            return content
    
    return extract_song_from_filename(filename, pres, book, number)


def find_presentation_files(input_dir: Path, book: str | None, number: int | None) -> list[Path]:
    """Find presentation files matching the given criteria."""
    if book and number is not None:
        patterns = Song.get_file_patterns(book, number)
    elif book:
        patterns = Song.get_all_file_patterns(book)
    else:
        patterns = ["*.pro"]
    
    files = []
    for pattern in patterns:
        files.extend(input_dir.glob(pattern, case_sensitive=False))
    files = sorted(set(files))
    
    if book:
        files.sort(key=lambda f: Song.extract_number_from_filename(book, f.name) or 0)
    
    return files


def process_single_presentation(pres_file: Path, pres: pb.Presentation, output_dir: Path, content: Song | BibleText, add_infoslide: bool) -> None:
    """Process a single presentation file with the given content."""
    if len(pres.cues) == 0:
        logger.warning(f"{pres_file.name} - Ingen slides, springer over")
        return
    
    content.set_ccli_info(pres)
    pres.name = content.format_presentation_name()
    
    if isinstance(content, Song):
        if content.book and content.number:
            presentation_name = f"{content.book} {content.number:03d}"
        else:
            presentation_name = content.title
    else:
        presentation_name = content.reference
    
    cleanup_slides(
        pres,
        song=content if isinstance(content, Song) else None,
        presentation_name=presentation_name,
        add_dash_to_last=content.should_add_dash_to_last_slide(),
    )
    
    if add_infoslide:
        should_add = True
        if pres.cues and pres.cues[0].actions[0].label.text == "Infoslide":
            ans = input("Præsentationen har allerede et infoslide - udskift? [y/N] ")
            if ans and ans.lower()[0] == "y":
                del pres.cues[0]
                del pres.cue_groups[0].cue_identifiers[0]
            else:
                should_add = False
        
        if should_add:
            slide_content = content.get_info_slide_content()
            info_cue = make_infoslide_from_content(slide_content)
            insert_cue(pres, info_cue, 0)
    
    out = write_presentation(output_dir, pres, content=content)
    if isinstance(content, Song):
        if content.book and content.number:
            logger.info(f"[*] {content.book} {content.number:03d} opdateret\n    Sti: {out}\n    Info: {content.title}")
        else:
            logger.info(f"[*] {content.title} opdateret\n    Sti: {out}")
    else:
        logger.info(f"[*] {pres.name} opdateret\n    Sti: {out}")


def process_songs(
    input_dir: Path,
    output_dir: Path,
    db_path: Path | None,
    book: str | None,
    start: int | None,
    end: int | None,
    add_infoslide: bool,
) -> None:
    """Process song presentations."""
    if add_infoslide and (not db_path or not db_path.exists()):
        logger.warning("--add-infoslide kræver database, men databasen eksisterer ikke. Fortsætter uden infoslides.")
        add_infoslide = False

    if start is not None and end is not None:
        for number in range(start, end + 1):
            files = find_presentation_files(input_dir, book, number)
            if not files:
                logger.warning(f"{book or ''} {number or ''} - Præsentation ikke fundet")
                continue
            if len(files) > 1:
                pres_file = choice("[*] Flere præsentationer matcher, vælg:", files)
            else:
                pres_file = files[0]

            pres = load_presentation(pres_file)
            content = load_song_content(db_path, pres_file, pres, book, number)
            process_single_presentation(pres_file, pres, output_dir, content, add_infoslide)
    else:
        files = find_presentation_files(input_dir, book, None)
        if not files:
            logger.warning("Ingen præsentationer fundet")
            return

        if book:
            files.sort(key=lambda f: Song.extract_number_from_filename(book, f.name) or 0)
        else:
            files.sort()

        for pres_file in files:
            logger.info(f"Behandler: {pres_file.name}")

            if book:
                number = Song.extract_number_from_filename(book, pres_file.name)
                if number is None:
                    logger.warning(f"{pres_file.name} - Kunne ikke ekstrahere sangnummer")
                    continue
            else:
                number = None
            
            pres = load_presentation(pres_file)
            content = load_song_content(db_path, pres_file, pres, book, number)
            process_single_presentation(pres_file, pres, output_dir, content, add_infoslide)


def process_bible_texts(
    input_dir: Path,
    output_dir: Path,
    db_path: Path | None,
) -> None:
    """Process Bible text presentations."""
    files = sorted(input_dir.glob("*.pro", case_sensitive=False))
    if not files:
        logger.warning("Ingen Bible præsentationer fundet")
        return
    
    logger.info(f"Fundet {len(files)} Bible præsentation(er)")
    
    for pres_file in files:
        logger.info(f"Behandler: {pres_file.name}")
        
        pres = load_presentation(pres_file)
        
        if len(pres.cues) == 0:
            logger.warning(f"{pres_file.name} - Ingen slides, springer over")
            continue
        
        reference = pres_file.stem.replace("Bible ", "").strip()
        content = BibleText.load_from_db(db_path, reference) if db_path and db_path.exists() else None
        if content is None:
            content = BibleText(reference=reference)
        
        process_single_presentation(pres_file, pres, output_dir, content, add_infoslide=False)


def process_cleanup(input_dir: Path, output_dir: Path, add_end_dash: bool, check_single_lines: bool) -> None:
    """Clean up all presentations in input directory without database."""
    logger.info(f"Renser alle præsentationer i: {input_dir}")
    
    presentation_files = sorted(input_dir.glob("*.pro", case_sensitive=False))
    if not presentation_files:
        logger.warning(f"Ingen .pro filer fundet i {input_dir}")
        return
    
    logger.info(f"Fundet {len(presentation_files)} præsentation(er)")
    
    for pres_file in presentation_files:
        logger.info(f"Behandler: {pres_file.name}")
        
        try:
            pres = load_presentation(pres_file)
            
            if len(pres.cues) == 0:
                logger.warning(f"{pres_file.name} - Ingen slides, springer over")
                continue
            
            cleanup_slides(
                pres,
                song=None,
                presentation_name=pres_file.stem,
                add_dash_to_last=add_end_dash,
                check_single_lines=check_single_lines,
            )
            out = write_presentation(output_dir, pres, original_name=pres_file.name)
            logger.info(f"Opdateret: {out}")
            
        except Exception as e:
            logger.error(f"Fejl ved behandling af {pres_file.name}: {e}", exc_info=True)


def find_missing_songs(input_dir: Path, book: str | None, start: int, end: int | None) -> None:
    """Find missing songs in the specified range."""
    if book is None:
        book = input_dir.name.split(" ")[0]
    if end is None:
        logger.info(f"Søger efter manglende sange for {book} fra {start} til sidste præsentation")
    else:
        logger.info(f"Søger efter manglende sange for {book} fra {start} til {end}")
    
    existing_files = []
    for pattern in Song.get_all_file_patterns(book):
        existing_files.extend(input_dir.glob(pattern, case_sensitive=False))
    existing_files = sorted(existing_files, key=lambda f: Song.extract_number_from_filename(book, f.name) or 0)
    
    found_numbers = set()
    for f in existing_files:
        num = Song.extract_number_from_filename(book, f.name)
        if num is not None:
            found_numbers.add(num)
    
    if not found_numbers:
        logger.warning(f"Ingen sange fundet for {book}")
        return
    
    if end is None:
        end = max(found_numbers)
    
    expected_numbers = set(range(start, end + 1))
    missing_numbers = sorted(expected_numbers - found_numbers)
    
    if missing_numbers:
        logger.info(f"\n[*] Manglende sange for {book}:")
        for num in missing_numbers:
            logger.info(f"    {book} {num:03d}")
        logger.info(f"\nTotal manglende: {len(missing_numbers)} af {len(expected_numbers)}")
    else:
        logger.info(f"\n[✓] Alle sange fra {start} til {end} er til stede for {book}")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="propresenter",
        description="Rens og opdater ProPresenter præsentationer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Eksempler:
  # Rens alle præsentationer i en mappe (ingen database nødvendig)
  propresenter cleanup input/ output/

  # Find manglende sange
  propresenter find-missing input/ --book DDS --start 1 --end 791

  # Processer sange fra database med infoslides
  propresenter song input/ output/ --book DDS --start 1 --end 50 --add-infoslide

  # Processer en enkelt sang
  propresenter song input/ output/ --book DDS --song 42 --add-infoslide

  # Processer alle sange i en mappe (ingen book/number nødvendig)
  propresenter song input/ output/

  # Processer alle Bible tekster
  propresenter bible input/ output/
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Kommando", required=True)
    
    cleanup_parser = subparsers.add_parser("cleanup", help="Rens alle præsentationer i input mappen")
    cleanup_parser.add_argument("input_library", type=str, help="Sti til ProPresenter input library")
    cleanup_parser.add_argument("output_library", type=str, help="Sti til ProPresenter output library")
    cleanup_parser.add_argument("--add-end-dash", action="store_true", help="Tilføj dash til sidste slide")
    cleanup_parser.add_argument("--check-single-lines", action="store_true", help="Tjek for slides med kun én linje")
    
    find_missing_parser = subparsers.add_parser("find-missing", help="Find manglende sange i et interval")
    find_missing_parser.add_argument("input_library", type=str, help="Sti til ProPresenter library for sangbog")
    find_missing_parser.add_argument("--book", type=str, help="Sangbog (tages fra input library hvis udeladt)")
    find_missing_parser.add_argument("--start", type=int, default=1, help="Start sangnummer (default: %(default)s)")
    find_missing_parser.add_argument("--end", type=int, help="Slut sangnummer (udelad for alle)")
    
    song_parser = subparsers.add_parser("song", help="Processer sang præsentationer")
    song_parser.add_argument("input_library", type=str, help="Sti til ProPresenter input library")
    song_parser.add_argument("output_library", type=str, help="Sti til ProPresenter output library")
    song_parser.add_argument("--book", type=str, help="Sangbog (e.g. DDS, SOS, FS4)")
    song_parser.add_argument("--song", type=int, help="Sangnummer (brug sammen med --book)")
    song_parser.add_argument("--start", type=int, help="Start sangnummer (brug sammen med --book)")
    song_parser.add_argument("--end", type=int, help="Slut sangnummer (brug sammen med --book)")
    song_parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Database sti (default: %(default)s)")
    song_parser.add_argument("--add-infoslide", action="store_true", help="Tilføj infoslide (kræver database)")
    
    bible_parser = subparsers.add_parser("bible", help="Processer alle Bible tekst præsentationer")
    bible_parser.add_argument("input_library", type=str, help="Sti til ProPresenter input library")
    bible_parser.add_argument("output_library", type=str, help="Sti til ProPresenter output library")
    bible_parser.add_argument("--db", type=str, default=DEFAULT_DB_PATH, help="Database sti (default: %(default)s)")
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    setup_logging()
    
    pp_in = Path(args.input_library)
    if not pp_in.exists():
        logger.error(f"Input library ikke fundet: {pp_in}")
        sys.exit(1)
    
    if args.command != "find-missing":
        pp_out = Path(args.output_library)
        pp_out.mkdir(parents=True, exist_ok=True)
        logger.info(f"Output sti: {pp_out}")
    
    if args.command == "cleanup":
        process_cleanup(pp_in, pp_out, args.add_end_dash, args.check_single_lines)
    
    elif args.command == "find-missing":
        find_missing_songs(pp_in, args.book, args.start, args.end)
    
    elif args.command == "song":
        db_path = Path(args.db) if args.db else None
        if db_path and not db_path.exists():
            logger.error(f"Database ikke fundet: {db_path}")
            sys.exit(1)
        if args.song is not None:
            if not args.book:
                logger.error("--song kræver --book")
                sys.exit(1)
            process_songs(pp_in, pp_out, db_path, args.book, args.song, args.song, args.add_infoslide)
        elif args.start is not None or args.end is not None:
            if not args.book:
                logger.error("--start/--end kræver --book")
                sys.exit(1)
            process_songs(pp_in, pp_out, db_path, args.book, args.start, args.end, args.add_infoslide)
        else:
            process_songs(pp_in, pp_out, db_path, args.book, None, None, args.add_infoslide)
    
    elif args.command == "bible":
        db_path = Path(args.db) if args.db else None
        process_bible_texts(pp_in, pp_out, db_path)


if __name__ == "__main__":
    main()
