# Normalize raw Assembly Constituency Excel voter rolls for the matcher.
# Inputs: the first worksheet's header and data rows, with an optional row limit.
# Prefer supplied parts, recover bounded station-number gaps, and keep uncertain blocks separate.
# Retain roll numbers and relationship details when the source supplies them.
# AUTHOR: Chinmay and AI

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

import pandas as pd


AC_HEADERS = {
    "serial_number": "SI. NO.",
    "roll_number": "Roll No.",
    "epic_number": "EPIC ID",
    "name": "Name",
    "relation_type": "Relation",
    "relation_name": "Relative's Name",
    "house_number": "House Number",
    "age": "Age",
    "gender": "Gender",
    "section_raw": "Section No. and Name",
    "ward": "Ward",
    "pincode": "Pin Code",
    "pollingname": "No. and Name of Polling Station",
    "pollingaddress": "Address of Polling Station",
}
AC_SIGNATURE = ("SI. NO.", "EPIC ID", "No. Name and Reservation Status of Assembly Constituency")
AC_REQUIRED = ("serial_number", "epic_number", "name", "house_number", "section_raw")
AC_OUTPUT_COLUMNS = (*AC_HEADERS, "part", "corporation")
PART_HEADER_KEYS = ("part", "partno", "partnumber")
STATION_PREFIX = re.compile(r"^\s*(\d+)\s*[-–—.:]\s*\S")
LEGACY_RELATIONS = {
    "fathersname": "Father", "husbandsname": "Husband", "mothersname": "Mother", "others": "Other",
}


def header_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def cell_value(row: tuple, index: int | None) -> object:
    return row[index] if index is not None and index < len(row) else None


def text_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def read_ac_export(
    header: tuple,
    rows: Iterable[tuple],
    filename: str,
    *,
    nrows: int | None = None,
) -> pd.DataFrame | None:
    """Return normalized voter rows for a recognized AC export, or None for other inputs."""
    keys = [header_key(cell) for cell in header]
    positions = {key: index for index, key in enumerate(keys) if key}
    if not all(header_key(field) in positions for field in AC_SIGNATURE):
        return None
    if len(positions) != sum(bool(key) for key in keys):
        raise ValueError(f"{filename}: the AC worksheet contains duplicate column names")
    indexes = {field: positions.get(header_key(label)) for field, label in AC_HEADERS.items()}
    part_index = next((positions[key] for key in PART_HEADER_KEYS if key in positions), None)
    required = AC_REQUIRED if part_index is not None else (*AC_REQUIRED, "pollingname", "pollingaddress")
    missing = [AC_HEADERS[field] for field in required if indexes[field] is None]
    if missing:
        raise ValueError(f"{filename} is missing required AC export columns: {', '.join(missing)}")
    if nrows is not None and nrows < 0:
        raise ValueError("nrows must be nonnegative")
    if nrows == 0:
        return pd.DataFrame(columns=AC_OUTPUT_COLUMNS)

    occupied_numbers: set[int] = set()
    proposed_gaps: list[dict[int, int]] = []

    def records():
        unnumbered_groups = 0
        previous_station = None
        previous_roll_number = None
        previous_station_number = None
        pending_groups: list[int] = []
        gap_has_roll_evidence = True
        for number, row in enumerate(rows, start=2):
            if not any(value is not None and str(value).strip() for value in row):
                continue
            record = {field: cell_value(row, index) for field, index in indexes.items()}
            serial = text_value(record["serial_number"]).strip()
            if not serial.isdecimal():
                raise ValueError(f"{filename}, row {number}: SI. NO. must be a nonnegative integer")
            record["serial_number"] = int(serial)
            # Keep text identifiers and house numbers, including source leading zeros.
            for field in ("epic_number", "name", "house_number", "relation_name", "relation_type"):
                record[field] = text_value(record[field]) or None

            # The current export has Relation; older files prefix the relative's name.
            relative = record["relation_name"] or ""
            prefix, separator, remainder = relative.partition(":")
            legacy_type = LEGACY_RELATIONS.get(header_key(prefix)) if separator else None
            if legacy_type:
                record["relation_name"] = remainder.strip() or None
            record["relation_type"] = (record["relation_type"] or "").strip() or legacy_type

            # The electoral-roll part can differ from the polling-station number.
            supplied_part = text_value(cell_value(row, part_index)).strip()
            station = STATION_PREFIX.match(text_value(record["pollingname"]))
            station_number = int(station.group(1)) if station else None
            if supplied_part and not supplied_part.isdecimal():
                raise ValueError(f"{filename}, row {number}: Part must be a nonnegative integer")
            if supplied_part or station_number is not None:
                part = int(supplied_part) if supplied_part else station_number
                record["part"] = part
                occupied_numbers.add(part)
                if station_number is not None:
                    occupied_numbers.add(station_number)
                    if (pending_groups and gap_has_roll_evidence and previous_station_number is not None
                            and station_number - previous_station_number - 1 == len(pending_groups)):
                        proposed_gaps.append(dict(zip(pending_groups, range(previous_station_number + 1, station_number))))
                # A supplied part without a numbered station cannot bound a station gap.
                pending_groups.clear()
                gap_has_roll_evidence = True
                previous_station_number = station_number
                previous_station = previous_roll_number = None
            else:
                # Keep a distinct negative key for each block until the next station is known.
                station_key = (record["pollingname"], record["pollingaddress"], record["ward"])
                roll_text = text_value(record["roll_number"]).strip()
                roll_number = int(roll_text) if roll_text.isdecimal() else None
                starts_block = (
                    station_key != previous_station or not record["pollingaddress"]
                    or roll_number is None or previous_roll_number is None or roll_number <= previous_roll_number
                )
                if starts_block:
                    unnumbered_groups += 1
                    pending_groups.append(-unnumbered_groups)
                if roll_number is None or not record["pollingaddress"]:
                    gap_has_roll_evidence = False
                record["part"] = -unnumbered_groups
                previous_station, previous_roll_number = station_key, roll_number
            record["corporation"] = None
            yield tuple(record[field] for field in AC_OUTPUT_COLUMNS)

    voters = pd.DataFrame.from_records(records(), columns=AC_OUTPUT_COLUMNS, nrows=nrows)
    # Check the entire input before assigning numbers: a repeated or already-used
    # number could otherwise merge distinct station groups.
    proposed_numbers = Counter(number for gap in proposed_gaps for number in gap.values())
    recovered = {
        local_part: station_number
        for gap in proposed_gaps
        if all(number not in occupied_numbers and proposed_numbers[number] == 1 for number in gap.values())
        for local_part, station_number in gap.items()
    }
    if recovered:
        voters["part"] = voters["part"].replace(recovered)
    return voters
