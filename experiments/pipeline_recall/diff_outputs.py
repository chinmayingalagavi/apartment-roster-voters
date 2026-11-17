# List changed voter-flat rows in experimental workbooks compared with fresh baseline outputs.
# Inputs: temporary baseline and trial workbooks and independent reviewer candidate labels.
# AUTHOR: Chinmay and AI

import csv

from test_cutoff import DESTINATION, SOURCES, matcher, reviewed_candidates, row_key, rows


def main():
    for variant in ("cutoff_50", "section5", "section5_guard"):
        changes = []
        for apartment, label in SOURCES.items():
            baseline = DESTINATION / "generated" / "baseline" / f"{apartment}_voters.xlsx"
            trial = DESTINATION / "generated" / variant / f"{apartment}_voters.xlsx"
            if not baseline.exists():
                baseline = matcher.PROJECT_ROOT / "output" / "ac-no-grey" / f"{apartment}_voters.xlsx"
            if not trial.exists():
                continue
            old_rows = rows(baseline)
            new_rows = rows(trial)
            old = {row_key(row): row for row in old_rows}
            new = {row_key(row): row for row in new_rows}
            assert len(old) == len(old_rows) and len(new) == len(new_rows), apartment
            judgments = reviewed_candidates(apartment, label)
            for key in sorted(set(old) | set(new)):
                original, changed = old.get(key), new.get(key)
                if original is not None and changed is not None and original["strength"] == changed["strength"]:
                    continue
                display = changed if changed is not None else original
                changes.append({
                    "apartment": apartment,
                    "change": "gained" if original is None else "lost" if changed is None else "grade_changed",
                    "reviewer_grade": judgments.get(key, "unreviewed"),
                    "unit": display["apartment_unit"],
                    "serial_number": display["serial_number"],
                    "epic_number": display["epic_number"],
                    "voter_name": display["voter_name"],
                    "house_number": display["house_number"],
                    "section_raw": display["section_raw"],
                    "part": display["part"],
                    "old_strength": original["strength"] if original else "",
                    "new_strength": changed["strength"] if changed else "",
                    "connection": display["apartment_connection"],
                    "name_match_pct": display["name_match_pct"],
                    "link_type": display["voter_link_type"],
                })
        if changes:
            with (DESTINATION / f"{variant}_changed_rows.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(changes[0]))
                writer.writeheader()
                writer.writerows(changes)
        print(variant, len(changes), "changed rows")


if __name__ == "__main__":
    main()
