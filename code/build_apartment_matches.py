#!/usr/bin/env python3
# AUTHOR: Chinmay and AI
"""Build an Excel workbook per apartment from voter and roster files in CSV or XLSX.

Read the voter list name and filename on the first row of the apartment list, followed by
apartment names, roster filenames, and optional alternate names separated by semicolons.
Standardize source rosters in memory and label each output row with the voter list searched.
Recognize any configured name for the apartment in voter addresses.
The workbook lists assigned voters, unassigned voters alongside households without a unit
link, and roster rows that no voter row is connected through.
Relation and household links require a voter directly matched to the same flat.
Two people linked on the voter roll can corroborate each other's roster matches.
Rank competing voter records for each roster person by name score and booth support.
Show match strength in the voter sheets, shade voter rows, and separate flats with dark borders.
Select links through named-apartment section evidence, corroborated related pairs,
an exact multiword own name and full flat, or a guarded 95% score in a named section.
Recover uncontested full-word matches at explicitly named buildings and complete flats.
Freeze support counts, competing rankings and Strong/Medium qualifications on the first
resolved pool, then rebuild actual dependent links using surviving own-name voters.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from copy import copy
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations, groupby
from pathlib import Path
from textwrap import wrap
from typing import Iterable

import pandas as pd
from openpyxl.styles import Alignment, PatternFill, Side
from openpyxl.utils import get_column_letter

import matching as matcher


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_APARTMENTS_CSV = PROJECT_ROOT / "data" / "apartments.csv"
DEFAULT_VOTER_CSV = PROJECT_ROOT / "data" / "voters.csv"
INPUT_FILE_EXTENSIONS = (".csv", ".xlsx")
UNIT_PAD_WIDTH = 3
ALGORITHM_VERSION = "named-section-95-v1"

VOTER_OUTPUT_COLUMNS = [
    "serial_number",
    "epic_number",
    "voter_name",
    "relation_type",
    "relation_name",
    "house_number",
    "age",
    "gender",
    "section_raw",
    "part",
    "ward",
    "corporation",
    "pincode",
    "pollingname",
    "pollingaddress",
]

APARTMENT_UNIT_COLUMNS = [
    "apartment",
    "apartment_unit",
    "apartment_block",
    "apartment_unit_part",
]

MATCH_DETAIL_COLUMNS = [
    "apartment_status",
    "apartment_connection",
    "part_name_match",
    "name_match_pct",
    "other_hh_matched_booth",
    "other_hh_matched_section_in_part",
    "other_named_flats_in_section",
    "voter_link_type",
]

VOTER_NAME_COLUMNS = ["voter_name", "relation_type", "relation_name"]
VOTER_DETAIL_COLUMNS = [
    *VOTER_NAME_COLUMNS,
    *[column for column in VOTER_OUTPUT_COLUMNS if column not in VOTER_NAME_COLUMNS],
]
OUTPUT_COLUMNS = [*APARTMENT_UNIT_COLUMNS, *MATCH_DETAIL_COLUMNS, *VOTER_DETAIL_COLUMNS]
MAPPED_OUTPUT_COLUMNS = [
    "apartment",
    "apartment_unit",
    "strength",
    "voter_name",
    "apartment_connection",
    *[column for column in VOTER_DETAIL_COLUMNS if column != "voter_name"],
    *[column for column in MATCH_DETAIL_COLUMNS if column != "apartment_connection"],
    "apartment_block",
    "apartment_unit_part",
]

# Workbook sheets and columns for the household-level address report.
VOTERS_SHEET = "voters_mapped_tohouse"
UNMAPPED_HOUSEHOLDS_SHEET = "voters_unmapped"
ROSTER_NOT_MATCHED_SHEET = "not_found_in_voterlist"
UNMAPPED_HOUSEHOLD_COLUMNS = [
    "household_id",
    "house_number",
    "part",
    "section_raw",
    "pollingname",
    "voter_count",
    "voter_serial_numbers",
]
UNMAPPED_OUTPUT_COLUMNS = list(dict.fromkeys([
    *UNMAPPED_HOUSEHOLD_COLUMNS, *APARTMENT_UNIT_COLUMNS, "strength", *MATCH_DETAIL_COLUMNS, *VOTER_DETAIL_COLUMNS,
]))
MAX_EXCEL_COLUMN_WIDTH = 50
CONFIDENCE_COLORS = {
    "Strong": "FFDCEFE0",
    "Probable": "FFDEECF9",
    "Needs review": "FFF0F1F3",
}
HOUSEHOLD_BORDER = Side(style="medium", color="FF344054")

# Statuses reported on the second sheet.
UNMAPPED_STATUS = "Unmapped"
UNASSIGNED_STATUS = "Unassigned"

# Which roster person a row is connected through, in order of preference.
CONNECTION_PRIORITY_VOTER_NAME = 1
CONNECTION_PRIORITY_RELATION_NAME = 2
CONNECTION_PRIORITY_HOUSEHOLD_MEMBER = 3

INDIVIDUAL_RELATED_COLUMNS = [
    "serial_number",
    "epic_number",
    "voter_name",
    "relation_type",
    "relation_name",
    "age",
    "gender",
]

HOUSEHOLD_RELATED_COLUMNS = [
    "house_number",
    "section_raw",
    "part",
    "ward",
    "corporation",
    "pincode",
    "pollingname",
    "pollingaddress",
    "apartment",
    "apartment_unit",
    "apartment_block",
    "apartment_unit_part",
    "apartment_status",
    "apartment_connection",
    "part_name_match",
    "name_match_pct",
    "other_hh_matched_booth",
    "voter_link_type",
]

LINK_TYPES = [
    "voter_name_match",
    "relation_name_match",
    "explicit_apartment_address",
    "same_address_household_member",
]

STANDARD_ROSTER_COLUMNS = [
    "apartment_key",
    "unit",
    "block",
    "unit_part",
    "name",
    "status",
]

# Source workbook columns used by the original roster converters.
EXCEL_ROSTER_COLUMNS = {
    "concorde": {"House #": "unit_part", "Block": "block", "Name": "name", "Residency": "status"},
    "purnima": {"Flat #": "unit", "Name": "name", "Status": "status"},
    "silicon_oasis": {"Flat No.": "unit", "Name": "name", "Status": "status"},
}

KNOWN_APARTMENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "concorde": ("Concorde Midway", ("CITY",)),
    "purnima": ("Purnima Classic", ()),
    "silicon_oasis": ("Silicon Oasis", ("WING", "TOWER", "VILLA", "ROW")),
    "tirumala_vintage": (
        "Tirumala Vintage",
        ("SRI", "SHRI", "APPARTMENT", "APPARTMENTS", "APPARTMEN", "APARTMEN", "APA"),
    ),
}

# Alternate labels select the same roster reader.
ROSTER_LABEL_KEYS = {
    "concorde_midway_city": "concorde",
    "sobha_silicon_oasis": "silicon_oasis",
    "sri_tirumala_vintage": "tirumala_vintage",
    "shri_tirumala_vintage": "tirumala_vintage",
}

APARTMENT_CONFIG_REQUIRED_COLUMNS = ["apartment_name", "roster_path"]
APARTMENT_LIST_COLUMNS = [*APARTMENT_CONFIG_REQUIRED_COLUMNS, "alternate_names"]

APARTMENT_CONFIG_COLUMNS = [
    "key",
    *APARTMENT_LIST_COLUMNS,
    "extra_filler_terms",
    "voter_csv",
]

COMMON_ADDRESS_FILLERS = [
    "H",
    "HOUSE",
    "FLAT",
    "F",
    "NO",
    "NUMBER",
    "NUM",
    "DOOR",
    "APT",
    "APARTMENT",
    "APARTMENTS",
    "BLOCK",
    "ROAD",
    "RD",
    "MAIN",
    "ROOM",
    "FLOOR",
    "FLR",
    "TH",
    "ST",
    "ND",
    "RD",
]

FLOOR_RE = re.compile(r"\b\d+\s*(?:ST|ND|RD|TH)?\s*(?:FLOOR|FLR)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ApartmentConfig:
    key: str
    apartment_name: str
    roster_path: Path
    extra_filler_terms: tuple[str, ...] = ()
    alternate_names: tuple[str, ...] = ()

    @property
    def address_names(self) -> tuple[str, ...]:
        return (self.apartment_name, *self.alternate_names)


def split_config_terms(value: object) -> tuple[str, ...]:
    text = matcher.normalize_space(value)
    if not text:
        return ()
    return tuple(
        matcher.normalize_space(term)
        for term in text.split(";")
        if matcher.normalize_space(term)
    )


def resolve_config_path(value: object, base_dir: Path, default: Path | None = None) -> Path:
    text = str(value).strip()
    if not text:
        if default is not None:
            return default
        raise ValueError("missing path")

    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path


def load_apartment_configs(apartments_csv: Path) -> dict[str, ApartmentConfig]:
    """Read apartment rows for callers that supply their own voter CSV."""
    configs, _, _ = _load_apartment_run_config(apartments_csv)
    return configs


def apartment_key(apartment_name: str) -> str:
    """Use the existing key for a known apartment or form a key from its name."""
    decomposed_name = unicodedata.normalize("NFKD", apartment_name)
    name_without_accents = "".join(char for char in decomposed_name if not unicodedata.combining(char))
    slug = re.sub(r"[^a-z0-9]+", "_", name_without_accents.lower()).strip("_")
    for key, (name, _) in KNOWN_APARTMENTS.items():
        if slug == name.lower().replace(" ", "_"):
            return key
    return ROSTER_LABEL_KEYS.get(slug, slug)


def _read_apartment_list(path: Path) -> tuple[list[tuple[int, dict[str, str]]], Path | None, str]:
    """Read the voter list name and path, followed by apartment rows."""
    if not path.is_file():
        raise SystemExit(f"Apartment list not found: {path}")

    try:
        if path.suffix.lower() == ".xlsx":
            sheet = pd.read_excel(path, header=None, dtype=str, keep_default_na=False)
            rows = sheet.to_numpy().tolist()
        else:
            with path.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.reader(source, strict=True))
    except (csv.Error, OSError, ValueError) as error:
        raise SystemExit(f"Cannot read apartment list {path}: {error}") from error

    first = rows[0] if rows else []
    headed_layout = len(first) > 1 and any(column in first for column in APARTMENT_CONFIG_REQUIRED_COLUMNS)
    voter_file = None
    searched_voter_list = ""
    if headed_layout:
        columns = first
        missing = [column for column in APARTMENT_CONFIG_REQUIRED_COLUMNS if column not in columns]
        if missing:
            raise SystemExit(f"{path} is missing required columns: {', '.join(missing)}")
    else:
        if not first or not first[0].strip() or any(value.strip() for value in first[2:]):
            raise SystemExit(f"{path} row 1 must contain the voter list name and filename")
        if len(first) > 1 and first[1].strip():
            searched_voter_list = first[0].strip()
            voter_file = resolve_config_path(first[1], path.parent)
        else:
            # Earlier setup files use only the voter filename in the first row.
            voter_file = resolve_config_path(first[0], path.parent)
        columns = APARTMENT_LIST_COLUMNS

    apartment_rows = []
    for row_number, values in enumerate(rows[1:], start=2):
        if not any(value.strip() for value in values):
            continue
        if not headed_layout and (len(values) < 2 or any(value.strip() for value in values[3:])):
            raise SystemExit(
                f"{path} row {row_number} must contain an apartment name, roster filename, "
                "and optional alternate names in column C"
            )
        row = dict.fromkeys(columns, "")
        row.update(zip(columns, values))
        apartment_rows.append((row_number, row))
    return apartment_rows, voter_file, searched_voter_list


def _load_apartment_run_config(apartments_csv: Path) -> tuple[dict[str, ApartmentConfig], Path | None, str]:
    """Resolve roster paths and the voter file relative to the apartment list."""
    rows, voter_csv, searched_voter_list = _read_apartment_list(apartments_csv)
    base_dir = apartments_csv.parent
    configs: dict[str, ApartmentConfig] = {}
    for display_row_number, row in rows:
        apartment_name = matcher.normalize_space(row["apartment_name"])
        roster_path_text = row["roster_path"].strip()

        missing_values = []
        if not apartment_name:
            missing_values.append("apartment_name")
        if not roster_path_text:
            missing_values.append("roster_path")
        if missing_values:
            raise SystemExit(
                f"{apartments_csv} row {display_row_number} is missing: {', '.join(missing_values)}"
            )

        key = matcher.normalize_space(row.get("key", "")) or apartment_key(apartment_name)
        if not key:
            raise SystemExit(f"{apartments_csv} row {display_row_number} needs a key for this apartment name")
        if key in configs:
            raise SystemExit(f"{apartments_csv} has duplicate key: {key}")

        # Honor an explicit blank so a saved configuration can opt out of the preset fillers.
        filler_terms = row.get("extra_filler_terms")
        extra_filler_terms = (
            split_config_terms(filler_terms)
            if filler_terms is not None
            else KNOWN_APARTMENTS.get(key, ("", ()))[1]
        )
        configs[key] = ApartmentConfig(
            key=key,
            apartment_name=apartment_name,
            roster_path=resolve_config_path(roster_path_text, base_dir),
            extra_filler_terms=extra_filler_terms,
            alternate_names=split_config_terms(row.get("alternate_names", "")),
        )

        voter_csv_text = row.get("voter_csv", "").strip()
        if voter_csv_text:
            row_voter_csv = resolve_config_path(voter_csv_text, base_dir)
            if voter_csv is not None and voter_csv.resolve() != row_voter_csv.resolve():
                raise SystemExit(f"{apartments_csv} row {display_row_number} names a different voter CSV")
            if voter_csv is None:
                voter_csv = row_voter_csv

    if not configs:
        raise SystemExit(f"{apartments_csv} does not contain any apartment rows")
    return configs, voter_csv, searched_voter_list


def compile_terms_re(terms: Iterable[str], *, allow_joined_words: bool = True) -> re.Pattern[str]:
    separator = r"\s*" if allow_joined_words else " "
    patterns: list[str] = []
    for term in terms:
        normalized = matcher.normalize_address(term)
        if not normalized:
            continue
        phrase = separator.join(re.escape(part) for part in normalized.split())
        patterns.append(rf"\b{phrase}\b")
    if not patterns:
        return re.compile(r"a^")
    return re.compile("|".join(patterns), re.IGNORECASE)


def has_target_label(value: object, label_re: re.Pattern[str]) -> bool:
    return bool(label_re.search(matcher.normalize_address(value)))


def normalize_block(value: object) -> str:
    text = matcher.normalize_address(value)
    return "".join(text.split())


def normalize_unit_part(value: object, width: int) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip().upper()
    text = text.replace("'", "")
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"[^A-Z0-9/]+", "", text)
    if not text:
        return ""
    if text.isdigit():
        return f"{int(text):0{width}d}"
    match = re.fullmatch(r"([A-Z]+)(\d+)", text)
    if match:
        return f"{match.group(1)}{int(match.group(2)):0{width}d}"
    match = re.fullmatch(r"(\d+)([A-Z]+)", text)
    if match:
        return f"{match.group(2)}{int(match.group(1)):0{width}d}"
    return text


def split_unit_part(value: str, width: int) -> tuple[str, str, int | None]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", value)
    if match:
        number = int(match.group(2))
        return match.group(1), f"{number:0{width}d}", number
    if value.isdigit():
        return "", f"{int(value):0{width}d}", int(value)
    return "", value, None


def canonical_standard_roster_unit(row: pd.Series) -> tuple[str, str, str, int | None]:
    block = normalize_block(row.get("block", ""))
    raw_unit = normalize_unit_part(row.get("unit", ""), UNIT_PAD_WIDTH)
    raw_unit_part = normalize_unit_part(row.get("unit_part", ""), UNIT_PAD_WIDTH)

    if raw_unit:
        parsed_block, unit_part, unit_number = split_unit_part(raw_unit, UNIT_PAD_WIDTH)
        block = parsed_block or block
        unit = f"{block}{unit_part}" if block else unit_part
        return block, unit_part, unit, unit_number

    if raw_unit_part:
        parsed_block, unit_part, unit_number = split_unit_part(raw_unit_part, UNIT_PAD_WIDTH)
        block = parsed_block or block
        unit = f"{block}{unit_part}" if block else unit_part
        return block, unit_part, unit, unit_number

    return block, "", "", None


def normalize_address_for_units(value: object) -> str:
    text = str(value) if pd.notna(value) else ""
    text = text.replace("'", " ")
    text = text.replace(".", " ")
    text = re.sub(r"([A-Za-z])\s*/\s*([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])\s*/\s*([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"\s*/\s*", "/", text)
    text = re.sub(r"[^A-Za-z0-9/]+", " ", text).upper()
    return matcher.normalize_space(text)


def filler_re_for_config(config: ApartmentConfig, valid_blocks: set[str]) -> re.Pattern[str]:
    filler_terms = (*COMMON_ADDRESS_FILLERS, config.apartment_name, *config.extra_filler_terms)
    if config.alternate_names:
        # Strip entire apartment names before shorter aliases and generic words such as "Apartment".
        names = sorted(config.address_names, key=lambda name: len(matcher.normalize_address(name)), reverse=True)
        filler_terms = (*names, *COMMON_ADDRESS_FILLERS, *config.extra_filler_terms)
    terms: list[str] = []
    for term in filler_terms:
        normalized = matcher.normalize_address(term)
        if normalized in valid_blocks:
            continue
        terms.append(term)
    return compile_terms_re(terms)


def strip_address_fillers(value: object, config: ApartmentConfig, filler_re: re.Pattern[str]) -> str:
    text = normalize_address_for_units(value)
    text = FLOOR_RE.sub(" ", text)
    text = filler_re.sub(" ", text)
    return matcher.normalize_space(re.sub(r"[^A-Z0-9/]+", " ", text))


def build_block_aliases(valid_blocks: set[str]) -> dict[str, str]:
    aliases_by_token: dict[str, set[str]] = {}
    for block in valid_blocks:
        normalized = normalize_block(block)
        if not normalized:
            continue
        aliases_by_token.setdefault(normalized, set()).add(normalized)
        if len(normalized) > 1 and normalized.isalpha():
            aliases_by_token.setdefault(normalized[0], set()).add(normalized)
    return {
        alias: next(iter(blocks))
        for alias, blocks in aliases_by_token.items()
        if len(blocks) == 1
    }


def units_for_block_token(
    token: str,
    unit_part_token: str,
    block_aliases: dict[str, str],
    block_unit_part_to_units: dict[tuple[str, str], list[str]],
) -> list[str]:
    block = block_aliases.get(token)
    if not block:
        return []
    unit_part = normalize_unit_part(unit_part_token, UNIT_PAD_WIDTH)
    if not unit_part:
        return []
    return block_unit_part_to_units.get((block, unit_part), [])


def unit_part_matches_token(unit_part: str, token: str) -> bool:
    if unit_part.isdigit():
        return token.isdigit() and int(token) == int(unit_part)
    return normalize_unit_part(token, UNIT_PAD_WIDTH) == unit_part


def number_value_for_token(token: str) -> int | None:
    return int(token) if token.isdigit() else None


def long_numeric_candidate_numbers(
    address: object,
    valid_numbers: set[int],
    config: ApartmentConfig,
    filler_re: re.Pattern[str],
) -> list[int]:
    stripped = strip_address_fillers(address, config, filler_re)
    if not stripped:
        return []

    runs: list[list[str]] = []
    current_run: list[str] = []
    for token in stripped.split():
        if token.isdigit():
            current_run.append(token)
            continue
        if current_run:
            runs.append(current_run)
            current_run = []
        chunks = re.findall(r"\d+", token)
        if len(chunks) > 1:
            runs.append(chunks)
        elif len(chunks) == 1 and len(chunks[0]) >= 4:
            runs.append(chunks)
    if current_run:
        runs.append(current_run)

    candidates: set[int] = set()
    for run in runs:
        for start in range(len(run)):
            combined = ""
            for chunk in run[start:]:
                combined += chunk
                if len(combined) >= 4:
                    number = int(combined)
                    if number in valid_numbers:
                        candidates.add(number)
    return sorted(candidates)


def long_numeric_candidate_units(
    address: object,
    valid_numbers: set[int],
    units_by_number: dict[int, list[str]],
    config: ApartmentConfig,
    filler_re: re.Pattern[str],
) -> list[str]:
    return sorted(
        {
            unit
            for number in long_numeric_candidate_numbers(address, valid_numbers, config, filler_re)
            for unit in units_by_number.get(number, [])
        }
    )


def merge_candidate_units(*values: object) -> list[str]:
    return sorted(
        {
            unit
            for value in values
            for unit in matcher.voter_candidate_units(value)
        }
    )


def parse_units_from_address(
    address: object,
    config: ApartmentConfig,
    valid_units: set[str],
    valid_blocks: set[str],
    block_aliases: dict[str, str],
    block_unit_part_to_units: dict[tuple[str, str], list[str]],
    units_by_number: dict[int, list[str]],
    label_re: re.Pattern[str],
    filler_re: re.Pattern[str],
) -> list[str]:
    stripped = strip_address_fillers(address, config, filler_re)
    if not stripped:
        return []
    tokens = stripped.split()
    candidates: set[str] = set()

    for index, token in enumerate(tokens):
        if token in valid_units and (
            valid_blocks
            or not token.isdigit()
            or has_target_label(address, label_re)
        ):
            candidates.add(token)
        if token in block_aliases and index + 1 < len(tokens):
            candidates.update(
                units_for_block_token(
                    token,
                    tokens[index + 1],
                    block_aliases,
                    block_unit_part_to_units,
                )
            )
        if token in block_aliases and index > 0:
            candidates.update(
                units_for_block_token(
                    token,
                    tokens[index - 1],
                    block_aliases,
                    block_unit_part_to_units,
                )
            )

    if candidates:
        return sorted(candidates)

    if not has_target_label(address, label_re):
        return []
    numeric_tokens = [int(token) for token in tokens if token.isdigit()]
    return sorted(
        {
            unit
            for number in numeric_tokens
            for unit in units_by_number.get(number, [])
        }
    )


def parse_unit_from_address(
    address: object,
    config: ApartmentConfig,
    valid_units: set[str],
    valid_blocks: set[str],
    block_aliases: dict[str, str],
    block_unit_part_to_units: dict[tuple[str, str], list[str]],
    units_by_number: dict[int, list[str]],
    label_re: re.Pattern[str],
    filler_re: re.Pattern[str],
) -> str | None:
    candidates = parse_units_from_address(
        address,
        config,
        valid_units,
        valid_blocks,
        block_aliases,
        block_unit_part_to_units,
        units_by_number,
        label_re,
        filler_re,
    )
    return candidates[0] if len(candidates) == 1 else None


def is_ignorable_address_token(token: str, valid_blocks: set[str]) -> bool:
    if len(token) != 1 or not token.isalpha():
        return False
    return not valid_blocks


def parse_number_only_unit_number(
    address: object,
    config: ApartmentConfig,
    valid_numbers: set[int],
    valid_blocks: set[str],
    label_re: re.Pattern[str],
    filler_re: re.Pattern[str],
) -> int | None:
    stripped = strip_address_fillers(address, config, filler_re)
    if not stripped:
        return None
    tokens = stripped.split()
    nonnumeric_tokens = [token for token in tokens if not token.isdigit()]
    if any(not is_ignorable_address_token(token, valid_blocks) for token in nonnumeric_tokens):
        return None

    candidates = [token for token in tokens if token.isdigit() and int(token) in valid_numbers]
    if not candidates:
        return None
    noncandidate_numbers = [token for token in tokens if token.isdigit() and int(token) not in valid_numbers]
    if noncandidate_numbers:
        return None

    preferred = sorted({int(token) for token in candidates if len(token) >= 2})
    if len(preferred) == 1:
        return preferred[0]
    if len(preferred) > 1:
        return None
    unique_candidates = sorted({int(token) for token in candidates})
    return unique_candidates[0] if len(unique_candidates) == 1 else None


def number_only_address_key(
    voter: pd.Series,
    config: ApartmentConfig,
    filler_re: re.Pattern[str],
) -> str:
    if pd.isna(voter.get("number_only_flat")):
        return ""
    stripped = strip_address_fillers(voter["house_number"], config, filler_re)
    if not stripped:
        stripped = f"{int(voter['number_only_flat']):0{UNIT_PAD_WIDTH}d}"
    part_key = matcher.normalize_space(voter.get("part", ""))
    return f"PART:{part_key}:NUMADDR:{int(voter['number_only_flat']):0{UNIT_PAD_WIDTH}d}:{stripped}"


def long_number_address_key(
    voter: pd.Series,
    config: ApartmentConfig,
    filler_re: re.Pattern[str],
) -> str:
    units = matcher.voter_candidate_units(voter.get("long_number_candidate_units"))
    if not units:
        return ""
    stripped = strip_address_fillers(voter["house_number"], config, filler_re)
    part_key = matcher.normalize_space(voter.get("part", ""))
    return f"PART:{part_key}:LONGNUM:{';'.join(sorted(units))}:{stripped}"


def voter_address_group_key(voter: pd.Series, config: ApartmentConfig) -> str:
    part_key = matcher.normalize_space(voter.get("part", ""))
    if pd.notna(voter.get("parsed_unit")) and voter.get("parsed_unit"):
        address_key = matcher.normalize_space(voter.get("address_norm", ""))
        if not address_key:
            address_key = str(voter["parsed_unit"])
        return f"PART:{part_key}:UNITADDR:{voter['parsed_unit']}:{address_key}"
    if pd.notna(voter.get("number_only_flat")):
        return str(voter.get("number_only_address_key", ""))
    return ""


def roster_by_unit_group(roster_rows: pd.DataFrame) -> dict[tuple[str, str], list[dict[str, object]]]:
    out: dict[tuple[str, str], list[dict[str, object]]] = {}
    for _, row in roster_rows.iterrows():
        key = (row["unit"], row["group_label"])
        out.setdefault(key, []).append(
            {
                "roster_row_id": int(row["_roster_row_id"]),
                "unit": row["unit"],
                "name": row["name"],
                "name_norm": " ".join(t.text for t in matcher.tokenize_name(row["name"])),
                "status": row.get("status", ""),
            }
        )
    return out


def read_roster_source(config: ApartmentConfig) -> pd.DataFrame:
    """Read the source file and apply the apartment's source-specific cleaning."""
    path = config.roster_path
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        source = pd.read_excel(path, dtype=str)
        if "name" in source and {"unit", "unit_part"}.intersection(source.columns):
            return source.fillna("")

        columns = EXCEL_ROSTER_COLUMNS.get(config.key, {})
        if not columns or not set(columns).issubset(source.columns):
            expected = ", ".join(columns) if columns else "name and either unit or unit_part"
            raise ValueError(f"{path} is missing expected roster columns: {expected}")

        roster = source.dropna(subset=list(columns)).rename(columns=columns)
        roster = roster[list(columns.values())].copy()
        status = roster["status"].map(matcher.normalize_space)
        if config.key == "concorde":
            roster["status"] = status.str.lower().eq("yes").map({True: "Yes", False: "No"})
        else:
            roster["status"] = status.str.title()
        if config.key == "purnima":
            names = roster["name"].map(matcher.normalize_space).str.lower()
            unknown = names.eq("") | names.str.contains(r"<<<|not known")
            roster = roster.loc[~unknown].copy()
    else:
        try:
            roster = pd.read_csv(path, dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            if config.key != "tirumala_vintage":
                raise
            roster = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="cp1252")

        if "name" not in roster or not {"unit", "unit_part"}.intersection(roster.columns):
            raise ValueError(f"{path} is missing expected roster columns: name and either unit or unit_part")

        tirumala_source_columns = {"unit", "block", "name", "status"}
        if (
            config.key != "tirumala_vintage"
            or "apartment_key" in roster
            or "unit_part" in roster
            or not tirumala_source_columns.issubset(roster.columns)
        ):
            return roster

        # The Tirumala source contains a placeholder email and truncated names.
        roster["name"] = roster["name"].str.replace("…", "", regex=False).str.strip()
        roster = roster.loc[~roster["name"].str.contains("@", regex=False)].copy()
        for column in ("unit", "block", "status"):
            roster[column] = roster[column].str.strip()

    roster["apartment_key"] = config.key
    return roster.reindex(columns=STANDARD_ROSTER_COLUMNS, fill_value="")


