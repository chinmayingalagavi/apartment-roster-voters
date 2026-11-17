# Build experimental section-supported workbooks from the AC list and original apartment rosters.
# AUTHOR: Chinmay and AI

from collections import Counter
from pathlib import Path
from unittest.mock import patch
import csv
import sys

import pandas as pd
from openpyxl import load_workbook

from compare_from_candidates import make_candidates, rows
from run_pipeline import identity, load_apartment, run_baseline, select_by_named_section

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = Path(__file__).resolve().parent / "final_workbooks"
sys.path.insert(0, str(ROOT / "code"))
import build_apartment_matches as matcher


def section_support(row, section_flats):
    section = row["section_raw"]
    if pd.isna(section) or not str(section).strip():
        return 0
    return len(section_flats.get((str(row["part"]), section), set()) - {row["apartment_unit"]})


def make_workbook(config, voter_file, list_name):
    roster_rows, roster, voters = load_apartment(config, voter_file)
    captured, baseline = run_baseline(config, roster_rows, roster, voters)
    expected = {identity(row) for row in rows(ROOT / "output/ac-no-grey" / f"{config.key}_voters.xlsx")}
    if baseline != expected:
        raise ValueError(f"Baseline changed for {config.key}")

    # Record the specific own-name voter used to attach each same-address member.
    household_anchors = {}
    original_household_link = matcher.same_address_word_link
    def record_household_link(voter, anchor_records):
        link = original_household_link(voter, anchor_records)
        if link:
            ids = {int(item["voter"]["_row_id"]) for item in anchor_records
                   if int(item["voter"]["serial_number"]) == link["anchor_serial"]}
            household_anchors.setdefault(int(voter["_row_id"]), set()).update(ids)
        return link
    with patch.object(matcher, "same_address_word_link", record_household_link):
        resolved, unmapped_rows, section_flats = select_by_named_section(
            captured, config, min_score=0, dominance=True, section2=True, return_details=True
        )
    # Use the original candidate pool for section support, with the candidate's own flat excluded.
    initial = captured["initial"]
    booths = matcher.matched_units_at_booth(initial)
    resolved["other_hh_matched_booth"] = matcher.other_households_matched_at_booth(resolved, booths)
    resolved["other_hh_matched_section_in_part"] = resolved.apply(section_support, args=(section_flats,), axis=1)
    target = matcher.compile_terms_re(config.address_names, allow_joined_words=False)
    explicit = resolved["house_number"].map(lambda value: bool(target.search(matcher.matcher.normalize_address(value))))
    resolved["_match_confidence"] = "Needs review"
    resolved.loc[resolved["other_hh_matched_section_in_part"].ge(2), "_match_confidence"] = "Probable"
    resolved.loc[explicit | resolved["other_hh_matched_section_in_part"].ge(5), "_match_confidence"] = "Strong"

    # The first-sheet grey filter follows the current workbook implementation.
    unassigned = resolved["apartment_status"].eq(matcher.UNASSIGNED_STATUS)
    mapped = resolved["apartment_unit"].ne("") & ~unassigned
    strong_units = set(resolved.loc[mapped & resolved["_match_confidence"].eq("Strong"), "apartment_unit"])
    suppressed = mapped & resolved["_match_confidence"].eq("Needs review") & resolved["apartment_unit"].isin(strong_units)
    mapped_rows = resolved.loc[mapped & ~suppressed].copy()

    # Check selected relations identify a directly matched voter at the selected flat.
    own = mapped_rows[mapped_rows["voter_link_type"].str.split(";").map(lambda kinds: "voter_name_match" in kinds)]
    orphan_relations = []
    orphan_households = []
    for row in mapped_rows.to_dict("records"):
        kinds = row["voter_link_type"].split(";")
        if "relation_name_match" not in kinds or "voter_name_match" in kinds:
            continue
        candidates = own[own["apartment_unit"].eq(row["apartment_unit"]) & own["_row_id"].ne(row["_row_id"])]
        valid = any(
            matcher.matcher.relation_identifies_voter(row["relation_name"], candidate["voter_name"])
            for candidate in candidates.to_dict("records")
        )
        if not valid:
            orphan_relations.append(identity(row))

    for row in mapped_rows.to_dict("records"):
        if "same_address_household_member" not in row["voter_link_type"]:
            continue
        same_unit_own_ids = set(own.loc[own["apartment_unit"].eq(row["apartment_unit"]), "_row_id"])
        if not same_unit_own_ids.intersection(household_anchors.get(int(row["_row_id"]), set())):
            orphan_households.append(identity(row))

    # Build the other sheets using the same household and unmatched-roster helpers as production.
    connected = {(str(unit), matcher.connection_name_key(name))
                 for unit, names in zip(resolved["apartment_unit"], resolved["_connection_names"])
                 for name in names}
    source_rows = matcher.read_roster_source(config)
    not_matched = matcher.roster_rows_not_matched(source_rows, roster_rows, connected)
    unmapped = matcher.summarize_unmapped_households(
        unmapped_rows, voters, resolved.loc[resolved["apartment_unit"].ne(""), "_row_id"], config
    )
    mapped_rows = mapped_rows.sort_values(["apartment_unit", "apartment_status", "part", "serial_number"])
    output = DESTINATION / f"{config.key}_voters.xlsx"
    display_columns = [*matcher.MAPPED_OUTPUT_COLUMNS, "other_hh_matched_section_in_part"]
    with patch.object(matcher, "MAPPED_OUTPUT_COLUMNS", display_columns):
        matcher.write_output_workbook(output, mapped_rows, not_matched, unmapped, resolved.loc[unassigned],
                                      searched_voter_list=list_name)

    # Re-open the final sheet to check the actual visible set and its grade and count fields.
    book = load_workbook(output, read_only=True, data_only=True)
    values = iter(book[matcher.VOTERS_SHEET].values)
    header = next(values)
    final = [dict(zip(header, row)) for row in values]
    book.close()
    final_links = {identity(row) for row in final}
    assert final_links == {identity(row) for row in mapped_rows.to_dict("records")}
    assert not suppressed.any(), f"Grey suppression changed the selected set for {config.key}"
    return baseline, final_links, Counter(str(row["strength"]).split(" - ")[0] for row in final), orphan_relations, orphan_households


