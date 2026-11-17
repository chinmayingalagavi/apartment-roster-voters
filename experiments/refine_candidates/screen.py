# Screen for new voter-to-flat candidates in the configured voter roll and apartment rosters.
# Inputs: active configuration, baseline and section experiment workbooks, historical reviewer labels.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(HERE.parent / "pipeline_section"))
import build_apartment_matches as builder
from compare_from_candidates import APARTMENTS, identity, make_candidates, rows


def exact_name(name):
    """Require two full words, retaining any initials and ignoring word order."""
    tokens = builder.matcher.tokenize_name(name)
    if len({token.text for token in builder.matcher.full_word_tokens(tokens)}) < 2:
        return ()
    return tuple(sorted(token.text for token in tokens))


def roster_keys(roster):
    index = defaultdict(set)
    for row in roster.itertuples(index=False):
        key = exact_name(row.name)
        if key:
            index[key].add((row.unit, row.group_label, row.name))
    return index


def contained_full_name(voter_name, roster_name):
    """Exactly match every full word on either side, requiring at least two there."""
    voter_words = builder.matcher.name_word_set(voter_name)
    roster_words = builder.matcher.name_word_set(roster_name)
    return min(len(voter_words), len(roster_words)) >= 2 and (
        voter_words <= roster_words or roster_words <= voter_words
    )


def matched_anchors(selected):
    anchors = defaultdict(list)
    reverse_anchors = defaultdict(list)
    for row in selected:
        if "voter_name_match" not in str(row["voter_link_type"] or ""):
            continue
        if not str(row["strength"]).startswith("Strong") or (row["name_match_pct"] or 0) < 90:
            continue
        key = exact_name(row["voter_name"])
        if key:
            anchors[key].append(row)
        reverse_key = exact_name(row["relation_name"])
        if reverse_key:
            reverse_anchors[reverse_key].append(row)
    return anchors, reverse_anchors


def proposals(config, voters, selected):
    roster = builder.normalize_roster(config, builder.read_roster_source(config))
    names = roster_keys(roster)
    roster_by_flat = defaultdict(list)
    for row in roster.itertuples(index=False):
        roster_by_flat[row.unit].append((row.group_label, row.name))
    anchors, reverse_anchors = matched_anchors(selected)
    named = builder.compile_terms_re(config.address_names, allow_joined_words=False)

    # Use a raw-roll subset for parsing. The address parser is per voter and does not need the whole roll.
    potential = voters.loc[
        voters["address_norm"].str.contains(named)
        | voters["relation_key"].isin(list(anchors))
        | (voters["name_key"].isin(list(reverse_anchors)) & voters["name_key"].isin(list(names)))
    ].copy()
    parsed = builder.build_address_fields(potential, roster, config)
    parsed["named"] = parsed["address_norm"].str.contains(named)
    for row in parsed.itertuples(index=False):
        serial = str(row.serial_number)
        candidates = names.get(row.name_key, set())
        if row.named and len(candidates) == 1:
            unit, status, roster_name = next(iter(candidates))
            # An address without digits provides building evidence but cannot contradict a flat number.
            if not any(char.isdigit() for char in row.address_norm):
                yield ("named_address_no_number", row, unit, status, roster_name, "")
            elif not row.address_candidate_units:
                yield ("named_address_unparsed_number", row, unit, status, roster_name, "")
            elif unit in row.address_candidate_units:
                yield ("named_address_agreeing_number", row, unit, status, roster_name, "")

        if not row.parsed_unit:
            continue
        if row.named:
            matching_names = [
                (status, name) for status, name in roster_by_flat[row.parsed_unit]
                if contained_full_name(row.name, name)
                and not contained_full_name(row.relation_name, name)
            ]
            if len(set(matching_names)) == 1:
                status, name = matching_names[0]
                yield ("named_unique_flat_contained_name", row, row.parsed_unit, status, name, "")

        # A dependent must identify the selected own-name voter and have the same complete flat.
        possible = [
            anchor for anchor in anchors.get(row.relation_key, ())
            if anchor["apartment_unit"] == row.parsed_unit and str(anchor["serial_number"]) != serial
        ]
        if len(possible) == 1:
            anchor = possible[0]
            scope = "cross_part_exact_relation" if str(anchor["part"]) != str(row.part) else "same_part_exact_relation"
            yield (
                scope, row, row.parsed_unit, anchor["apartment_status"],
                anchor["apartment_connection"], str(anchor["serial_number"]),
            )

        # A reverse relationship supplies supporting evidence only for an exact own-name link.
        if len(candidates) == 1:
            unit, status, roster_name = next(iter(candidates))
            possible = [
                anchor for anchor in reverse_anchors.get(row.name_key, ())
                if anchor["apartment_unit"] == unit == row.parsed_unit and str(anchor["serial_number"]) != serial
            ]
            if len(possible) == 1:
                anchor = possible[0]
                scope = ("cross_part_reverse_relation" if str(anchor["part"]) != str(row.part) else "same_part_reverse_relation")
                yield (scope, row, unit, status, roster_name, str(anchor["serial_number"]))


def run(config, voters, reviewed):
    current = rows(ROOT / "output/ac-no-grey" / f"{config.key}_voters.xlsx")
    selected = rows(HERE.parent / "pipeline_section/final_workbooks" / f"{config.key}_voters.xlsx")
    baseline = {identity(row) for row in current}
    incumbent = defaultdict(set)
    for row in current + selected:
        incumbent[str(row["serial_number"])].add(row["apartment_unit"])
    selected_units = {(str(row["serial_number"]), row["apartment_unit"]) for row in selected}
    for scope, row, unit, status, roster_name, anchor_serial in proposals(config, voters, selected):
        key = (str(row.serial_number), unit, status)
        if (key[0], unit) in selected_units:
            continue
        yield {
            "apartment": config.key, "rule": scope, "serial": key[0], "unit": unit,
            "status": status, "review": reviewed.get(key, "Unreviewed"),
            "current": key in baseline, "other_flat": bool(incumbent.get(key[0], set()) - {unit}),
            "part": row.part, "section": row.section_raw, "address": row.house_number,
            "name": row.name, "relation": row.relation_name, "roster_connection": roster_name,
            "anchor_serial": anchor_serial,
        }


def main():
    configs, voter_file, _ = builder._load_apartment_run_config(builder.DEFAULT_APARTMENTS_CSV)
    voters = builder.read_voter_source(voter_file)
    voters["_row_id"] = range(len(voters))
    voters["address_norm"] = voters["house_number"].map(builder.matcher.normalize_address)
    voters["name_key"] = voters["name"].map(exact_name)
    voters["relation_key"] = voters["relation_name"].map(exact_name)
    benchmark = make_candidates()
    output = []
    for short, (apartment, _) in APARTMENTS.items():
        reviewed = {
            tuple(str(row[field] or "") for field in ("serial", "unit", "status")): row["manual"]
            for row in benchmark if row["apartment"] == short
        }
        screened = list(run(configs[apartment], voters, reviewed))
        output.extend(screened)
        pd.DataFrame(output).to_csv(HERE / "screened.csv", index=False)
        print(apartment, Counter((row["rule"], row["review"]) for row in screened), flush=True)


if __name__ == "__main__":
    main()