def normalize_roster(config: ApartmentConfig, source_rows: pd.DataFrame) -> pd.DataFrame:
    roster = source_rows.copy()

    for column in STANDARD_ROSTER_COLUMNS:
        if column not in roster.columns:
            roster[column] = ""
    roster = roster[STANDARD_ROSTER_COLUMNS].copy()
    roster["apartment_key"] = roster["apartment_key"].map(matcher.normalize_space)
    roster.loc[~roster["apartment_key"].astype(bool), "apartment_key"] = config.key
    wrong_key = roster["apartment_key"] != config.key
    if wrong_key.any():
        bad_keys = ", ".join(sorted(roster.loc[wrong_key, "apartment_key"].astype(str).unique()))
        raise ValueError(f"{config.roster_path} contains apartment_key values other than {config.key}: {bad_keys}")
    roster["name"] = roster["name"].map(matcher.normalize_space)
    roster = roster[roster["name"].astype(bool)].copy()
    roster["status"] = roster["status"].map(lambda value: matcher.normalize_space(value) or "Unknown")

    roster["_roster_row_id"] = range(len(roster))
    normalized = roster.apply(canonical_standard_roster_unit, axis=1)
    roster["block"] = [item[0] for item in normalized]
    roster["unit_part"] = [item[1] for item in normalized]
    roster["unit"] = [item[2] for item in normalized]
    roster["unit_number"] = [item[3] for item in normalized]
    roster = roster[roster["unit"].astype(bool)].copy()
    roster["group_value"] = roster["status"]
    roster["group_label"] = roster["status"]
    return roster


