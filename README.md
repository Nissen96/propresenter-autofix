# ProPresenter Infoslides

A tool for automatically adding infoslides to ProPresenter presentations with song metadata from multiple Danish songbooks (DDS, SOS, FS4).

## Structure

```
propresenter/
├── src/
│   ├── propresenter/       # Main package
│   │   ├── __init__.py
│   │   ├── constants.py    # Shared constants
│   │   ├── database.py     # Database operations
│   │   ├── model.py        # Domain models
│   │   ├── utils.py        # Utility functions
│   │   └── info_template.pro  # ProPresenter template
│   └── protobuf/           # ProPresenter protobuf definitions
├── data/                   # Data files for SOS and FS4 scraping
│   ├── sos.sqlite         # SOS songbook database
│   └── fs4.db             # FS4 songbook database
├── main.py                 # Entry point for processing presentations
├── scraper.py              # Entry point for scraping song data
└── pyproject.toml          # Project configuration
```

## Installation

Install the package in editable mode:

```bash
uv sync
```

## Data Setup

For scraping SOS and FS4 songs, you need to place the corresponding database files in the `data/` directory:

- `data/sos.sqlite` - SOS songbook database
- `data/fs4.db` - FS4 songbook database

The DDS scraper fetches data directly from the web and doesn't require local data files.

## Usage

### Scraping Song Data

Scrape song information and save to the database. Supported books: **DDS**, **SOS**, **FS4**.

**DDS (web scraping):**
```bash
python scraper.py --book DDS --start 1 --end 50 --db songs.sqlite
```

**SOS (from local database):**
```bash
python scraper.py --book SOS --start 1 --end 100 --db songs.sqlite
```

**FS4 (from local database):**
```bash
python scraper.py --book FS4 --start 1 --end 50 --db songs.sqlite
```

**Arguments:**
- `--book` (required): Songbook identifier (DDS, SOS, or FS4)
- `--start` (optional, default: 1): Starting song number
- `--end` (required): Ending song number
- `--db` (optional, default: songs.sqlite): Database path

### Processing ProPresenter Files

Apply song information to ProPresenter presentations. The script will:
- Add infoslides with song metadata
- Clean and format slide text
- Normalize font sizes and formatting
- Remove empty or redundant slides
- Standardize slide appearance

**Process all songs:**
```bash
python main.py input_library output_library --book DDS --db songs.sqlite
```

**Process a single song:**
```bash
python main.py input_library output_library --book DDS --song 42 --db songs.sqlite
```

**Process a range:**
```bash
python main.py input_library output_library --book DDS --start 1 --end 50 --db songs.sqlite
```

**Arguments:**
- `input_library` (required): Path to ProPresenter input library
- `output_library` (required): Path to ProPresenter output library
- `--book` (required): Songbook identifier (DDS, SOS, or FS4)
- `--song` (optional): Single song number (alternative to --start/--end)
- `--start` (optional, default: 1): Starting song number
- `--end` (optional): Ending song number (defaults to highest available if omitted)
- `--db` (optional, default: songs.sqlite): Database path

**Interactive Features:**
- If a song already has an infoslide, you'll be prompted to replace it
- If multiple files match a song number, you'll be prompted to choose
- If a slide has only one line, you'll be prompted to remove it
- If font sizes vary, you'll be prompted to choose a consistent size
- If song info isn't in the database, you can enter it manually (it will be saved)

## Features

### Scraping
- **DDS**: Web scraping from dendanskesalmebogonline.dk
  - Extracts title, authors, and melody information
  - Handles missing song text gracefully
- **SOS**: Reads from local SQLite database
  - Extracts title, history, melody, and Bible references
- **FS4**: Reads from local SQLite database
  - Extracts title and author information

### Slide Processing
- **Automatic cleanup**: Removes tabs, formatting artifacts, word explanations, copyright notices
- **Smart filtering**: Removes duplicate info lines, verse markers, and empty slides
- **Text normalization**: Handles special characters and encoding issues
- **Font standardization**: Automatically detects and standardizes font sizes
- **Info slide generation**: Creates formatted infoslides with book, number, title, and metadata
- **Interactive refinement**: Prompts for manual review of ambiguous cases

## Logging

Both scripts use structured logging. Logs are written to:
- Console output (INFO level and above)
- `propresenter.log` file (all levels)

The log file includes timestamps and log levels for easy debugging.

## Modules

- **scraper.py**: Song data scraping from web and databases
- **main.py**: ProPresenter file processing, slide cleanup, and infoslide insertion
- **src/propresenter/**: Shared library code with domain models, database operations, utilities, and constants
