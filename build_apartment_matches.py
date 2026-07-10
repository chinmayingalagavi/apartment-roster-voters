#!/usr/bin/env python3
"""Build linked voter CSVs for apartments from standardized roster CSVs."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pandas as pd

import matching as matcher


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_APARTMENTS_CSV = PROJECT_ROOT / "apartments.csv"
DEFAULT_VOTER_CSV = PROJECT_ROOT / "data" / "voters.csv"
UNIT_PAD_WIDTH = 3

VOTER_OUTPUT_COLUMNS = [
    "serial_number",
    "epic_number",
    "name",
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

APARTMENT_OUTPUT_COLUMNS = [
    "apartment",
    "apartment_unit",
    "apartment_block",
    "apartment_unit_part",
    "apartment_status",
    "apartment_names_in_house",
    "voter_link_type",
]

OUTPUT_COLUMNS = [*VOTER_OUTPUT_COLUMNS, *APARTMENT_OUTPUT_COLUMNS]

INDIVIDUAL_RELATED_COLUMNS = [
    "serial_number",
    "epic_number",
    "name",
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
    "apartment_names_in_house",
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

APARTMENT_CONFIG_REQUIRED_COLUMNS = [
    "key",
    "apartment_name",
    "roster_path",
    "keywords",
]

APARTMENT_CONFIG_OPTIONAL_COLUMNS = [
    "extra_filler_terms",
    "output_path",
]

APARTMENT_CONFIG_COLUMNS = [
    *APARTMENT_CONFIG_REQUIRED_COLUMNS,
    *APARTMENT_CONFIG_OPTIONAL_COLUMNS,
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
    output_path: Path
    keywords: tuple[str, ...]
    extra_filler_terms: tuple[str, ...] = ()


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
    text = matcher.normalize_space(value)
    if not text:
        if default is not None:
            return default
        raise ValueError("missing path")

    path = Path(text).expanduser()
    if path.is_absolute():
        return path
    return base_dir / path


def load_apartment_configs(apartments_csv: Path) -> dict[str, ApartmentConfig]:
    if not apartments_csv.exists():
        raise SystemExit(f"Apartment list CSV not found: {apartments_csv}")

    rows = pd.read_csv(apartments_csv, dtype=str, keep_default_na=False)
    missing_columns = [column for column in APARTMENT_CONFIG_REQUIRED_COLUMNS if column not in rows.columns]
    if missing_columns:
        raise SystemExit(
            f"{apartments_csv} is missing required columns: {', '.join(missing_columns)}"
        )
    for column in APARTMENT_CONFIG_OPTIONAL_COLUMNS:
        if column not in rows.columns:
            rows[column] = ""

    base_dir = apartments_csv.parent
    configs: dict[str, ApartmentConfig] = {}
    for row_number, row in rows.iterrows():
        display_row_number = int(row_number) + 2
        key = matcher.normalize_space(row["key"])
        apartment_name = matcher.normalize_space(row["apartment_name"])
        roster_path_text = matcher.normalize_space(row["roster_path"])
        keywords = split_config_terms(row["keywords"])
        extra_filler_terms = split_config_terms(row["extra_filler_terms"])

        missing_values = []
        if not key:
            missing_values.append("key")
        if not apartment_name:
            missing_values.append("apartment_name")
        if not roster_path_text:
            missing_values.append("roster_path")
        if not keywords:
            missing_values.append("keywords")
        if missing_values:
            raise SystemExit(
                f"{apartments_csv} row {display_row_number} is missing: {', '.join(missing_values)}"
            )
        if key in configs:
            raise SystemExit(f"{apartments_csv} has duplicate key: {key}")

        default_output_path = PROJECT_ROOT / "outputs" / f"{key}_voters.csv"
        configs[key] = ApartmentConfig(
            key=key,
            apartment_name=apartment_name,
            roster_path=resolve_config_path(roster_path_text, base_dir),
            output_path=resolve_config_path(row["output_path"], base_dir, default_output_path),
            keywords=keywords,
            extra_filler_terms=extra_filler_terms,
        )

    if not configs:
        raise SystemExit(f"{apartments_csv} does not contain any apartment rows")
    return configs


def compile_terms_re(terms: Iterable[str]) -> re.Pattern[str]:
    patterns: list[str] = []
    for term in terms:
        normalized = matcher.normalize_address(term)
        if not normalized:
            continue
        parts = normalized.split()
        if len(parts) == 1:
            patterns.append(rf"\b{re.escape(parts[0])}\b")
        else:
            patterns.append(r"\b" + r"\s*".join(re.escape(part) for part in parts) + r"\b")
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
    terms: list[str] = []
    for term in (*COMMON_ADDRESS_FILLERS, *config.keywords, *config.extra_filler_terms):
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


def roster_names(roster_rows: pd.DataFrame, unit: str, group_label: str | None = None) -> str:
    rows = roster_rows[roster_rows["unit"] == unit]
    if group_label is not None:
        rows = rows[rows["group_label"] == group_label]
    return "; ".join(rows["name"].astype(str).drop_duplicates().tolist())


def load_roster(config: ApartmentConfig) -> pd.DataFrame:
    raw = pd.read_csv(config.roster_path, dtype=str, keep_default_na=False)
    roster = raw.copy()

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
    label_re = compile_terms_re(config.keywords)
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
                    }
    return None


def add_evidence(
    evidence_by_row: dict[int, dict[str, object]],
    voter: pd.Series,
    person_hits: list[dict[str, object]],
    relation_hits: list[dict[str, object]],
    scope: str,
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
    record["person_hits"].extend(person_hits)
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


def add_explicit_apartment_address(evidence_by_row: dict[int, dict[str, object]], voter: pd.Series) -> None:
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
    record["scopes"].add("explicit_apartment_address")


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


def number_only_identity_units(
    voter: pd.Series,
    number_only_group_cache: dict[str, dict[str, object]],
) -> set[str]:
    group_key = str(voter.get("number_only_address_key", ""))
    if not group_key:
        return set()
    cached = number_only_group_cache.get(group_key)
    if not cached:
        return set()
    return set(cached["row_identity_hit_units"].get(int(voter["_row_id"]), []))


def load_data(
    voter_csv: Path,
    config: ApartmentConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[tuple[str, str], list[dict[str, object]]]]:
    voters = pd.read_csv(voter_csv).copy()
    voters["_row_id"] = range(len(voters))
    roster_rows = load_roster(config)
    voters = build_address_fields(voters, roster_rows, config)
    voters = matcher.assign_households(voters)
    return voters, roster_rows, roster_by_unit_group(roster_rows)


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
        "name": voter["name"],
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


def collapse_unresolved_group_records(
    out: pd.DataFrame,
    roster_rows: pd.DataFrame,
    config: ApartmentConfig,
) -> pd.DataFrame:
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

        row = group.iloc[0].copy()
        unit = str(row["apartment_unit"])
        row["apartment_status"] = "Unassigned"
        row["apartment_names_in_house"] = roster_names(roster_rows, unit)
        row["voter_link_type"] = combine_link_types(group["voter_link_type"])
        collapsed.append(row.to_dict())

    return pd.DataFrame(collapsed)


def build_apartment_voter_rows(
    voters: pd.DataFrame,
    roster_rows: pd.DataFrame,
    roster: dict[tuple[str, str], list[dict[str, object]]],
    config: ApartmentConfig,
) -> pd.DataFrame:
    usable = voters.copy()
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
    records: list[dict[str, object]] = []
    emitted_row_unit_keys: set[tuple[int, str]] = set()
    identity_supported_row_ids: set[int] = set()

    for unit, group_label in sorted(roster):
        unit_roster = roster[(unit, group_label)]
        unit_rows = identity_usable[
            identity_usable["identity_candidate_units"].map(lambda units: unit in matcher.voter_candidate_units(units))
        ]
        if unit_rows.empty:
            continue

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

                household_details: dict[tuple[str, str], dict[str, object]] = {}
                row_identity_hit_keys: dict[int, list[tuple[str, str]]] = {}
                for candidate_key in candidate_households:
                    evaluation = matcher.evaluate_voter_rows_against_unit(group_rows, roster[candidate_key])
                    for detail in evaluation["row_details"]:
                        if not detail["person_hits"] and not detail["relation_hits"]:
                            continue
                        row_id = int(detail["voter"]["_row_id"])
                        row_identity_hit_keys.setdefault(row_id, []).append(candidate_key)
                    household_details[candidate_key] = evaluation
                number_only_group_cache[group_key] = {
                    "household_details": household_details,
                    "row_identity_hit_units": {
                        row_id: sorted({candidate_key[0] for candidate_key in candidate_keys})
                        for row_id, candidate_keys in row_identity_hit_keys.items()
                    },
                }

            cached = number_only_group_cache[group_key]
            for detail in cached["household_details"].get((unit, group_label), {}).get("row_details", []):
                if not detail["person_hits"] and not detail["relation_hits"]:
                    continue
                if set(cached["row_identity_hit_units"].get(int(detail["voter"]["_row_id"]), [])) != {unit}:
                    continue
                add_evidence(
                    evidence_by_row,
                    detail["voter"],
                    detail["person_hits"],
                    detail["relation_hits"],
                    "number_only_address_relation_unique",
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

                household_details: dict[tuple[str, str], dict[str, object]] = {}
                row_identity_hit_keys: dict[int, list[tuple[str, str]]] = {}
                for candidate_key in candidate_households:
                    evaluation = matcher.evaluate_voter_rows_against_unit(group_rows, roster[candidate_key])
                    for detail in evaluation["row_details"]:
                        if not detail["person_hits"] and not detail["relation_hits"]:
                            continue
                        row_id = int(detail["voter"]["_row_id"])
                        row_identity_hit_keys.setdefault(row_id, []).append(candidate_key)
                    household_details[candidate_key] = evaluation
                long_number_group_cache[group_key] = {
                    "household_details": household_details,
                    "row_identity_hit_units": {
                        row_id: sorted({candidate_key[0] for candidate_key in candidate_keys})
                        for row_id, candidate_keys in row_identity_hit_keys.items()
                    },
                }

            cached = long_number_group_cache[group_key]
            for detail in cached["household_details"].get((unit, group_label), {}).get("row_details", []):
                if not detail["person_hits"] and not detail["relation_hits"]:
                    continue
                if set(cached["row_identity_hit_units"].get(int(detail["voter"]["_row_id"]), [])) != {unit}:
                    continue
                add_evidence(
                    evidence_by_row,
                    detail["voter"],
                    detail["person_hits"],
                    detail["relation_hits"],
                    "long_number_address_relation_unique",
                )

        direct_evidence_row_ids = {
            row_id
            for row_id, record in evidence_by_row.items()
            if record["person_hits"] or record["relation_hits"]
        }
        anchored_group_keys = sorted(
            {
                str(record["voter"].get("same_address_group_key", ""))
                for row_id, record in evidence_by_row.items()
                if row_id in direct_evidence_row_ids and str(record["voter"].get("same_address_group_key", ""))
            }
        )
        for group_key in anchored_group_keys:
            group_rows = same_address_groups.get(group_key)
            if group_rows is None or group_rows.empty:
                continue
            anchor_records = [
                evidence_by_row[row_id]
                for row_id in direct_evidence_row_ids
                if str(evidence_by_row[row_id]["voter"].get("same_address_group_key", "")) == group_key
            ]
            for _, voter in group_rows.iterrows():
                if int(voter["_row_id"]) in evidence_by_row:
                    continue
                if unit not in matcher.voter_candidate_units(voter["candidate_units"]):
                    continue
                hit_units = number_only_identity_units(voter, number_only_group_cache)
                if hit_units and unit not in hit_units:
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

        explicit_rows = unit_rows[
            unit_rows["identity_candidate_units"].map(lambda units: unit in matcher.voter_candidate_units(units))
            & unit_rows["has_target_label"]
        ]
        for _, voter in explicit_rows.iterrows():
            if int(voter["_row_id"]) not in evidence_by_row:
                continue
            add_explicit_apartment_address(evidence_by_row, voter)

        all_person_hits: list[dict[str, object]] = []
        all_relation_hits: list[dict[str, object]] = []
        for record in evidence_by_row.values():
            record["person_hits"] = matcher.dedupe_hits(
                record["person_hits"],
                ("voter_row_id", "roster_name_norm", "match_source", "match_kind", "match_detail"),
            )
            record["relation_hits"] = matcher.dedupe_hits(
                record["relation_hits"],
                ("voter_row_id", "roster_name_norm", "match_source", "match_kind", "match_detail"),
            )
            record["member_links"] = matcher.dedupe_hits(
                record["member_links"],
                ("voter_source", "voter_word", "anchor_serial", "anchor_source", "anchor_word", "match_kind"),
            )
            all_person_hits.extend(record["person_hits"])
            all_relation_hits.extend(record["relation_hits"])
            if record["person_hits"] or record["relation_hits"]:
                identity_supported_row_ids.add(int(record["voter"]["_row_id"]))

        has_explicit_address = any(
            "explicit_apartment_address" in record["scopes"]
            for record in evidence_by_row.values()
        )
        if not all_person_hits and not all_relation_hits and not has_explicit_address:
            continue

        names = roster_names(roster_rows, unit, group_label)
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
            emitted_row_unit_keys.add((int(voter["_row_id"]), unit))
            record = base_output_record(voter, config)
            record.update(unit_values)
            record["apartment_status"] = group_label
            record["apartment_names_in_house"] = names
            record["voter_link_type"] = voter_link_type(item)
            record["_row_id"] = int(voter["_row_id"])
            records.append(record)

    for unit in sorted(roster_rows["unit"].unique()):
        explicit_rows = usable[
            (usable["address_unit"] == unit)
            & usable["has_target_label"]
        ].copy()
        if explicit_rows.empty:
            continue
        names = roster_names(roster_rows, unit)
        explicit_rows = explicit_rows.sort_values(["part", "serial_number", "_row_id"])
        unit_values = unit_output_values(config, roster_rows, unit)
        for _, voter in explicit_rows.iterrows():
            if int(voter["_row_id"]) in identity_supported_row_ids:
                continue
            row_unit_key = (int(voter["_row_id"]), unit)
            if row_unit_key in emitted_row_unit_keys:
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
            record["apartment_status"] = "Unassigned"
            record["apartment_names_in_house"] = names
            record["voter_link_type"] = voter_link_type(item)
            record["_row_id"] = int(voter["_row_id"])
            records.append(record)

    out = pd.DataFrame(records)
    out = collapse_unresolved_group_records(out, roster_rows, config)
    if not out.empty:
        sort_cols = ["apartment_unit", "apartment_status", "part", "serial_number"]
        out = out.sort_values(sort_cols).reset_index(drop=True)
        out = out.drop(columns=["_row_id"])
        out = out[OUTPUT_COLUMNS]
    return out


def run_one(config: ApartmentConfig, voter_csv: Path, output_csv: Path | None = None) -> pd.DataFrame:
    voters, roster_rows, roster = load_data(voter_csv, config)
    out = build_apartment_voter_rows(voters, roster_rows, roster, config)
    destination = output_csv or config.output_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(destination, index=False)
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
    print(f"output_csv: {destination}")
    return out


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
    output_csv: Path,
) -> dict[str, object]:
    identity_rows = output_rows[
        output_rows["voter_link_type"].str.contains("voter_name_match", regex=False, na=False)
        | output_rows["voter_link_type"].str.contains("relation_name_match", regex=False, na=False)
    ] if not output_rows.empty else output_rows

    return {
        "apartment_key": config.key,
        "apartment_name": config.apartment_name,
        "roster_csv": path_for_log(config.roster_path),
        "output_csv": path_for_log(output_csv),
        "roster_rows": int(len(roster_rows)),
        "roster_households": int(roster_rows["unit"].nunique()),
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
) -> Path:
    generated_at = datetime.now().astimezone()
    log_dir = output_root / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"run_{generated_at.strftime('%Y%m%d_%H%M%S')}.json"
    payload = {
        "apartments_csv_columns": APARTMENT_CONFIG_COLUMNS,
        "individual_related_columns": INDIVIDUAL_RELATED_COLUMNS,
        "household_related_columns": HOUSEHOLD_RELATED_COLUMNS,
        "apartment_output_csv_columns": OUTPUT_COLUMNS,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "voter_csv": path_for_log(voter_csv),
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
    parser.add_argument("--apartments-csv", type=Path, default=DEFAULT_APARTMENTS_CSV)
    parser.add_argument("--voter-csv", type=Path, default=DEFAULT_VOTER_CSV)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    configs = load_apartment_configs(args.apartments_csv)
    if args.apartment != "all" and args.apartment not in configs:
        available = ", ".join(sorted(configs))
        raise SystemExit(f"Unknown apartment key: {args.apartment}. Available keys: {available}")

    if args.apartment == "all":
        if args.output_csv:
            raise SystemExit("--output-csv can only be used with one apartment")
        output_root = args.output_dir or PROJECT_ROOT / "outputs"
        output_root.mkdir(parents=True, exist_ok=True)
        summaries: list[dict[str, object]] = []
        for config in configs.values():
            output_csv = output_root / f"{config.key}_voters.csv" if args.output_dir else config.output_path
            out = run_one(config, args.voter_csv, output_csv)
            roster_rows = load_roster(config)
            summaries.append(apartment_run_summary(config, roster_rows, out, output_csv))
        log_path = write_run_log(output_root, args.voter_csv, args.apartments_csv, summaries)
        print(f"run_log: {log_path}")
        return

    if args.output_dir:
        if args.output_csv:
            raise SystemExit("--output-dir and --output-csv cannot be used together")
        config = configs[args.apartment]
        args.output_dir.mkdir(parents=True, exist_ok=True)
        output_csv = args.output_dir / f"{config.key}_voters.csv"
        out = run_one(config, args.voter_csv, output_csv)
        roster_rows = load_roster(config)
        log_path = write_run_log(
            args.output_dir,
            args.voter_csv,
            args.apartments_csv,
            [apartment_run_summary(config, roster_rows, out, output_csv)],
        )
        print(f"run_log: {log_path}")
        return

    config = configs[args.apartment]
    out = run_one(config, args.voter_csv, args.output_csv)
    output_csv = args.output_csv or config.output_path
    roster_rows = load_roster(config)
    log_path = write_run_log(
        PROJECT_ROOT / "outputs",
        args.voter_csv,
        args.apartments_csv,
        [apartment_run_summary(config, roster_rows, out, output_csv)],
    )
    print(f"run_log: {log_path}")


if __name__ == "__main__":
    main()