def build_address_fields(voters: pd.DataFrame, roster_rows: pd.DataFrame, config: ApartmentConfig) -> pd.DataFrame:
    label_re = compile_terms_re(config.address_names)
    valid_units = set(roster_rows["unit"])
    valid_blocks = {block for block in roster_rows["block"].astype(str).unique() if block}
    block_aliases = build_block_aliases(valid_blocks)
    filler_re = filler_re_for_config(config, valid_blocks)
    valid_numbers = {int(value) for value in roster_rows["unit_number"].dropna().unique()}
    units_by_number = {
        int(number): sorted(group["unit"].unique().tolist())
        for number, group in roster_rows[roster_rows["unit_number"].notna()].groupby("unit_number")
    }
    block_unit_part_to_units = {
        (str(block), str(part)): sorted(group["unit"].unique().tolist())
        for (block, part), group in roster_rows.groupby(["block", "unit_part"])
    }

    voters = voters.copy()
    voters["address_norm"] = voters["house_number"].map(matcher.normalize_address)
    voters["has_target_label"] = voters["house_number"].map(lambda value: has_target_label(value, label_re))
    voters["parsed_unit_candidates"] = voters["house_number"].map(
        lambda value: parse_units_from_address(
            value,
            config,
            valid_units,
            valid_blocks,
            block_aliases,
            block_unit_part_to_units,
            units_by_number,
            label_re,
            filler_re,
        )
    )
    voters["parsed_unit"] = voters["parsed_unit_candidates"].map(
        lambda candidates: candidates[0] if len(candidates) == 1 else None
    )
    voters["number_only_flat"] = voters.apply(
        lambda row: (
            parse_number_only_unit_number(
                row["house_number"],
                config,
                valid_numbers,
                valid_blocks,
                label_re,
                filler_re,
            )
            if not row["parsed_unit_candidates"]
            else None
        ),
        axis=1,
    )
    voters["long_number_candidate_units"] = voters["house_number"].map(
        lambda value: long_numeric_candidate_units(
            value,
            valid_numbers,
            units_by_number,
            config,
            filler_re,
        )
    )
    voters["candidate_units"] = voters.apply(
        lambda row: (
            row["parsed_unit_candidates"]
            if row["parsed_unit_candidates"]
            else units_by_number.get(int(row["number_only_flat"]), [])
            if pd.notna(row["number_only_flat"])
            else []
        ),
        axis=1,
    )
    voters["address_candidate_units"] = voters.apply(
        lambda row: merge_candidate_units(row["candidate_units"], row["long_number_candidate_units"]),
        axis=1,
    )
    voters["address_unit"] = voters["address_candidate_units"].map(
        lambda candidates: candidates[0] if len(candidates) == 1 else None
    )
    voters["identity_candidate_units"] = voters.apply(
        lambda row: row["address_candidate_units"],
        axis=1,
    )
    voters["number_only_address_key"] = voters.apply(
        lambda row: number_only_address_key(row, config, filler_re)
        if pd.notna(row["number_only_flat"])
        else "",
        axis=1,
    )
    voters["long_number_address_key"] = voters.apply(
        lambda row: long_number_address_key(row, config, filler_re)
        if row["long_number_candidate_units"]
        else "",
        axis=1,
    )
    voters["unexplained_address_text"] = voters.apply(
        lambda row: matcher.unexplained_address_text(
            row["house_number"],
            row["parsed_unit"],
            row["number_only_flat"],
            label_re,
        ),
        axis=1,
    )
    voters["unexplained_address_letter_count"] = voters["unexplained_address_text"].map(
        matcher.unexplained_address_letter_count
    )
    voters["has_long_unexplained_address"] = (
        ~voters["has_target_label"]
        & (voters["unexplained_address_letter_count"] > matcher.UNEXPLAINED_ADDRESS_MAX_LETTERS)
    )
    voters["other_complex_terms"] = voters["unexplained_address_text"].where(
        voters["has_long_unexplained_address"],
        "",
    )
    voters["has_other_complex"] = voters["has_long_unexplained_address"]
    voters["same_address_group_key"] = voters.apply(lambda row: voter_address_group_key(row, config), axis=1)
    return voters


def source_word_items(voter: pd.Series) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for source_kind, source_name in (
        ("voter_name", voter.get("name", "")),
        ("relation_name", voter.get("relation_name", "")),
    ):
        for token in matcher.full_word_tokens(matcher.tokenize_name(source_name)):
            items.append((source_kind, token.text))
    return items


def source_name_items(voter: pd.Series) -> list[tuple[str, object, str]]:
    items: list[tuple[str, object, str]] = []
    for source_kind, source_name in (
        ("voter_name", voter.get("name", "")),
        ("relation_name", voter.get("relation_name", "")),
    ):
        source_norm = matcher.whole_name_normalized(source_name)
        if source_norm:
            items.append((source_kind, source_name, source_norm))
    return items


