# Test a lower review threshold in complete runs against reviewed Bangalore South candidate links.
# Inputs: the configured local voter list and apartment rosters, plus independent review workbooks.
# AUTHOR: Chinmay and AI

from pathlib import Path
from unittest.mock import patch
import csv
import sys

from openpyxl import load_workbook

FINAL = Path(__file__).resolve().parents[2]
WORKSPACE = FINAL.parent
sys.path.insert(0, str(FINAL / "code"))
import build_apartment_matches as matcher

DESTINATION = Path(__file__).resolve().parent
SOURCES = {
    "concorde": "concorde",
    "purnima": "purnima",
    "silicon_oasis": "silicon",
    "tirumala_vintage": "tirumala",
}


def rows(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    values = iter(workbook["voters_mapped_tohouse"].values)
    headers = next(values)
    result = [dict(zip(headers, item)) for item in values]
    workbook.close()
    return [row for row in result if row.get("serial_number") and row.get("apartment_unit")]


def row_key(row):
    return (str(row["serial_number"]), str(row["apartment_unit"]), str(row.get("apartment_status") or ""))


def reviewed_candidates(key, label):
    first_pass = WORKSPACE / "agents" / "research" / f"{label}-first-pass"
    source = rows(first_pass / f"{label}_before_scoring.xlsx")
    reviewed_path = WORKSPACE / "agents" / "drafts" / f"{label}_independent_full.xlsx"
    if not reviewed_path.exists():
        reviewed_path = first_pass / f"{label}_AI_review.xlsx"
    reviewed = rows(reviewed_path)
    source_keys = {row_key(row) for row in source}
    grade = {row_key(row): row["strength"] for row in reviewed}
    assert len(source_keys) == len(source), (key, "duplicate source keys")
    assert len(grade) == len(reviewed) and set(grade).issubset(source_keys), key
    if key == "concorde":
        assert len(source_keys - set(grade)) == 502
        for candidate in source_keys - set(grade):
            grade[candidate] = "No Match (inferred)"
    else:
        assert set(grade) == source_keys
    return grade


original_confidence = matcher.match_confidence
original_resolve = matcher.resolve_voter_links


def run(config, voter_file, searched_voter_list, variant):
    snapshots = []

    def record_resolve(*args, **kwargs):
        frame, unmatched = original_resolve(*args, **kwargs)
        stage = "cutoff re-resolution" if kwargs.get("excluded_links") else "dominance" if snapshots else "initial"
        links = {row_key(row) for row in frame.to_dict("records") if row.get("apartment_unit")}
        snapshots.append((stage, links))
        return frame, unmatched

    def lower_cutoff(frame, voters, apartment_config):
        result = original_confidence(frame, voters, apartment_config)
        eligible = frame["_linked_voter_name_match_pct"].gt(50)
        result.loc[result.eq(matcher.LOW_CONFIDENCE) & eligible] = "Needs review"
        return result

    out_file = DESTINATION / "generated" / variant / f"{config.key}_voters.xlsx"
    confidence_fn = lower_cutoff if variant == "cutoff_50" else original_confidence
    with patch.object(matcher, "resolve_voter_links", record_resolve), patch.object(matcher, "match_confidence", confidence_fn):
        matcher.run_one(config, voter_file, out_file, searched_voter_list=searched_voter_list)
    result = {row_key(row) for row in rows(out_file)}
    return result, snapshots


def main():
    configurations, voter_file, voter_name = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    summary = []
    evidence = []
    for apartment, label in SOURCES.items():
        print("Working on", apartment, flush=True)
        judgments = reviewed_candidates(apartment, label)
        before, snapshots = run(configurations[apartment], voter_file, voter_name, "baseline")
        after, _ = run(configurations[apartment], voter_file, voter_name, "cutoff_50")
        old_output = {row_key(row) for row in rows(FINAL / "output" / "ac-no-grey" / f"{apartment}_voters.xlsx")}
        print("Baseline matches saved output:", before == old_output, flush=True)
        gold = {key for key, value in judgments.items() if value in ("Strong", "Medium")}
        lower = set(judgments) - gold
        for name, cohort in (("reviewer_supported", gold), ("reviewer_lower_rated", lower), ("unreviewed", (before | after) - set(judgments))):
            result = {
                "apartment": apartment, "cohort": name, "reviewed_candidates": len(cohort),
                "baseline_visible": len(before & cohort), "cutoff_50_visible": len(after & cohort),
                "gained": len((after - before) & cohort), "lost": len((before - after) & cohort),
            }
            summary.append(result)
            print(result, flush=True)
        for candidate in gold - before:
            dominance = next((links for stage, links in snapshots if stage == "dominance"), None)
            if not snapshots or candidate not in snapshots[0][1]:
                stage = "not in initial resolved candidates"
            elif dominance is not None and candidate not in dominance:
                stage = "removed during dominance"
            elif candidate not in snapshots[-1][1]:
                stage = "removed during cutoff re-resolution"
            else:
                stage = "still resolved but not visible (grading/filter/status)"
            evidence.append({"apartment": apartment, "serial_number": candidate[0], "apartment_unit": candidate[1],
                             "status": candidate[2], "reviewer_grade": judgments[candidate], "stage": stage,
                             "recovered_by_cutoff_50": candidate in after})
    for name, data in (("summary.csv", summary), ("missing_supported_links.csv", evidence)):
        with (DESTINATION / name).open("w", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)


if __name__ == "__main__":
    main()
