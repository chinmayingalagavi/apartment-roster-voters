# Convert an AC voter XLSX to standard voter fields plus the raw relative field and provenance; inputs are --source, --sheet, --output, and an explicit station-number grouping option.
# AUTHOR: Chinmay and AI
"""Stream the supplied AC workbook without changing its source records."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import time

from openpyxl import load_workbook


# Explicit source mappings keep absent metadata separate from source data.
OUTPUT_COLUMNS = [
    "serial_number", "epic_number", "name", "relation_type", "relation_name",
    "house_number", "age", "gender", "section_raw", "part", "ward",
    "corporation", "pincode", "pollingname", "pollingaddress",
    "source_relation_name",
]
SOURCE_COLUMNS = {
    "serial_number": "SI. NO.",
    "epic_number": "EPIC ID",
    "name": "Name",
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
REQUIRED_SOURCE_FIELDS = {"serial_number", "epic_number", "name", "house_number", "pollingname"}
METADATA_COLUMNS = {
    "assembly_constituency": "No. Name and Reservation Status of Assembly Constituency",
    "source_update_date": "Date Of Updation:",
}
STATION_NUMBER_RE = re.compile(r"^\s*(\d+)\s*[-–—.:]\s*\S")
RELATION_LABEL_TYPES = {
    "fathersname": "Father", "husbandsname": "Husband",
    "mothersname": "Mother", "others": "Other",
}


# Normalize header punctuation only; never use fuzzy header or field guesses.
def normalized_header(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def text_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


# Split only explicit source labels. Unknown prefixes and unlabeled names are
# retained verbatim; no relationship is inferred from a person's name.
def parse_relative_label(value: object) -> tuple[str, str]:
    raw = text_value(value)
    prefix, separator, remainder = raw.partition(":")
    kind = RELATION_LABEL_TYPES.get(normalized_header(prefix)) if separator else None
    return (kind, remainder.strip()) if kind else ("", raw)


def integer_value(value: object, source_row: int, column: str) -> int:
    value_text = text_value(value).strip()
    if not re.fullmatch(r"\d+", value_text):
        raise ValueError(f"Source row {source_row}: {column} is missing or not a nonnegative integer")
    return int(value_text)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# Write one row at a time. Counters grow with columns/stations, not with voter count.
def convert(source: Path, output: Path, sheet_name: str, station_number_as_part: bool) -> dict[str, object]:
    if not station_number_as_part:
        raise ValueError("The source has no Part field. Explicitly pass --station-number-as-part to use its polling-station number as the grouping key.")
    started = time.monotonic()
    source = source.resolve()
    output = output.resolve()
    if source == output or output.suffix.lower() != ".csv":
        raise ValueError("Choose a separate .csv output path; the source workbook must be preserved")
    book = load_workbook(source, read_only=True, data_only=True)
    temporary_csv = output.with_name(output.name + ".tmp")
    duplicate_directory = tempfile.TemporaryDirectory(prefix="ac-voter-identifiers-")
    identifiers = sqlite3.connect(Path(duplicate_directory.name) / "identifiers.sqlite")
    identifiers.execute("CREATE TABLE epics (value TEXT PRIMARY KEY)")
    try:
        if sheet_name not in book.sheetnames:
            raise ValueError(f"Sheet {sheet_name!r} not found; available: {book.sheetnames}")
        sheet = book[sheet_name]
        rows = sheet.iter_rows(values_only=True)
        headers = next(rows, None)
        if not headers:
            raise ValueError("The source sheet has no header row")
        positions: dict[str, int] = {}
        for index, header in enumerate(headers):
            key = normalized_header(header)
            if key in positions:
                raise ValueError(f"Duplicate normalized source header: {header!r}")
            positions[key] = index
        indexes = {
            target: positions[normalized_header(header)]
            for target, header in SOURCE_COLUMNS.items()
            if normalized_header(header) in positions
        }
        missing = sorted(REQUIRED_SOURCE_FIELDS - indexes.keys())
        if missing:
            raise ValueError(f"Required source columns missing: {', '.join(missing)}")
        metadata_indexes = {
            target: positions[normalized_header(header)]
            for target, header in METADATA_COLUMNS.items()
            if normalized_header(header) in positions
        }
        derived = {"part", "relation_type", "source_relation_name"}
        unavailable = [column for column in OUTPUT_COLUMNS if column not in indexes and column not in derived]
        print(json.dumps({"sheet": sheet_name, "declared_voter_rows": sheet.max_row - 1, "mapping": {key: SOURCE_COLUMNS[key] for key in indexes}, "blank_unavailable_columns": unavailable, "part_derivation": "integer prefix of source polling-station number/name"}), flush=True)

        output.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        skipped_empty = 0
        blank_counts: Counter[str] = Counter()
        station_counts: Counter[int] = Counter()
        station_pairs: set[tuple[str, str]] = set()
        metadata_values: dict[str, set[str]] = {key: set() for key in metadata_indexes}
        epic_types: Counter[str] = Counter()
        duplicate_epic_rows = 0
        relation_type_counts: Counter[str] = Counter()
        unknown_relation_prefix_rows = 0
        serial_min: int | None = None
        serial_max: int | None = None
        with temporary_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS)
            writer.writeheader()
            for source_row, values in enumerate(rows, start=2):
                if not any(value is not None and str(value).strip() for value in values):
                    skipped_empty += 1
                    continue
                record: dict[str, object] = {column: "" for column in OUTPUT_COLUMNS}
                for target, index in indexes.items():
                    record[target] = text_value(values[index] if index < len(values) else None)
                record["serial_number"] = integer_value(record["serial_number"], source_row, "serial_number")
                station_match = STATION_NUMBER_RE.match(str(record["pollingname"]))
                if not station_match:
                    raise ValueError(f"Source row {source_row}: polling-station number is absent or ambiguous")
                record["part"] = int(station_match.group(1))
                record["source_relation_name"] = record["relation_name"]
                kind, relative = parse_relative_label(record["source_relation_name"])
                record["relation_type"], record["relation_name"] = kind, relative
                if kind:
                    relation_type_counts[kind] += 1
                elif ":" in str(record["source_relation_name"]):
                    unknown_relation_prefix_rows += 1
                # Real missing values remain blank. Missing source columns and invalid
                # serial/station identifiers fail above; records are never guessed or dropped.
                epic_types[type(values[indexes["epic_number"]]).__name__] += 1
                if str(record["epic_number"]).strip():
                    cursor = identifiers.execute("INSERT OR IGNORE INTO epics VALUES (?)", (record["epic_number"],))
                    duplicate_epic_rows += int(cursor.rowcount == 0)
                for column, value in record.items():
                    if value == "":
                        blank_counts[column] += 1
                for key, index in metadata_indexes.items():
                    metadata_values[key].add(text_value(values[index]))
                serial = int(record["serial_number"])
                serial_min = serial if serial_min is None else min(serial_min, serial)
                serial_max = serial if serial_max is None else max(serial_max, serial)
                station_counts[int(record["part"])] += 1
                station_pairs.add((str(record["pollingname"]), str(record["pollingaddress"])))
                writer.writerow(record)
                count += 1
                if count % 100000 == 0:
                    print(f"Converted {count:,} voter rows", flush=True)
        if not count:
            raise ValueError("No voter rows found")

        # Publish complete outputs atomically and record their source lineage.
        temporary_csv.replace(output)
        payload = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_file": str(source),
            "source_sha256": file_hash(source),
            "source_sheet": sheet_name,
            "source_headers": list(headers),
            "source_declared_rows_including_header": sheet.max_row,
            "output_file": str(output),
            "output_sha256": file_hash(output),
            "output_columns": OUTPUT_COLUMNS,
            "row_count": count,
            "empty_source_rows_skipped": skipped_empty,
            "column_mapping": {key: SOURCE_COLUMNS[key] for key in indexes},
            "unavailable_columns_written_blank": unavailable,
            "part_derivation": "Explicit integer prefix of 'No. and Name of Polling Station', used as a local station-number grouping key. The source has no separate electoral-roll part field.",
            "serial_number_semantics": "Original global source SI. NO. preserved, not regenerated as within-station serial numbers.",
            "epic_storage": "CSV text copied from source; no numeric coercion, case changes, deduplication, or guessed leading zeros.",
            "epic_source_value_types": dict(epic_types),
            "unique_nonblank_epic_count": identifiers.execute("SELECT COUNT(*) FROM epics").fetchone()[0],
            "duplicate_nonblank_epic_rows": duplicate_epic_rows,
            "duplicate_handling": "All source rows are preserved; duplicates are counted with a temporary disk-backed identifier index.",
            "relative_name_handling": "Recognized explicit prefix before the first colon maps to relation_type; the remainder maps to relation_name. Original text is retained in source_relation_name. Unknown prefixes and plain names remain unmodified; no relationship is inferred.",
            "relation_label_mapping": RELATION_LABEL_TYPES,
            "relation_type_counts": dict(relation_type_counts),
            "unrecognized_relation_prefix_rows": unknown_relation_prefix_rows,
            "blank_cell_counts": dict(blank_counts),
            "station_number_count": len(station_counts),
            "station_name_address_pair_count": len(station_pairs),
            "rows_by_station_number": {str(key): value for key, value in sorted(station_counts.items())},
            "source_metadata_values": {key: sorted(values) for key, values in metadata_values.items()},
            "serial_number_min": serial_min,
            "serial_number_max": serial_max,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "comparison_note": "The AC and local ward CSV are independent source extracts. Matching their release dates or station numbering has not been assumed.",
        }
        provenance_path = output.with_suffix(".provenance.json")
        temporary_json = provenance_path.with_name(provenance_path.name + ".tmp")
        temporary_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary_json.replace(provenance_path)
        print(json.dumps({"row_count": count, "station_number_count": len(station_counts), "station_pair_count": len(station_pairs), "output": str(output), "provenance": str(provenance_path), "elapsed_seconds": payload["elapsed_seconds"]}), flush=True)
        return payload
    finally:
        book.close()
        identifiers.close()
        duplicate_directory.cleanup()
        if temporary_csv.exists():
            temporary_csv.unlink()


# Command-line inputs make the conversion repeatable without editing paths.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sheet", default="Voters_1")
    parser.add_argument("--station-number-as-part", action="store_true")
    args = parser.parse_args()
    convert(args.source, args.output, args.sheet, args.station_number_as_part)


if __name__ == "__main__":
    main()