def connection_name_key(roster_name: object) -> str:
    """Compare roster names ignoring case, spacing, punctuation, and honorifics."""
    return "".join(token.text for token in matcher.tokenize_name(roster_name))


def percent(score: float | None) -> int | None:
    return None if score is None else round(100 * score)


# (priority, full-name match %, part-name match %, roster name, multiple full words, linked voter match %)
ConnectionCandidate = tuple[int, int | None, int | None, str, bool, int | None]


def has_multiple_name_words(name: object) -> bool:
    return len(matcher.full_word_tokens(matcher.tokenize_name(name))) > 1


def connection_candidates(record: dict[str, object]) -> list[ConnectionCandidate]:
    """Roster people this voter row is connected through, with the full-name and part-name match %."""
    candidates: list[ConnectionCandidate] = []
    person_hits = record["person_hits"]
    # A voter is not their own relation: if the voter name also matched the roster person
    # that the relation name matched, prefer the voter name's other roster matches.
    relation_keys = {connection_name_key(hit["roster_name"]) for hit in record["relation_hits"]}
    not_relation = [hit for hit in person_hits if connection_name_key(hit["roster_name"]) not in relation_keys]
    if not_relation:
        person_hits = not_relation
    for hit in person_hits:
        score = matcher.name_match_percent(hit["voter_name"], hit["roster_name"])
        candidates.append(
            (
                CONNECTION_PRIORITY_VOTER_NAME,
                score,
                percent(hit.get("part_score")),
                str(hit["roster_name"]),
                has_multiple_name_words(hit["voter_name"]),
                score,
            )
        )
    for hit in record["relation_hits"]:
        candidates.append(
            (
                CONNECTION_PRIORITY_RELATION_NAME,
                matcher.name_match_percent(hit["relation_name"], hit["roster_name"]),
                percent(hit.get("part_score")),
                str(hit["roster_name"]),
                has_multiple_name_words(hit["relation_name"]),
                hit["linked_voter_name_match_pct"],
            )
        )
    for link in record["member_links"]:
        # Keep the score and word count from the same voter.
        for roster_name in link.get("anchor_connection_names", []):
            candidates.append(
                (
                    CONNECTION_PRIORITY_HOUSEHOLD_MEMBER,
                    link.get("anchor_connection_pct"),
                    link.get("anchor_connection_part_pct"),
                    str(roster_name),
                    link["anchor_match_has_multiple_words"],
                    link.get("anchor_connection_pct"),
                )
            )
    return candidates


def select_connection(candidates: list[ConnectionCandidate]) -> tuple[list[str], int | None, int | None, bool, int | None]:
    """Pick the row's roster connections and carry their name scores.

    The voter's own name match wins over a relation-name match, which wins over a
    household-member link. Within that, the highest full-name match % wins; equal scores are
    all kept. The word-count flag and linked voter's score use the same selected evidence.
    """
    if not candidates:
        return [], None, None, False, None
    best_priority = min(candidate[0] for candidate in candidates)
    top = [candidate for candidate in candidates if candidate[0] == best_priority]
    scores = [pct for _, pct, _, _, _, _ in top if pct is not None]
    best_pct = max(scores) if scores else None
    names: list[str] = []
    part_pcts: list[int] = []
    linked_voter_pcts: list[int] = []
    has_multiple_words = False
    seen_keys: set[str] = set()
    for _, pct, part_pct, roster_name, multiple_words, linked_voter_pct in top:
        if pct != best_pct:
            continue
        if part_pct is not None:
            part_pcts.append(part_pct)
        if linked_voter_pct is not None:
            linked_voter_pcts.append(linked_voter_pct)
        has_multiple_words |= multiple_words
        key = connection_name_key(roster_name)
        if key not in seen_keys:
            seen_keys.add(key)
            names.append(roster_name)
    return names, best_pct, max(part_pcts, default=None), has_multiple_words, max(linked_voter_pcts, default=None)


def anchor_connection(anchor_record: dict[str, object]) -> dict[str, object]:
    """The roster connection and match % of the voter a household member is linked through."""
    names, pct, part_pct, has_multiple_words, _ = select_connection(connection_candidates(anchor_record))
    return {
        "anchor_connection_names": names,
        "anchor_connection_pct": pct,
        "anchor_connection_part_pct": part_pct,
        "anchor_match_has_multiple_words": has_multiple_words,
    }


def same_address_word_link(
    voter: pd.Series,
    anchor_records: list[dict[str, object]],
) -> dict[str, object] | None:
    voter_items = source_word_items(voter)
    voter_name_items = source_name_items(voter)
    if not voter_items and not voter_name_items:
        return None

    for anchor_record in anchor_records:
        anchor = anchor_record["voter"]
        if int(anchor["_row_id"]) == int(voter["_row_id"]):
            continue
        for voter_source, voter_word in voter_items:
            for anchor_source, anchor_word in source_word_items(anchor):
                match_kind = matcher.full_token_match(voter_word, anchor_word)
                if match_kind:
                    return {
                        "voter_source": voter_source,
                        "voter_word": voter_word,
                        "anchor_serial": int(anchor["serial_number"]),
                        "anchor_name": anchor["name"],
                        "anchor_source": anchor_source,
                        "anchor_word": anchor_word,
                        "match_kind": match_kind,
                        **anchor_connection(anchor_record),
                    }
        for voter_source, voter_name, voter_norm in voter_name_items:
            for anchor_source, anchor_name, anchor_norm in source_name_items(anchor):
                match = matcher.whole_name_rule_match(voter_name, anchor_name)
                if match.matched:
                    return {
                        "voter_source": voter_source,
                        "voter_word": voter_norm,
                        "anchor_serial": int(anchor["serial_number"]),
                        "anchor_name": anchor["name"],
                        "anchor_source": anchor_source,
                        "anchor_word": anchor_norm,
                        "match_kind": match.kind,
                        **anchor_connection(anchor_record),
                    }
    return None


def add_evidence(
    evidence_by_row: dict[int, dict[str, object]],
    voter: pd.Series,
    person_hits: list[dict[str, object]],
    relation_hits: list[dict[str, object]],
    scope: str,
    *,
    unique_unit: bool = True,
) -> None:
    if not person_hits and not relation_hits:
        return
    row_id = int(voter["_row_id"])
    record = evidence_by_row.setdefault(
        row_id,
        {
            "voter": voter,
            "person_hits": [],
            "relation_hits": [],
            "scopes": set(),
            "member_links": [],
        },
    )
    if unique_unit:
        record["person_hits"].extend(person_hits)
    else:
        # A second roster match in the voter household can resolve an ambiguous unit.
        record["person_hits"].extend({**hit, "requires_household_match": True} for hit in person_hits)
    record["relation_hits"].extend(relation_hits)
    record["scopes"].add(scope)


def add_household_member(
    evidence_by_row: dict[int, dict[str, object]],
    voter: pd.Series,
    member_link: dict[str, object],
    scope: str,
) -> None:
    row_id = int(voter["_row_id"])
    record = evidence_by_row.setdefault(
        row_id,
        {
            "voter": voter,
            "person_hits": [],
            "relation_hits": [],
            "scopes": set(),
            "member_links": [],
        },
    )
    record["scopes"].add(scope)
    record["member_links"].append(member_link)


def voter_link_type(record: dict[str, object]) -> str:
    link_types: list[str] = []
    if record["person_hits"]:
        link_types.append("voter_name_match")
    if record["relation_hits"]:
        link_types.append("relation_name_match")
    if not record["person_hits"] and not record["relation_hits"] and record["member_links"]:
        link_types.append("same_address_household_member")
    if "explicit_apartment_address" in record["scopes"]:
        link_types.append("explicit_apartment_address")
    return ";".join(link_types)


def combine_link_types(values: pd.Series) -> str:
    combined: list[str] = []
    for value in values:
        for link_type in str(value).split(";"):
            if link_type and link_type not in combined:
                combined.append(link_type)
    return ";".join(combined)


def direct_hit_units(
    household_details: dict[tuple[str, str], dict[str, object]],
) -> dict[int, list[str]]:
    """Return units with own-name evidence, giving independent matches priority."""
    direct: dict[int, set[str]] = {}
    contextual: dict[int, set[str]] = {}
    for (unit, _group_label), evaluation in household_details.items():
        for detail in evaluation["row_details"]:
            row_id = int(detail["voter"]["_row_id"])
            for hit in detail["person_hits"]:
                matches = contextual if "anchor_voter_row_id" in hit else direct
                matches.setdefault(row_id, set()).add(unit)
    units = {row_id: sorted(found) for row_id, found in contextual.items()}
    units.update({row_id: sorted(found) for row_id, found in direct.items()})
    return units


def same_roll_household(first: pd.Series, second: pd.Series) -> bool:
    """Check the household group and address assigned from the voter roll."""
    return (
        first["household_id"] is not None
        and first["household_id"] == second["household_id"]
        and first["address_norm"] == second["address_norm"]
    )


def corroborated_roster_matches(
    unit_evidence: dict[tuple[str, str], dict[int, dict[str, object]]],
) -> dict[int, tuple[str, str]]:
    """Find unambiguous pairs of linked voters who match distinct people at one flat."""
    by_unit: dict[str, dict[int, tuple[pd.Series, dict[str, int]]]] = {}
    for (unit, _), evidence in unit_evidence.items():
        for row_id, record in evidence.items():
            for hit in record["person_hits"]:
                if "anchor_voter_row_id" in hit:
                    continue
                name = connection_name_key(hit["roster_name"])
                score = matcher.name_match_percent(hit["voter_name"], hit["roster_name"]) or 0
                _, names = by_unit.setdefault(unit, {}).setdefault(row_id, (record["voter"], {}))
                names[name] = max(score, names.get(name, 0))

    voter_options: dict[int, dict[tuple[str, str], tuple[bool, bool]]] = {}
    roster_options: dict[tuple[str, str], dict[int, tuple[bool, bool]]] = {}
    pairs: set[tuple[int, str, int, str, str]] = set()
    for unit, matches in by_unit.items():
        for (first_id, (first, first_names)), (second_id, (second, second_names)) in combinations(matches.items(), 2):
            same_address = same_roll_household(first, second)
            named_relation = (
                matcher.relation_identifies_voter(first["relation_name"], second["name"])
                or matcher.relation_identifies_voter(second["relation_name"], first["name"])
            )
            if not (same_address or named_relation):
                continue
            for first_name, first_score in first_names.items():
                if first_score != max(first_names.values()):
                    continue
                for second_name, second_score in second_names.items():
                    if first_name == second_name or second_score != max(second_names.values()):
                        continue
                    pairs.add((first_id, first_name, second_id, second_name, unit))
                    for row_id, name in ((first_id, first_name), (second_id, second_name)):
                        key = unit, name
                        rank = named_relation, same_address
                        options = voter_options.setdefault(row_id, {})
                        options[key] = max(rank, options.get(key, rank))
                        options = roster_options.setdefault(key, {})
                        options[row_id] = max(rank, options.get(row_id, rank))

    # Prefer a named relation over a shared address. Both sides must agree.
    best_voter_options = {
        row_id: {key for key, rank in options.items() if rank == max(options.values())}
        for row_id, options in voter_options.items()
    }
    best_roster_options = {
        key: {row_id for row_id, rank in options.items() if rank == max(options.values())}
        for key, options in roster_options.items()
    }
    matched = {}
    for first_id, first_name, second_id, second_name, unit in pairs:
        entries = ((first_id, (unit, first_name)), (second_id, (unit, second_name)))
        if all(best_voter_options[row_id] == {key} and best_roster_options[key] == {row_id} for row_id, key in entries):
            matched.update(entries)
    return matched


