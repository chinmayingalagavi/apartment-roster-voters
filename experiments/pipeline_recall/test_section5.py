# Run a section-supported recovery rule against the configured voter and apartment files.
# Compare output with fresh baseline workbooks and independent review candidate labels.
# AUTHOR: Chinmay and AI

from collections import defaultdict
from pathlib import Path
from unittest.mock import patch
import csv
import sys

import pandas as pd

from test_cutoff import DESTINATION, SOURCES, matcher, reviewed_candidates, row_key, rows


original_booths = matcher.matched_units_at_booth
original_confidence = matcher.match_confidence


def run_with_section_exception(config, voter_file, list_name, *, guard=False):
    """Retain below-cutoff candidates with five other flats in their part and section."""
    section_units = defaultdict(set)

    def count_and_capture(candidates):
        # The matcher freezes booth counts here, before dominance and confidence pruning.
        for part, section, flat in candidates[["part", "section_raw", "apartment_unit"]].itertuples(index=False):
            if flat and pd.notna(section) and str(section).strip():
                section_units[str(part), str(section)].add(flat)
        return original_booths(candidates)

    def classify(frame, voters, apartment_config):
        result = original_confidence(frame, voters, apartment_config)
        # Only grant the exception to candidates that already passed identity/household checks.
        supported = pd.Series([
            bool(flat) and len(section_units.get((str(part), str(section)), set()) - {flat}) >= 5
            for part, section, flat in frame[["part", "section_raw", "apartment_unit"]].itertuples(index=False)
        ], index=frame.index)
        if guard:
            # Require the address parser to identify this flat unambiguously.
            # Existing matches are unchanged; the guard applies only to the new exception.
            source = voters.set_index("_row_id")
            parsed_units = frame["_row_id"].map(source["parsed_unit"])
            supported &= parsed_units.eq(frame["apartment_unit"])
        result.loc[result.eq(matcher.LOW_CONFIDENCE) & supported] = "Probable"
        return result

    name = "section5_guard" if guard else "section5"
    target = DESTINATION / "generated" / name / f"{config.key}_voters.xlsx"
    with patch.object(matcher, "matched_units_at_booth", count_and_capture), patch.object(matcher, "match_confidence", classify):
        matcher.run_one(config, voter_file, target, searched_voter_list=list_name)
    return {row_key(row) for row in rows(target)}


def main():
    guard = "--guard" in sys.argv[1:]
    selected = [arg for arg in sys.argv[1:] if arg != "--guard"]
    if any(apartment not in SOURCES for apartment in selected):
        raise SystemExit(f"Unknown apartment. Choose from: {', '.join(SOURCES)}")
    configurations, voter_file, list_name = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    filename = "section5_guard_summary.csv" if guard else "section5_summary.csv"
    summary_path = DESTINATION / filename
    if selected and summary_path.exists():
        with summary_path.open(newline="") as handle:
            summary = [row for row in csv.DictReader(handle) if row["apartment"] not in selected]
    else:
        summary = []
    for apartment, label in SOURCES.items():
        if selected and apartment not in selected:
            continue
        print("Working on", apartment, flush=True)
        baseline_file = DESTINATION / "generated" / "baseline" / f"{apartment}_voters.xlsx"
        if baseline_file.exists():
            before = {row_key(row) for row in rows(baseline_file)}
        else:
            # The saved baseline has already been reproduced for Concorde using current code.
            before = {row_key(row) for row in rows(matcher.PROJECT_ROOT / "output" / "ac-no-grey" / f"{apartment}_voters.xlsx")}
        judgments = reviewed_candidates(apartment, label)
        after = run_with_section_exception(configurations[apartment], voter_file, list_name, guard=guard)
        supported = {key for key, value in judgments.items() if value in ("Strong", "Medium")}
        lower = set(judgments) - supported
        for name, cohort in (("reviewer_supported", supported), ("reviewer_lower_rated", lower),
                             ("unreviewed", (before | after) - set(judgments))):
            item = {"apartment": apartment, "cohort": name, "baseline": len(before & cohort),
                    "section5_raw": len(after & cohort), "raw_gained": len((after - before) & cohort),
                    "raw_lost": len((before - after) & cohort),
                    "union_total": len((before | after) & cohort)}
            summary.append(item)
            print(item, flush=True)
        # Preserve progress if an individual apartment run is interrupted.
        with summary_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
            writer.writeheader()
            writer.writerows(summary)


if __name__ == "__main__":
    main()
