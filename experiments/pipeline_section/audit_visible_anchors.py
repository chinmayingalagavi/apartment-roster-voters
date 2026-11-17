# Audit whether relation and household links have compatible own-name anchors visible in experimental workbooks.
# Inputs are experimental XLSX outputs and the configured apartment rosters.
# AUTHOR: Chinmay and AI

from pathlib import Path
import csv
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))
import build_apartment_matches as matcher


def audit(config, path):
    frame = pd.read_excel(path, sheet_name=matcher.VOTERS_SHEET).fillna("")
    frame["_row_id"] = range(len(frame))
    frame["name"] = frame["voter_name"]
    roster = matcher.normalize_roster(config, matcher.read_roster_source(config))
    frame = matcher.build_address_fields(frame, roster, config)
    own = frame[frame["voter_link_type"].str.split(";").map(lambda kinds: "voter_name_match" in kinds)]
    missing = []
    for row in frame.to_dict("records"):
        kinds = row["voter_link_type"].split(";")
        anchors = own[own["apartment_unit"].eq(row["apartment_unit"]) & own["_row_id"].ne(row["_row_id"])]
        if "relation_name_match" in kinds and "voter_name_match" not in kinds:
            if not any(matcher.matcher.relation_identifies_voter(row["relation_name"], a["voter_name"])
                       for a in anchors.to_dict("records")):
                missing.append((row, "relation"))
        if "same_address_household_member" in kinds:
            candidates = anchors[anchors["same_address_group_key"].eq(row["same_address_group_key"])]
            records = [{"voter": a, "person_hits": [], "relation_hits": [], "member_links": []}
                       for a in candidates.to_dict("records")]
            if not row["same_address_group_key"] or not matcher.same_address_word_link(pd.Series(row), records):
                missing.append((row, "household"))
    return missing


def main():
    configs, _, _ = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    dest = Path(__file__).resolve().parent / "final_workbooks"
    missing = []
    for key, config in configs.items():
        path = dest / f"{key}_voters.xlsx"
        if not path.exists():
            continue
        found = audit(config, path)
        print(key, "visible-anchor failures", len(found), flush=True)
        for row, kind in found:
            missing.append({"apartment": key, "unit": row["apartment_unit"], "part": row["part"],
                            "serial_number": row["serial_number"], "voter_name": row["voter_name"],
                            "connection_type": kind})
    with (dest / "visible_anchor_failures.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["apartment", "unit", "part", "serial_number", "voter_name", "connection_type"])
        writer.writeheader()
        writer.writerows(missing)


if __name__ == "__main__":
    main()