def unit_output_values(config: ApartmentConfig, roster_rows: pd.DataFrame, unit: str) -> dict[str, object]:
    rows = roster_rows[roster_rows["unit"] == unit]
    block = rows["block"].dropna().astype(str).iloc[0] if not rows.empty else ""
    unit_part = rows["unit_part"].dropna().astype(str).iloc[0] if not rows.empty else unit
    return {
        "apartment": config.apartment_name,
        "apartment_unit": unit,
        "apartment_block": block,
        "apartment_unit_part": unit_part,
    }


def base_output_record(voter: pd.Series, config: ApartmentConfig) -> dict[str, object]:
    record = {
        "part": voter["part"],
        "section_raw": voter["section_raw"],
        "serial_number": voter["serial_number"],
        "epic_number": voter["epic_number"],
        "voter_name": voter["name"],
        "relation_type": voter["relation_type"],
        "relation_name": voter["relation_name"],
        "house_number": voter["house_number"],
        "age": voter["age"],
        "gender": voter["gender"],
        "ward": voter["ward"],
        "corporation": voter["corporation"],
        "pincode": voter["pincode"],
        "pollingname": voter["pollingname"],
        "pollingaddress": voter["pollingaddress"],
    }
    return record


def set_connection_fields(record: dict[str, object], candidates: list[ConnectionCandidate]) -> None:
    names, pct, part_pct, has_multiple_words, linked_voter_pct = select_connection(candidates)
    record["apartment_connection"] = "; ".join(names)
    record["part_name_match"] = part_pct
    record["name_match_pct"] = pct
    record["_connection_candidates"] = candidates
    record["_connection_names"] = names
    record["_match_has_multiple_words"] = has_multiple_words
    record["_linked_voter_name_match_pct"] = linked_voter_pct


def collapse_unresolved_group_records(out: pd.DataFrame) -> pd.DataFrame:
    if out.empty:
        return out

    if "apartment_unit" not in out.columns:
        return out

    collapsed: list[dict[str, object]] = []
    for _, group in out.groupby(["_row_id", "apartment_unit"], sort=False, dropna=False):
        group_values = set(group["apartment_status"].astype(str))
        if len(group) == 1 or len(group_values) == 1:
            collapsed.extend(group.to_dict("records"))
            continue

        row = group.iloc[0].to_dict()
        row["apartment_status"] = UNASSIGNED_STATUS
        row["voter_link_type"] = combine_link_types(group["voter_link_type"])
        merged_candidates = [
            candidate
            for candidates in group["_connection_candidates"]
            for candidate in candidates
        ]
        set_connection_fields(row, merged_candidates)
        collapsed.append(row)

    return pd.DataFrame(collapsed)


def summarize_unmapped_households(
    unmapped_rows: pd.DataFrame,
    voters: pd.DataFrame,
    mapped_row_ids: pd.Series,
    config: ApartmentConfig,
) -> pd.DataFrame:
    """Summarize household groups with an exact apartment name and no linked unit."""
    exact_name = compile_terms_re(config.address_names, allow_joined_words=False)
    named_rows = unmapped_rows["address_norm"].str.contains(exact_name, na=False)
    mapped_households = voters.loc[voters["_row_id"].isin(mapped_row_ids), "household_id"]
    report_rows = unmapped_rows[named_rows & ~unmapped_rows["household_id"].isin(mapped_households)]

    households = []
    for household_id, rows in report_rows.groupby("household_id", sort=False):
        first = rows.iloc[0]
        households.append(
            {
                "household_id": household_id,
                "house_number": "; ".join(rows["house_number"].astype(str).unique()),
                "part": first["part"],
                "section_raw": first["section_raw"],
                "pollingname": first["pollingname"],
                "voter_count": len(rows),
                "voter_serial_numbers": ", ".join(rows["serial_number"].astype(str)),
            }
        )
    return pd.DataFrame(households, columns=UNMAPPED_HOUSEHOLD_COLUMNS)


def dominated_voter_links(out: pd.DataFrame) -> dict[tuple[int, str], set[str]]:
    """Find own-name links beaten by at least two distinct voter rows on name and booth evidence."""
    candidates: dict[tuple[str, str], dict[int, tuple[int, int]]] = {}
    for _, row in out.iterrows():
        if "voter_name_match" not in row["voter_link_type"].split(";"):
            continue
        for name in row["_connection_names"]:
            key = row["apartment_unit"], connection_name_key(name)
            candidates.setdefault(key, {})[int(row["_row_id"])] = (
                int(row["name_match_pct"]), int(row["other_hh_matched_booth"])
            )

    discarded: dict[tuple[int, str], set[str]] = {}
    for (unit, name), links in candidates.items():
        for row_id, (name_score, booth_count) in links.items():
            dominators = sum(
                other_score >= name_score
                and other_count >= booth_count
                and (other_score > name_score or other_count > booth_count)
                for other_score, other_count in links.values()
            )
            if dominators >= 2:
                discarded.setdefault((row_id, unit), set()).add(name)
    return discarded


def corroborated_named_pair_links(
    initial: pd.DataFrame,
    unit_evidence: dict[tuple[str, str], dict[int, dict[str, object]]],
    source: pd.DataFrame,
) -> set[tuple[int, str]]:
    """Find reserved own-name pairs with full flats and a named relation between voters."""
    claimed = corroborated_roster_matches(unit_evidence)
    by_unit: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in initial.to_dict("records"):
        row_id, unit = int(row["_row_id"]), row["apartment_unit"]
        if (
            row["apartment_status"] != UNASSIGNED_STATUS
            and "voter_name_match" in row["voter_link_type"].split(";")
            and claimed.get(row_id, (None,))[0] == unit
            and source.at[row_id, "parsed_unit"] == unit
        ):
            by_unit[unit].append(row)

    paired: set[tuple[int, str]] = set()
    for unit, candidates in by_unit.items():
        for first, second in combinations(candidates, 2):
            first_id, second_id = int(first["_row_id"]), int(second["_row_id"])
            if claimed[first_id] == claimed[second_id]:
                continue
            if (
                matcher.relation_identifies_voter(first["relation_name"], second["voter_name"])
                or matcher.relation_identifies_voter(second["relation_name"], first["voter_name"])
            ):
                paired.update(((first_id, unit), (second_id, unit)))
    return paired


def expand_named_full_word_matches(
    voters: pd.DataFrame,
    roster_rows: pd.DataFrame,
    config: ApartmentConfig,
    initial: pd.DataFrame,
    unit_evidence: dict[tuple[str, str], dict[int, dict[str, object]]],
) -> tuple[dict[tuple[str, str], dict[int, dict[str, object]]], set[tuple[int, str]]]:
    """Add uncontested full-word name matches at an explicitly named building and full flat."""
    mapped = initial[initial["apartment_unit"].ne("") & initial["apartment_status"].ne(UNASSIGNED_STATUS)]
    already_mapped = set(mapped["_row_id"])
    occupied = {
        (row["apartment_unit"], connection_name_key(name))
        for row in mapped.to_dict("records")
        if "voter_name_match" in row["voter_link_type"].split(";")
        for name in row["_connection_names"]
    }
    people_by_flat: dict[str, list[tuple[str, dict[str, object]]]] = defaultdict(list)
    for (unit, status), people in roster_by_unit_group(roster_rows).items():
        people_by_flat[unit].extend((status, person) for person in people)

    # Every word comparison here is exact, unordered, and excludes initials.
    target = compile_terms_re(config.address_names, allow_joined_words=False)
    candidates = voters[
        voters["address_norm"].str.contains(target) & voters["parsed_unit"].notna()
        & ~voters["_row_id"].isin(already_mapped)
    ]
    proposals: dict[tuple[str, str], list[tuple[pd.Series, str, dict[str, object]]]] = defaultdict(list)
    for _, voter in candidates.iterrows():
        name_words = matcher.name_word_set(voter["name"])
        if len(name_words) < 2:
            continue
        relation_words = matcher.name_word_set(voter["relation_name"])
        unit = voter["parsed_unit"]
        options = []
        for status, person in people_by_flat[unit]:
            roster_words = matcher.name_word_set(person["name"])
            if len(roster_words) < 2:
                continue
            relation_matches = len(relation_words) >= 2 and (
                relation_words <= roster_words or roster_words <= relation_words
            )
            if not relation_matches and (name_words <= roster_words or roster_words <= name_words):
                options.append((status, person))
        if len(options) != 1:
            continue
        status, person = options[0]
        roster_link = unit, connection_name_key(person["name"])
        if roster_link not in occupied:
            proposals[roster_link].append((voter, status, person))

    # Copy only modified evidence groups. Conflicting new claims are rejected together.
    updated = unit_evidence.copy()
    additions: set[tuple[int, str]] = set()
    for (unit, _), options in proposals.items():
        if len(options) != 1:
            continue
        voter, status, person = options[0]
        row_id = int(voter["_row_id"])
        key = unit, status
        if key not in updated or updated[key] is unit_evidence.get(key):
            updated[key] = updated.get(key, {}).copy()
        if row_id in updated[key]:
            record = updated[key][row_id]
            updated[key][row_id] = {
                **record, "person_hits": record["person_hits"].copy(), "scopes": record["scopes"].copy(),
            }
        hit = {
            "voter_row_id": row_id, "serial_number": int(voter["serial_number"]),
            "voter_name": voter["name"], "roster_row_id": person["roster_row_id"],
            "roster_name": person["name"], "roster_name_norm": person["name_norm"],
            "match_source": "voter_name", "match_kind": "named_flat_full_words",
            "match_detail": "matching full words at a named building and parsed flat",
            "part_score": 1.0,
        }
        add_evidence(updated[key], voter, [hit], [], "exact_unit")
        additions.add((row_id, unit))
    return updated, additions


