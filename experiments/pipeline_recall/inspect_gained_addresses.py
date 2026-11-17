# Inspect parser-derived address flags on newly gained experimental voter-flat links.
# Inputs: the actual section5 difference file and the configured apartment roster files.
# AUTHOR: Chinmay and AI

from pathlib import Path
import csv

import pandas as pd

from test_cutoff import DESTINATION, SOURCES, matcher


def main():
    source_file = DESTINATION / "section5_changed_rows.csv"
    changed = list(csv.DictReader(source_file.open()))
    configurations, _, _ = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    result = []
    for apartment in SOURCES:
        gained = [row for row in changed if row["apartment"] == apartment and row["change"] == "gained"]
        if not gained:
            continue
        config = configurations[apartment]
        roster_rows = matcher.normalize_roster(config, matcher.read_roster_source(config))
        voters = pd.DataFrame(gained)
        voters["part"] = voters["part"].map(int)
        parsed = matcher.build_address_fields(voters, roster_rows, config)
        for _, row in parsed.iterrows():
            result.append({
                "apartment": apartment, "unit": row["unit"], "voter_name": row["voter_name"],
                "serial_number": row["serial_number"], "reviewer_grade": row["reviewer_grade"],
                "house_number": row["house_number"], "link_type": row["link_type"],
                "parsed_unit": row["parsed_unit"],
                "parsed_unit_matches": row["parsed_unit"] == row["unit"],
                "long_unexplained": row["has_long_unexplained_address"],
                "unexplained_text": row["unexplained_address_text"],
                "unexplained_letter_count": row["unexplained_address_letter_count"],
            })
    if result:
        with (DESTINATION / "section5_gained_address_flags.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(result[0]))
            writer.writeheader()
            writer.writerows(result)


if __name__ == "__main__":
    main()
