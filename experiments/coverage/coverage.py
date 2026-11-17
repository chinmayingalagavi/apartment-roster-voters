#!/usr/bin/env python3
# Compare manually graded historical candidate links with saved Bangalore South outputs.
# Inputs are independent review workbooks and pre/post-filter workbooks in the project folder.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
import csv
from pathlib import Path

from openpyxl import load_workbook


PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT.parent
REVIEWS = {
    "concorde": ROOT / "agents/research/concorde-first-pass/concorde_AI_review.xlsx",
    "purnima": ROOT / "agents/drafts/purnima_independent_full.xlsx",
    "silicon_oasis": ROOT / "agents/drafts/silicon_independent_full.xlsx",
    "tirumala_vintage": ROOT / "agents/drafts/tirumala_independent_full.xlsx",
}


def mapped_rows(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    values = iter(workbook["voters_mapped_tohouse"].values)
    columns = next(values)
    rows = [dict(zip(columns, values_row)) for values_row in values]
    workbook.close()
    return [row for row in rows if row.get("serial_number") is not None and row.get("apartment_unit")]


def key(row):
    """Use voter serial, proposed flat and roster status to identify a candidate link."""
    return str(row["serial_number"]), str(row["apartment_unit"]), str(row.get("apartment_status") or "")


def main():
    table = []
    for apartment, review in REVIEWS.items():
        reviews = mapped_rows(review)
        before = mapped_rows(PROJECT / "output/ac-named" / f"{apartment}_voters.xlsx")
        after = mapped_rows(PROJECT / "output/ac-no-grey" / f"{apartment}_voters.xlsx")
        labels_by_key = defaultdict(set)
        for row in reviews:
            labels_by_key[key(row)].add(row["strength"])
        if apartment == "concorde":
            # The filtered review workbook omitted No Match rows. Recover them from the
            # identical pre-scoring candidate snapshot and verify the reported count.
            original = mapped_rows(
                ROOT / "agents/research/concorde-first-pass/concorde_before_scoring.xlsx"
            )
            original_keys = {key(row) for row in original}
            if len(original_keys) != len(original) or not set(labels_by_key).issubset(original_keys):
                raise ValueError("Concorde source candidates do not uniquely contain the reviewed links")
            inferred_no_match = original_keys - set(labels_by_key)
            if len(inferred_no_match) != 502:
                raise ValueError("Concorde omitted-row count does not match the review report")
            for link in inferred_no_match:
                labels_by_key[link].add("No Match")
        ambiguous = sum(len(labels) > 1 for labels in labels_by_key.values())
        print(apartment, "reviewed rows", len(reviews), "unique keys", len(labels_by_key), "conflicting labels", ambiguous)
        if ambiguous:
            raise ValueError("A candidate link has conflicting manual labels")
        before_keys = {key(row) for row in before}
        after_keys = {key(row) for row in after}
        grades = ("Strong", "Medium", "Unlikely", "No Match")
        for grade in grades:
            matching = {link for link, labels in labels_by_key.items() if grade in labels}
            record = {
                "apartment": apartment,
                "manual_grade": grade,
                "label_source": "inferred from omission" if apartment == "concorde" and grade == "No Match" else "manual workbook",
                "reviewed_candidate_links": len(matching),
                "found_before_grey_filter": len(matching & before_keys),
                "found_on_first_sheet": len(matching & after_keys),
            }
            table.append(record)
            print(record)

    with (Path(__file__).parent / "manual_label_coverage.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=table[0].keys())
        writer.writeheader()
        writer.writerows(table)


if __name__ == "__main__":
    main()