def select_supported_apartment_links(
    voters: pd.DataFrame,
    roster_rows: pd.DataFrame,
    config: ApartmentConfig,
    initial: pd.DataFrame,
    unit_evidence: dict[tuple[str, str], dict[int, dict[str, object]]],
    same_address_groups: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select named-section, corroborated-pair, 100% and guarded 95% candidates and resolve anchors."""
    source = voters.set_index("_row_id")
    target = compile_terms_re(config.address_names, allow_joined_words=False)
    candidates = initial[initial["apartment_unit"].ne("")].copy()
    paired = corroborated_named_pair_links(initial, unit_evidence, source)
    named_by_part: dict[tuple[str, str], set[str]] = defaultdict(set)
    named_by_section: dict[str, set[str]] = defaultdict(set)
    all_by_part: dict[tuple[str, str], set[str]] = defaultdict(set)

    # Freeze supporting flat sets on the first resolved pool, including address-only records.
    for row in candidates.to_dict("records"):
        row_id, unit = int(row["_row_id"]), row["apartment_unit"]
        section = row["section_raw"]
        if pd.isna(section) or not str(section).strip():
            continue
        section_key = str(row["part"]), section
        all_by_part[section_key].add(unit)
        if source.at[row_id, "parsed_unit"] == unit and target.search(source.at[row_id, "address_norm"]):
            named_by_part[section_key].add(unit)
            named_by_section[section].add(unit)

    chosen: set[tuple[int, str]] = set()
    strong: set[tuple[int, str]] = set()
    counts: dict[tuple[int, str], tuple[int, int]] = {}
    all_links = set(zip(candidates["_row_id"], candidates["apartment_unit"]))
    for row in candidates.to_dict("records"):
        row_id, unit = key = int(row["_row_id"]), row["apartment_unit"]
        voter = source.loc[row_id]
        section = row["section_raw"]
        valid_section = pd.notna(section) and bool(str(section).strip())
        section_key = str(row["part"]), section
        named_count = len(named_by_part.get(section_key, set()) - {unit}) if valid_section else 0
        other_count = len(all_by_part.get(section_key, set()) - {unit}) if valid_section else 0
        counts[key] = other_count, named_count
        explicit = bool(target.search(voter["address_norm"]))
        full_flat = voter["parsed_unit"] == unit
        direct = "voter_name_match" in row["voter_link_type"].split(";")
        name_score = int(row["name_match_pct"]) if pd.notna(row["name_match_pct"]) else 0
        linked_score = row["_linked_voter_name_match_pct"]
        linked_score = int(linked_score) if pd.notna(linked_score) else 0
        score = min(name_score, linked_score)
        exact_own_name = (
            direct and name_score == 100 and row["_match_has_multiple_words"] and full_flat
            and not str(voter["unexplained_address_text"] or "").strip()
        )
        section_supported = named_count >= 1 and (full_flat or score >= 80)
        cross_part_supported = valid_section and bool(named_by_section.get(section, set()) - {unit})
        high_name_supported = score >= 95 and cross_part_supported and (
            full_flat or direct and len(matcher.tokenize_name(voter["name"])) >= 2
        )
        if explicit or section_supported or key in paired or exact_own_name or high_name_supported:
            chosen.add(key)
        if explicit or key in paired or (named_count >= 2 and full_flat and score >= 75):
            strong.add(key)

    # Ranking retains the complete preliminary pool, even rivals that fail eligibility.
    booth_units = matched_units_at_booth(initial)
    initial = initial.assign(other_hh_matched_booth=other_households_matched_at_booth(initial, booth_units))
    discarded = dominated_voter_links(initial)
    evidence, additions = expand_named_full_word_matches(voters, roster_rows, config, initial, unit_evidence)
    chosen.update(additions)
    strong.update(additions)
    out, unmapped = resolve_voter_links(
        voters[voters["has_target_label"]], roster_rows, config, evidence, same_address_groups, discarded,
        original_links=chosen, excluded_links=all_links - chosen,
    )
    if out.empty:
        return out, unmapped

    # Grades and support stay based on preliminary features, even if resolution changes the displayed link.
    keys = list(zip(out["_row_id"], out["apartment_unit"]))
    mapped = out["apartment_unit"].ne("") & out["apartment_status"].ne(UNASSIGNED_STATUS)
    out["_match_confidence"] = [
        "Strong" if key in strong or "explicit_apartment_address" in kind.split(";") else "Probable"
        for key, kind in zip(keys, out["voter_link_type"])
    ]
    out.loc[~mapped, "_match_confidence"] = "Strong"
    out["other_hh_matched_booth"] = other_households_matched_at_booth(out, booth_units)
    out["other_hh_matched_section_in_part"] = [counts.get(key, (0, 0))[0] for key in keys]
    out["other_named_flats_in_section"] = [counts.get(key, (0, 0))[1] for key in keys]
    return out, unmapped


def build_apartment_voter_rows(
    voters: pd.DataFrame,
    roster_rows: pd.DataFrame,
    roster: dict[tuple[str, str], list[dict[str, object]]],
    config: ApartmentConfig,
) -> tuple[pd.DataFrame, set[tuple[str, str]], pd.DataFrame]:
    """Return voter rows, connected (unit, roster name key) pairs, and unmapped household groups."""
    identity_usable = voters.copy()
    number_only_groups = {
        str(key): group.copy()
        for key, group in identity_usable[
            identity_usable["number_only_flat"].notna()
            & identity_usable["number_only_address_key"].astype(bool)
        ].groupby("number_only_address_key", sort=False)
    }
    same_address_groups = {
        str(key): group.copy()
        for key, group in identity_usable[
            identity_usable["same_address_group_key"].astype(bool)
        ].groupby("same_address_group_key", sort=False)
    }
    long_number_groups = {
        str(key): group.copy()
        for key, group in identity_usable[
            identity_usable["long_number_address_key"].astype(bool)
        ].groupby("long_number_address_key", sort=False)
    }
    number_only_group_cache: dict[str, dict[str, object]] = {}
    long_number_group_cache: dict[str, dict[str, object]] = {}
    unit_evidence: dict[tuple[str, str], dict[int, dict[str, object]]] = {}

    # Index voter positions by candidate unit once for the full constituency roll.
    candidate_units = identity_usable["identity_candidate_units"].reset_index(drop=True).explode().dropna()
    positions_by_unit = candidate_units.groupby(candidate_units, sort=False).groups
    for unit, group_label in sorted(roster):
        positions = positions_by_unit.get(unit)
        if positions is None:
            continue
        unit_roster = roster[(unit, group_label)]
        unit_rows = identity_usable.iloc[positions.unique()]

        evidence_by_row: dict[int, dict[str, object]] = {}

        exact_rows = unit_rows[unit_rows["parsed_unit"] == unit]
        if not exact_rows.empty:
            exact_evaluation = matcher.evaluate_voter_rows_against_unit(exact_rows, unit_roster)
            for detail in exact_evaluation["row_details"]:
                add_evidence(
                    evidence_by_row,
                    detail["voter"],
                    detail["person_hits"],
                    detail["relation_hits"],
                    "exact_unit",
                )

        candidate_address_rows = unit_rows[
            unit_rows["parsed_unit"].isna()
            & unit_rows["number_only_flat"].isna()
            & ~unit_rows["has_long_unexplained_address"]
            & unit_rows["candidate_units"].map(lambda units: unit in matcher.voter_candidate_units(units))
        ]
        if not candidate_address_rows.empty:
            candidate_evaluation = matcher.evaluate_voter_rows_against_unit(candidate_address_rows, unit_roster)
            for detail in candidate_evaluation["row_details"]:
                add_evidence(
                    evidence_by_row,
                    detail["voter"],
                    detail["person_hits"],
                    detail["relation_hits"],
                    "candidate_unit",
                )

        number_only_rows = unit_rows[
            unit_rows["parsed_unit"].isna()
            & unit_rows["number_only_flat"].notna()
            & unit_rows["candidate_units"].map(lambda units: unit in matcher.voter_candidate_units(units))
        ]
        for group_key in sorted(set(number_only_rows["number_only_address_key"].dropna().astype(str)) - {""}):
            group_rows = number_only_groups.get(group_key)
            if group_rows is None or group_rows.empty:
                continue
            if group_key not in number_only_group_cache:
                candidate_households: list[tuple[str, str]] = []
                for candidate_list in group_rows["candidate_units"]:
                    for candidate_unit in matcher.voter_candidate_units(candidate_list):
                        candidate_households.extend(key for key in roster if key[0] == candidate_unit)
                candidate_households = sorted(set(candidate_households))

                household_details = {
                    candidate_key: matcher.evaluate_voter_rows_against_unit(group_rows, roster[candidate_key])
                    for candidate_key in candidate_households
                }
                number_only_group_cache[group_key] = {
                    "household_details": household_details,
                    "row_identity_hit_units": direct_hit_units(household_details),
                }

            cached = number_only_group_cache[group_key]
            for detail in cached["household_details"].get((unit, group_label), {}).get("row_details", []):
                row_id = int(detail["voter"]["_row_id"])
                own_name_units = cached["row_identity_hit_units"].get(row_id, [])
                add_evidence(
                    evidence_by_row,
                    detail["voter"],
                    detail["person_hits"],
                    detail["relation_hits"],
                    "number_only_address",
                    unique_unit=own_name_units == [unit],
                )

        long_number_rows = unit_rows[
            unit_rows["long_number_candidate_units"].map(lambda units: unit in matcher.voter_candidate_units(units))
        ]
        for group_key in sorted(set(long_number_rows["long_number_address_key"].dropna().astype(str)) - {""}):
            group_rows = long_number_groups.get(group_key)
            if group_rows is None or group_rows.empty:
                continue
            if group_key not in long_number_group_cache:
                candidate_households: list[tuple[str, str]] = []
                for candidate_list in group_rows["long_number_candidate_units"]:
                    for candidate_unit in matcher.voter_candidate_units(candidate_list):
                        candidate_households.extend(key for key in roster if key[0] == candidate_unit)
                candidate_households = sorted(set(candidate_households))

                household_details = {
                    candidate_key: matcher.evaluate_voter_rows_against_unit(group_rows, roster[candidate_key])
                    for candidate_key in candidate_households
                }
                long_number_group_cache[group_key] = {
                    "household_details": household_details,
                    "row_identity_hit_units": direct_hit_units(household_details),
                }

            cached = long_number_group_cache[group_key]
            for detail in cached["household_details"].get((unit, group_label), {}).get("row_details", []):
                row_id = int(detail["voter"]["_row_id"])
                own_name_units = cached["row_identity_hit_units"].get(row_id, [])
                add_evidence(
                    evidence_by_row,
                    detail["voter"],
                    detail["person_hits"],
                    detail["relation_hits"],
                    "long_number_address",
                    unique_unit=own_name_units == [unit],
                )

        if evidence_by_row:
            unit_evidence[(unit, group_label)] = evidence_by_row

    # Reserve only the two people in a corroborated match and their roster entries.
    corroborated = corroborated_roster_matches(unit_evidence)
    claimed_roster_entries = {key: row_id for row_id, key in corroborated.items()}
    for (unit, _), evidence in unit_evidence.items():
        for row_id, record in evidence.items():
            reserved = corroborated.get(row_id)
            kept_hits = []
            for hit in record["person_hits"]:
                key = unit, connection_name_key(hit["roster_name"])
                if reserved == key and "anchor_voter_row_id" not in hit:
                    kept_hits.append(hit)
                elif reserved is None and key not in claimed_roster_entries and not hit.get("requires_household_match"):
                    kept_hits.append(hit)
            record["person_hits"] = kept_hits

    # Resolve once before applying frozen named-section eligibility and competing-match rankings.
    out, unmapped_rows = resolve_voter_links(voters, roster_rows, config, unit_evidence, same_address_groups, {})
    if not out.empty:
        out, unmapped_rows = select_supported_apartment_links(
            voters, roster_rows, config, out, unit_evidence, same_address_groups,
        )

    connected: set[tuple[str, str]] = set()
    if out.empty:
        return (
            pd.DataFrame(columns=[*OUTPUT_COLUMNS, "_match_confidence"]),
            connected,
            pd.DataFrame(columns=UNMAPPED_HOUSEHOLD_COLUMNS),
        )
    unmapped_households = summarize_unmapped_households(
        unmapped_rows,
        voters,
        out.loc[out["apartment_unit"].ne(""), "_row_id"],
        config,
    )
    connected = {
        (str(unit), connection_name_key(name))
        for unit, names in zip(out["apartment_unit"], out["_connection_names"])
        for name in names
    }
    # Put apartment-only rows after the rows with a unit.
    out["_unmapped_last"] = out["apartment_status"].eq(UNMAPPED_STATUS)
    sort_cols = ["_unmapped_last", "apartment_unit", "apartment_status", "part", "serial_number"]
    out = out.sort_values(sort_cols).reset_index(drop=True)
    out["part_name_match"] = out["part_name_match"].astype("Int64")
    out["name_match_pct"] = out["name_match_pct"].astype("Int64")
    return out[[*OUTPUT_COLUMNS, "_match_confidence"]], connected, unmapped_households


def resolve_voter_links(
    voters: pd.DataFrame,
    roster_rows: pd.DataFrame,
    config: ApartmentConfig,
    unit_evidence: dict[tuple[str, str], dict[int, dict[str, object]]],
    same_address_groups: dict[str, pd.DataFrame],
    discarded: dict[tuple[int, str], set[str]],
    original_links: set[tuple[int, str]] | None = None,
    excluded_links: set[tuple[int, str]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build output rows using only the direct matches still eligible to support other voters."""
    excluded_links = excluded_links or set()
    unit_evidence = {
        (unit, status): {
            row_id: {
                **record,
                "scopes": record["scopes"].copy(),
                "member_links": [],
                "person_hits": [
                    hit for hit in record["person_hits"]
                    if connection_name_key(hit["roster_name"]) not in discarded.get((row_id, unit), ())
                ],
            }
            for row_id, record in evidence.items()
            if (row_id, unit) not in excluded_links
        }
        for (unit, status), evidence in unit_evidence.items()
    }
    records: list[dict[str, object]] = []
    emitted_row_unit_keys: set[tuple[int, str]] = set()
    identity_supported_row_ids: set[int] = set()

    # Resolve own-name links before checking any dependent evidence.
    independent_hits = {
        (unit, row_id, hit["roster_row_id"])
        for (unit, _), evidence_by_row in unit_evidence.items()
        for row_id, record in evidence_by_row.items()
        for hit in record["person_hits"]
        if "anchor_voter_row_id" not in hit
    }
    direct_row_ids: set[int] = set()
    linked_people: dict[tuple[str, int], dict[int, tuple[object, int | None]]] = {}
    for (unit, _), evidence_by_row in unit_evidence.items():
        for row_id, record in evidence_by_row.items():
            record["person_hits"] = [
                hit for hit in record["person_hits"]
                if "anchor_voter_row_id" not in hit
                or (unit, hit["anchor_voter_row_id"], hit["anchor_roster_row_id"]) in independent_hits
            ]
            for hit in record["person_hits"]:
                direct_row_ids.add(row_id)
                linked_people.setdefault((unit, hit["roster_row_id"]), {})[row_id] = (
                    hit["voter_name"],
                    matcher.name_match_percent(hit["voter_name"], hit["roster_name"]),
                )

    # A relation must identify a different voter whose own name links that person to this flat.
    relation_units: dict[int, set[str]] = {}
    for (unit, _), evidence_by_row in unit_evidence.items():
        for row_id, record in evidence_by_row.items():
            if original_links is not None and (row_id, unit) not in original_links:
                record["relation_hits"] = []
                continue
            relation_hits = []
            for hit in record["relation_hits"]:
                people = linked_people.get((unit, hit["roster_row_id"]), {})
                scores = [
                    score for other_row_id, (voter_name, score) in people.items()
                    if other_row_id != row_id and matcher.relation_identifies_voter(hit["relation_name"], voter_name)
                ]
                if scores:
                    relation_hits.append({
                        **hit,
                        "linked_voter_name_match_pct": max((score for score in scores if score is not None), default=None),
                    })
            record["relation_hits"] = relation_hits
            if record["relation_hits"] and row_id not in direct_row_ids:
                relation_units.setdefault(row_id, set()).add(unit)

    for (unit, group_label), evidence_by_row in unit_evidence.items():
        # Household members inherit the unit and roster status from an own-name match.
        anchors_by_address: dict[str, list[dict[str, object]]] = {}
        for row_id, record in list(evidence_by_row.items()):
            voter = record["voter"]
            if record["person_hits"]:
                group_key = voter["same_address_group_key"]
                if group_key:
                    anchors_by_address.setdefault(group_key, []).append(record)
            elif (
                (row_id, unit) in discarded
                or row_id in direct_row_ids
                or not record["relation_hits"]
                or relation_units.get(row_id) != {unit}
            ):
                del evidence_by_row[row_id]

        for group_key, anchor_records in anchors_by_address.items():
            group_rows = same_address_groups[group_key]
            for _, voter in group_rows.iterrows():
                row_id = int(voter["_row_id"])
                if row_id in evidence_by_row or row_id in direct_row_ids or (row_id, unit) in discarded:
                    continue
                if original_links is not None and (row_id, unit) not in original_links:
                    continue
                if unit not in matcher.voter_candidate_units(voter["candidate_units"]):
                    continue
                if relation_units.get(row_id, set()) - {unit}:
                    continue
                member_link = same_address_word_link(voter, anchor_records)
                if not member_link:
                    continue
                add_household_member(
                    evidence_by_row,
                    voter,
                    member_link,
                    "same_address_word_linked_household_member",
                )

        if not evidence_by_row:
            continue

        evidence_rows = sorted(
            evidence_by_row.values(),
            key=lambda item: (
                int(item["voter"]["part"]),
                int(item["voter"]["serial_number"]),
                int(item["voter"]["_row_id"]),
            ),
        )
        unit_values = unit_output_values(config, roster_rows, unit)
        for item in evidence_rows:
            voter = item["voter"]
            row_id = int(voter["_row_id"])
            emitted_row_unit_keys.add((row_id, unit))
            if item["person_hits"] or item["relation_hits"]:
                identity_supported_row_ids.add(row_id)
            if voter["has_target_label"] and unit in matcher.voter_candidate_units(voter["identity_candidate_units"]):
                item["scopes"].add("explicit_apartment_address")
            candidates = connection_candidates(item)
            if item["person_hits"]:
                # Relation hits can distinguish roster people, while the voter retains only the own-name link.
                item = {**item, "relation_hits": []}
                candidates = [c for c in candidates if c[0] == CONNECTION_PRIORITY_VOTER_NAME]
            record = base_output_record(voter, config)
            record.update(unit_values)
            record["apartment_status"] = group_label
            set_connection_fields(record, candidates)
            record["voter_link_type"] = voter_link_type(item)
            record["_row_id"] = row_id
            records.append(record)

    for unit in sorted(roster_rows["unit"].unique()):
        explicit_rows = voters[
            (voters["address_unit"] == unit)
            & voters["has_target_label"]
        ].copy()
        if explicit_rows.empty:
            continue
        explicit_rows = explicit_rows.sort_values(["part", "serial_number", "_row_id"])
        unit_values = unit_output_values(config, roster_rows, unit)
        for _, voter in explicit_rows.iterrows():
            if int(voter["_row_id"]) in identity_supported_row_ids:
                continue
            row_unit_key = (int(voter["_row_id"]), unit)
            if row_unit_key in emitted_row_unit_keys or row_unit_key in discarded:
                continue
            if original_links is not None and row_unit_key not in original_links:
                continue
            item = {
                "voter": voter,
                "person_hits": [],
                "relation_hits": [],
                "scopes": {"explicit_apartment_address"},
                "member_links": [],
            }
            emitted_row_unit_keys.add(row_unit_key)
            record = base_output_record(voter, config)
            record.update(unit_values)
            record["apartment_status"] = UNASSIGNED_STATUS
            set_connection_fields(record, connection_candidates(item))
            record["voter_link_type"] = voter_link_type(item)
            record["_row_id"] = int(voter["_row_id"])
            records.append(record)

    # Voters whose address names the apartment but does not point to exactly one roster unit
    # (no unit read, or several possible), and who were not linked to any unit by name.
    # They are kept with the apartment but no unit, status Unmapped.
    linked_row_ids = {int(record["_row_id"]) for record in records} | identity_supported_row_ids
    unmapped_rows = voters[
        voters["has_target_label"]
        & voters["address_unit"].isna()
        & ~voters["_row_id"].isin(linked_row_ids)
    ].sort_values(["part", "serial_number", "_row_id"])
    for _, voter in unmapped_rows.iterrows():
        record = base_output_record(voter, config)
        record.update(
            {
                "apartment": config.apartment_name,
                "apartment_unit": "",
                "apartment_block": "",
                "apartment_unit_part": "",
                "apartment_status": UNMAPPED_STATUS,
                "voter_link_type": "explicit_apartment_address",
                "_row_id": int(voter["_row_id"]),
            }
        )
        set_connection_fields(record, [])
        records.append(record)

    return collapse_unresolved_group_records(pd.DataFrame(records)), unmapped_rows


def polling_booth_keys(out: pd.DataFrame) -> pd.Series:
    return out["part"].fillna("").astype(str) + "|" + out["pollingname"].fillna("").astype(str)


def matched_units_at_booth(out: pd.DataFrame) -> dict[str, set[str]]:
    units_by_booth: dict[str, set[str]] = {}
    for booth, unit in zip(polling_booth_keys(out), out["apartment_unit"]):
        if unit:
            units_by_booth.setdefault(booth, set()).add(unit)
    return units_by_booth


def other_households_matched_at_booth(out: pd.DataFrame, booth_units: dict[str, set[str]]) -> pd.Series:
    """Count the other apartment households (units) with a matched voter at each row's polling booth.

    A booth is the voter-list part with its polling station. 0 means this row's household is the
    only one matched there. Unmapped rows have no unit, so every household at their booth counts.
    """
    counts = []
    for booth, unit in zip(polling_booth_keys(out), out["apartment_unit"]):
        units = booth_units.get(booth, ())
        counts.append(len(units) - (unit in units))
    return pd.Series(counts, index=out.index, dtype=int)


def roster_rows_not_matched(
    source_rows: pd.DataFrame,
    roster_rows: pd.DataFrame,
    connected: set[tuple[str, str]],
) -> pd.DataFrame:
    """Return roster rows that no output voter row is connected through, in roster order.

    A roster person is matched when an output row in their unit names them in apartment_connection.
    Rows the matcher cannot use (blank name or no unit) are never matched, so they are listed too.
    """
    is_connected = [
        (str(unit), connection_name_key(name)) in connected
        for unit, name in zip(roster_rows["unit"], roster_rows["name"])
    ]
    # Normalization keeps the source row index through filtering.
    matched_index = roster_rows.index[is_connected]
    return source_rows[~source_rows.index.isin(matched_index)].reset_index(drop=True)


def excel_ready(frame: pd.DataFrame) -> pd.DataFrame:
    """Write text columns as text: a column read with mixed numbers and text becomes all text."""
    frame = frame.copy()
    for column in frame.columns:
        if frame[column].dtype == object:
            values = frame[column]
            frame[column] = values.where(values.isna(), values.astype(str))
    return frame


def shade_households(sheet, confidence: Iterable[str | None]) -> None:
    """Color voter rows by confidence and draw a line between flats."""
    fills = {
        level: PatternFill(fill_type="solid", fgColor=color)
        for level, color in CONFIDENCE_COLORS.items()
    }
    unit_column = next(cell.column - 1 for cell in sheet[1] if cell.value == "apartment_unit")
    rows_with_confidence = zip(sheet.iter_rows(min_row=2), confidence, strict=True)
    voter_rows = ((row, level) for row, level in rows_with_confidence if pd.notna(level))
    households = groupby(voter_rows, key=lambda item: item[0][unit_column].value)
    for household_index, (_, rows) in enumerate(households):
        for row_index, (row, level) in enumerate(rows):
            for cell in row:
                cell.fill = fills[level]
                if cell.font.color is not None and cell.font.color.type == "rgb" and cell.font.color.rgb == "FFFFFFFF":
                    font = copy(cell.font)
                    font.color = "FF17202A"
                    cell.font = font
                if household_index and row_index == 0:
                    border = copy(cell.border)
                    border.top = HOUSEHOLD_BORDER
                    cell.border = border


def format_sheet(sheet, frame: pd.DataFrame) -> None:
    """Keep literal text, add filters and column widths, and shade mapped households."""
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if cell.data_type == "f":
                cell.data_type = "s"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for position, column in enumerate(frame.columns, start=1):
        letter = get_column_letter(position)
        lengths = [len(str(column)), *(len(str(value)) for value in frame[column].dropna())]
        width = min(max(lengths) + 2, MAX_EXCEL_COLUMN_WIDTH)
        if sheet.title == UNMAPPED_HOUSEHOLDS_SHEET:
            width = max(width, len(column) + 5)
            # Keep long addresses and polling-station names readable within the width cap.
            for cell in sheet[letter][1:]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
                lines = wrap(str(cell.value or ""), width=width - 4)
                if len(lines) > 1:
                    row = sheet.row_dimensions[cell.row]
                    row.height = max(row.height or 15, 15 * len(lines))
        sheet.column_dimensions[letter].width = width


def write_output_workbook(
    destination: Path,
    mapped_voters: pd.DataFrame,
    roster_not_matched: pd.DataFrame,
    unmapped_households: pd.DataFrame,
    unassigned_voters: pd.DataFrame,
    *,
    searched_voter_list: str = "",
) -> None:
    # Keep the household summary columns and retain the full record for each moved voter.
    household_summaries = unmapped_households.assign(apartment_status=UNMAPPED_STATUS)
    unassigned = unassigned_voters.assign(
        voter_count=1,
        voter_serial_numbers=unassigned_voters["serial_number"].astype(str),
    )
    rows = [frame for frame in (household_summaries, unassigned) if not frame.empty]
    columns = [*UNMAPPED_OUTPUT_COLUMNS, "_match_confidence"]
    unmapped = (
        pd.concat(rows, ignore_index=True).reindex(columns=columns)
        if rows
        else pd.DataFrame(columns=columns)
    )
    sheets = (
        (VOTERS_SHEET, mapped_voters),
        (UNMAPPED_HOUSEHOLDS_SHEET, unmapped),
        (ROSTER_NOT_MATCHED_SHEET, roster_not_matched),
    )
    with pd.ExcelWriter(destination, engine="openpyxl") as writer:
        for sheet_name, frame in sheets:
            frame = excel_ready(frame)
            display = frame
            if sheet_name in (VOTERS_SHEET, UNMAPPED_HOUSEHOLDS_SHEET):
                strength = frame["_match_confidence"].replace({"Probable": "Medium"})
                if sheet_name == VOTERS_SHEET:
                    link_types = frame["voter_link_type"].str.split(";")
                    own_name = link_types.map(lambda kinds: "voter_name_match" in kinds)
                    household = link_types.map(
                        lambda kinds: "relation_name_match" in kinds or "same_address_household_member" in kinds
                    )
                    strength = strength.mask(household & ~own_name, strength + " - household")
                    strength = strength.mask(own_name, strength + " - name linked")
                    display = frame.assign(strength=strength)[MAPPED_OUTPUT_COLUMNS]
                else:
                    display = frame.assign(strength=strength)[UNMAPPED_OUTPUT_COLUMNS]
            display = display.drop(columns="searched_voter_list", errors="ignore").assign(
                searched_voter_list=searched_voter_list,
            )
            display.to_excel(writer, sheet_name=sheet_name, index=False)
            sheet = writer.sheets[sheet_name]
            format_sheet(sheet, display)
            if sheet_name in (VOTERS_SHEET, UNMAPPED_HOUSEHOLDS_SHEET):
                shade_households(sheet, frame["_match_confidence"])


def read_voter_source(path: Path, *, nrows: int | None = None) -> pd.DataFrame:
    """Read a prepared voter table from CSV or the first worksheet in an XLSX file."""
    if path.suffix.lower() == ".xlsx":
        voters = pd.read_excel(path, nrows=nrows, dtype={"epic_number": str})
    else:
        voters = pd.read_csv(path, nrows=nrows)

    required_columns = (set(VOTER_OUTPUT_COLUMNS) - {"voter_name"}) | {"name"}
    missing = sorted(required_columns - set(voters.columns))
    if missing:
        raise ValueError(f"{path.name} is missing required voter columns: {', '.join(missing)}")
    return voters


def run_one(
    config: ApartmentConfig,
    voter_csv: Path,
    output_xlsx: Path,
    *,
    searched_voter_list: str = "",
) -> dict[str, object]:
    """Read the roster once, write the apartment workbook, and return its run summary."""
    source_rows = read_roster_source(config)
    roster_rows = normalize_roster(config, source_rows)
    roster = roster_by_unit_group(roster_rows)
    voters = read_voter_source(voter_csv)
    voters["_row_id"] = range(len(voters))
    voters = build_address_fields(voters, roster_rows, config)
    voters = matcher.assign_households(voters)
    out, connected, unmapped_households = build_apartment_voter_rows(voters, roster_rows, roster, config)
    not_matched = roster_rows_not_matched(source_rows, roster_rows, connected)
    is_unassigned = out["apartment_status"].eq(UNASSIGNED_STATUS)
    is_mapped = out["apartment_unit"].ne("") & ~is_unassigned
    mapped_voters = out.loc[is_mapped]
    output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    write_output_workbook(
        output_xlsx, mapped_voters, not_matched, unmapped_households, out.loc[is_unassigned],
        searched_voter_list=searched_voter_list,
    )
    print(f"{config.key}: rows: {len(out)}")
    if not out.empty:
        print(out["apartment_status"].value_counts().to_string())
        print(
            "same_address_household_member_rows: "
            f"{int(out['voter_link_type'].str.contains('same_address_household_member', regex=False).sum())}"
        )
        print(
            "explicit_apartment_address_rows: "
            f"{int(out['voter_link_type'].str.contains('explicit_apartment_address', regex=False).sum())}"
        )
    print(f"roster_rows_not_matched: {len(not_matched)}")
    print(f"unmapped_households: {len(unmapped_households)}")
    print(f"output_xlsx: {output_xlsx}")
    return apartment_run_summary(config, roster_rows, out, not_matched, unmapped_households, output_xlsx)


def household_count(rows: pd.DataFrame) -> int:
    if rows.empty or "apartment_unit" not in rows:
        return 0
    return int(rows["apartment_unit"].dropna().astype(str).loc[lambda s: s.astype(bool)].nunique())


def link_type_summary(rows: pd.DataFrame, link_type: str) -> dict[str, int]:
    if rows.empty:
        return {"rows": 0, "households": 0}
    matched = rows[rows["voter_link_type"].str.contains(link_type, regex=False, na=False)]
    return {
        "rows": int(len(matched)),
        "households": household_count(matched),
    }


def exact_link_type_counts(rows: pd.DataFrame) -> dict[str, int]:
    if rows.empty:
        return {}
    return {
        str(link_type): int(count)
        for link_type, count in rows["voter_link_type"].value_counts().sort_index().items()
    }


def path_for_log(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def apartment_run_summary(
    config: ApartmentConfig,
    roster_rows: pd.DataFrame,
    output_rows: pd.DataFrame,
    roster_not_matched: pd.DataFrame,
    unmapped_households: pd.DataFrame,
    output_xlsx: Path,
) -> dict[str, object]:
    identity_rows = output_rows[
        output_rows["voter_link_type"].str.contains("voter_name_match", regex=False, na=False)
        | output_rows["voter_link_type"].str.contains("relation_name_match", regex=False, na=False)
    ] if not output_rows.empty else output_rows

    return {
        "algorithm_version": ALGORITHM_VERSION,
        "apartment_key": config.key,
        "apartment_name": config.apartment_name,
        "alternate_names": list(config.alternate_names),
        "roster_source": path_for_log(config.roster_path),
        "output_xlsx": path_for_log(output_xlsx),
        "roster_rows": int(len(roster_rows)),
        "roster_households": int(roster_rows["unit"].nunique()),
        "roster_rows_not_matched": int(len(roster_not_matched)),
        "unmapped_households": len(unmapped_households),
        "mapped_voter_rows": int(
            (output_rows["apartment_unit"].ne("") & output_rows["apartment_status"].ne(UNASSIGNED_STATUS)).sum()
        ),
        "unassigned_voter_rows": int(output_rows["apartment_status"].eq(UNASSIGNED_STATUS).sum()),
        "output_rows": int(len(output_rows)),
        "output_households": household_count(output_rows),
        "headline_match_rows": int(len(identity_rows)),
        "headline_match_households": household_count(identity_rows),
        "rows_by_status": {
            str(status): int(count)
            for status, count in output_rows["apartment_status"].value_counts().sort_index().items()
        } if not output_rows.empty else {},
        "households_by_status": {
            str(status): household_count(group)
            for status, group in output_rows.groupby("apartment_status", sort=True)
        } if not output_rows.empty else {},
        "rows_by_link_type": {
            link_type: link_type_summary(output_rows, link_type)["rows"]
            for link_type in LINK_TYPES
        },
        "households_by_link_type": {
            link_type: link_type_summary(output_rows, link_type)["households"]
            for link_type in LINK_TYPES
        },
        "rows_by_exact_link_type": exact_link_type_counts(output_rows),
    }


def write_run_log(
    output_root: Path,
    voter_csv: Path,
    apartments_csv: Path,
    summaries: list[dict[str, object]],
    *,
    searched_voter_list: str = "",
) -> Path:
    generated_at = datetime.now().astimezone()
    log_dir = output_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{generated_at.strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "apartments_csv_columns": APARTMENT_CONFIG_COLUMNS,
        "individual_related_columns": INDIVIDUAL_RELATED_COLUMNS,
        "household_related_columns": HOUSEHOLD_RELATED_COLUMNS,
        "voters_sheet_columns": [*MAPPED_OUTPUT_COLUMNS, "searched_voter_list"],
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "voter_csv": path_for_log(voter_csv),
        "searched_voter_list": searched_voter_list,
        "apartments_csv": path_for_log(apartments_csv),
        "apartments": summaries,
    }
    with log_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return log_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apartment", nargs="?", default="all")
    parser.add_argument("--apartments-file", "--apartments-csv", type=Path, help="apartment list in CSV or XLSX")
    parser.add_argument("--voter-file", "--voter-csv", type=Path, help="override the voter file from the apartment list")
    parser.add_argument("--searched-voter-list", help="AC or ward name to show in the output")
    parser.add_argument("--output-xlsx", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    apartments_file = args.apartments_file
    if apartments_file is None:
        apartments_xlsx = DEFAULT_APARTMENTS_CSV.with_suffix(".xlsx")
        apartments_file = DEFAULT_APARTMENTS_CSV
        if not apartments_file.exists() and apartments_xlsx.is_file():
            apartments_file = apartments_xlsx
    configs, configured_voter_csv, searched_voter_list = _load_apartment_run_config(apartments_file)
    voter_csv = args.voter_file or configured_voter_csv or DEFAULT_VOTER_CSV
    if args.searched_voter_list is not None:
        searched_voter_list = args.searched_voter_list.strip()
    elif args.voter_file is not None and (
        configured_voter_csv is None or args.voter_file.resolve() != configured_voter_csv.resolve()
    ):
        searched_voter_list = ""
    if args.apartment != "all" and args.apartment not in configs:
        available = ", ".join(sorted(configs))
        raise SystemExit(f"Unknown apartment key: {args.apartment}. Available keys: {available}")

    if args.apartment == "all" and args.output_xlsx:
        raise SystemExit("--output-xlsx can only be used with one apartment")
    if args.output_dir and args.output_xlsx:
        raise SystemExit("--output-dir and --output-xlsx cannot be used together")

    output_root = args.output_dir or PROJECT_ROOT / "output"
    selected = configs.values() if args.apartment == "all" else (configs[args.apartment],)
    summaries = [
        run_one(
            config, voter_csv, args.output_xlsx or output_root / f"{config.key}_voters.xlsx",
            searched_voter_list=searched_voter_list,
        )
        for config in selected
    ]
    log_path = write_run_log(
        output_root, voter_csv, apartments_file, summaries, searched_voter_list=searched_voter_list,
    )
    print(f"run_log: {log_path}")


if __name__ == "__main__":
    main()