def main():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    configs, voter_file, list_name = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    reviewed = make_candidates()
    summary = []
    for key, config in configs.items():
        print("Starting", key, flush=True)
        baseline, final, grades, orphans, orphan_households = make_workbook(config, voter_file, list_name)
        manual_name = {"silicon_oasis": "silicon", "tirumala_vintage": "tirumala"}.get(key, key)
        manual = {tuple(str(row[field] or "") for field in ("serial", "unit", "status")): row["manual"]
                  for row in reviewed if row["apartment"] == manual_name}
        labels = Counter(manual.get(link, "Unreviewed") for link in final)
        gained = Counter(manual.get(link, "Unreviewed") for link in final - baseline)
        lost = Counter(manual.get(link, "Unreviewed") for link in baseline - final)
        result = {"apartment": key, "output_links": len(final), "strong": grades["Strong"],
                  "medium": grades["Medium"], "needs_review": grades["Needs review"],
                  "manual_strong": labels["Strong"], "manual_medium": labels["Medium"],
                  "manual_unlikely": labels["Unlikely"], "manual_no_match": labels["No Match"],
                  "unreviewed": labels["Unreviewed"],
                  "gained_supported": gained["Strong"] + gained["Medium"],
                  "gained_lower": gained["Unlikely"] + gained["No Match"],
                  "lost_supported": lost["Strong"] + lost["Medium"],
                  "lost_lower": lost["Unlikely"] + lost["No Match"],
                  "no_visible_relation_anchor": len(orphans),
                  "no_visible_household_anchor": len(orphan_households)}
        summary.append(result)
        with (DESTINATION / "summary.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(result))
            writer.writeheader()
            writer.writerows(summary)
        print(result, flush=True)


if __name__ == "__main__":
    main()
