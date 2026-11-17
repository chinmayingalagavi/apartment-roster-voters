# Annotate cached preliminary voter-to-flat candidates with name, address, and support features.
# Inputs are local captures from capture.py and the historical independent review workbooks.
# AUTHOR: Chinmay and AI

from collections import defaultdict
import pickle

import pandas as pd

from capture import HERE, matcher
from compare_from_candidates import APARTMENTS, make_candidates
from run_pipeline import identity


def reviewed_labels():
    return {
        (APARTMENTS[row["apartment"]][0], *(str(row[field] or "") for field in ("serial", "unit", "status"))):
        row["manual"]
        for row in make_candidates()
    }


def link_key(row):
    return int(row["_row_id"]), row["apartment_unit"]


def feature_rows(captured, baseline, reviews):
    # Freeze section support in the complete first resolved candidate pool.
    voters, _, config, evidence, _, _ = captured["args"]
    corroborated = matcher.corroborated_roster_matches(evidence)
    targets = matcher.compile_terms_re(config.address_names, allow_joined_words=False)
    lookup = voters.set_index("_row_id")
    features = []
    for row in captured["initial"].to_dict("records"):
        unit = row["apartment_unit"]
        if not unit:
            continue
        row_id = int(row["_row_id"])
        source = lookup.loc[row_id]
        score = row["name_match_pct"]
        linked_score = row["_linked_voter_name_match_pct"]
        feature = {
            "apartment": config.key,
            "_row_id": row_id,
            "part": str(row["part"]),
            "section_raw": row["section_raw"] if pd.notna(row["section_raw"]) else "",
            "serial_number": row["serial_number"],
            "apartment_unit": unit,
            "apartment_status": row["apartment_status"],
            "explicit": bool(targets.search(source["address_norm"])),
            "parsed_unit": str(source["parsed_unit"]) if pd.notna(source["parsed_unit"]) else "",
            "long_unexplained_address": bool(source["has_long_unexplained_address"]),
            "score": int(score) if pd.notna(score) else 0,
            "linked_score": int(linked_score) if pd.notna(linked_score) else 0,
            "multiword": bool(row["_match_has_multiple_words"]),
            "direct": "voter_name_match" in row["voter_link_type"].split(";"),
            "corroborated": corroborated.get(row_id, (None,))[0] == unit,
            "baseline": identity(row) in baseline,
            "review": reviews.get((config.key, *identity(row)), "Unreviewed"),
        }
        feature["unique_unit"] = feature["parsed_unit"] == unit
        features.append(feature)

    all_flats, exact_flats, seeds, named = (defaultdict(set) for _ in range(4))
    for row in features:
        section = row["part"], row["section_raw"]
        if not str(section[1]).strip():
            continue
        unit = row["apartment_unit"]
        all_flats[section].add(unit)
        if row["unique_unit"]:
            exact_flats[section].add(unit)
        if row["explicit"]:
            named[section].add(unit)
        if row["explicit"] or (row["direct"] and row["unique_unit"] and row["multiword"] and row["score"] >= 90):
            seeds[section].add(unit)
    for row in features:
        section = row["part"], row["section_raw"]
        unit = row["apartment_unit"]
        for field, index in (
            ("section_other_flats", all_flats), ("section_other_exact_flats", exact_flats),
            ("section_other_seed_flats", seeds), ("section_other_named_flats", named),
        ):
            row[field] = len(index[section] - {unit})
    return features


def main():
    reviews = reviewed_labels()
    for snapshot in sorted((HERE / "generated").glob("*.pickle")):
        with snapshot.open("rb") as handle:
            captured, baseline, _ = pickle.load(handle)
        frame = pd.DataFrame(feature_rows(captured, baseline, reviews))
        destination = snapshot.with_suffix(".csv")
        frame.to_csv(destination, index=False)
        print(f"{snapshot.stem}: {len(frame)} candidate flat links")


if __name__ == "__main__":
    main()
