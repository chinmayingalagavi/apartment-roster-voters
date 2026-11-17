# Rerun the current matcher and select candidates using named-apartment section support.
# Inputs are the configured constituency CSV, apartment rosters and reviewed candidate workbooks.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch
import csv
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
import build_apartment_matches as matcher
from compare_from_candidates import make_candidates, rows


def identity(row):
    return tuple(str(row[field] or "") for field in ("serial_number", "apartment_unit", "apartment_status"))


def load_apartment(config, voter_file):
    roster_source = matcher.read_roster_source(config)
    roster_rows = matcher.normalize_roster(config, roster_source)
    roster = matcher.roster_by_unit_group(roster_rows)
    voters = matcher.read_voter_source(voter_file)
    voters["_row_id"] = range(len(voters))
    voters = matcher.build_address_fields(voters, roster_rows, config)
    voters = matcher.matcher.assign_households(voters)
    return roster_rows, roster, voters


def run_baseline(config, roster_rows, roster, voters):
    original = matcher.resolve_voter_links
    captured = {}

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        if not captured:
            captured["args"] = args
            captured["initial"] = result[0].copy()
        return result

    # Capture the actual first resolved list while running the normal full matcher.
    with patch.object(matcher, "resolve_voter_links", capture):
        output, _, _ = matcher.build_apartment_voter_rows(voters, roster_rows, roster, config)
    mapped = output[output["apartment_unit"].ne("") & output["apartment_status"].ne(matcher.UNASSIGNED_STATUS)]
    strong_units = set(mapped.loc[mapped["_match_confidence"].eq("Strong"), "apartment_unit"])
    shown = mapped[~(mapped["_match_confidence"].eq("Needs review") & mapped["apartment_unit"].isin(strong_units))]
    return captured, {identity(row) for row in shown.to_dict("records")}


def select_by_named_section(captured, config, *, min_score, dominance, section2=False, return_details=False):
    voters, roster_rows, _, evidence, address_groups, _ = captured["args"]
    first = captured["initial"].copy()
    first["other_hh_matched_booth"] = matcher.other_households_matched_at_booth(
        first, matcher.matched_units_at_booth(first)
    )
    named_flats = defaultdict(set)
    section_flats = defaultdict(set)
    target = matcher.compile_terms_re(config.address_names, allow_joined_words=False)
    for part, section, flat, address in first[["part", "section_raw", "apartment_unit", "house_number"]].itertuples(index=False):
        if flat and pd.notna(section) and str(section).strip():
            section_flats[(str(part), section)].add(flat)
            if target.search(matcher.matcher.normalize_address(address)):
                named_flats[(str(part), section)].add(flat)

    # Retain exact addresses or a score-supported match at a different explicitly named flat's section.
    chosen = set()
    for row in first.to_dict("records"):
        unit = row["apartment_unit"]
        if not unit:
            continue
        is_named = bool(target.search(matcher.matcher.normalize_address(row["house_number"])))
        section = row["section_raw"]
        valid_section = pd.notna(section) and str(section).strip()
        neighbors = (named_flats[(str(row["part"]), section)] - {unit}) if valid_section else set()
        section_neighbors = (section_flats[(str(row["part"]), section)] - {unit}) if valid_section else set()
        if is_named or (section2 and len(section_neighbors) >= 2) or (not section2 and neighbors and (row["name_match_pct"] or 0) > min_score):
            chosen.add((int(row["_row_id"]), unit))

    all_links = {(int(row_id), unit) for row_id, unit in zip(first["_row_id"], first["apartment_unit"]) if unit}
    excluded = all_links - chosen
    discarded = matcher.dominated_voter_links(first) if dominance else {}
    resolved, unmapped_rows = matcher.resolve_voter_links(
        voters, roster_rows, config, evidence, address_groups, discarded,
        original_links=chosen, excluded_links=excluded,
    )
    if return_details:
        return resolved, unmapped_rows, section_flats
    mapped = resolved[resolved["apartment_unit"].ne("") & resolved["apartment_status"].ne(matcher.UNASSIGNED_STATUS)]
    return {identity(row) for row in mapped.to_dict("records")}, len(chosen), sum(map(len, named_flats.values()))


def main():
    config_rows, voter_file, _ = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    reviewed = make_candidates()
    source_keys = {name: set() for name in config_rows}
    for row in reviewed:
        name = {"silicon": "silicon_oasis", "tirumala": "tirumala_vintage"}.get(row["apartment"], row["apartment"])
        source_keys[name].add((str(row["serial"]), str(row["unit"]), str(row["status"] or "")))
    summary = []
    changes = []
    for key, config in config_rows.items():
        print("Starting", key, flush=True)
        roster_rows, roster, voters = load_apartment(config, voter_file)
        print("Loaded", key, flush=True)
        captured, baseline = run_baseline(config, roster_rows, roster, voters)
        saved_baseline = {identity(row) for row in rows(ROOT / "output/ac-no-grey" / f"{key}_voters.xlsx")}
        if baseline != saved_baseline:
            raise ValueError(f"Fresh baseline for {key} differs from the saved comparison workbook")
        print("Baseline", key, len(baseline), flush=True)
        variants = {"current": baseline}
        for kind, score in (("section2", 0), ("named1", 0), ("named1", 50)):
            for dominance in (True, False):
                label = f"{kind}_score{score}_dominance{int(dominance)}"
                variants[label], chosen, seeds = select_by_named_section(
                    captured, config, min_score=score, dominance=dominance, section2=kind == "section2"
                )
                print(key, label, "eligible", chosen, "seed flat occurrences", seeds, flush=True)

        manual_rows = [row for row in reviewed if row["apartment"] == key or
                       (key == "silicon_oasis" and row["apartment"] == "silicon") or
                       (key == "tirumala_vintage" and row["apartment"] == "tirumala")]
        for variant, links in variants.items():
            label_counts = Counter(row["manual"] for row in manual_rows if
                                   (str(row["serial"]), str(row["unit"]), str(row["status"] or "")) in links)
            record = {"apartment": key, "variant": variant, "output_links": len(links),
                      "manual_strong": label_counts["Strong"], "manual_medium": label_counts["Medium"],
                      "manual_unlikely": label_counts["Unlikely"], "manual_no_match": label_counts["No Match"],
                      "unreviewed_links": len(links - source_keys[key]),
                      "gained_vs_current": len(links - baseline), "lost_vs_current": len(baseline - links)}
            summary.append(record)
            print(record, flush=True)
            for change, keys in (("gained", links - baseline), ("lost", baseline - links)):
                for link in keys:
                    changes.append({"apartment": key, "variant": variant, "change": change,
                                    "serial": link[0], "unit": link[1], "status": link[2]})
        # Save results after every apartment, so later failures do not hide completed work.
        for filename, records in (("pipeline_summary.csv", summary), ("pipeline_changes.csv", changes)):
            if records:
                with Path(__file__).with_name(filename).open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(records[0]))
                    writer.writeheader()
                    writer.writerows(records)
        del captured, voters


if __name__ == "__main__":
    main()
