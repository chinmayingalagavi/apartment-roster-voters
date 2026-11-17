# Run the shortlisted apartment matching rules and write complete Excel outputs for the chosen rule.
# Inputs: fresh captures made from the configured AC voter list and original rosters, and local benchmark reviews.
# AUTHOR: Chinmay and AI

import argparse
from pathlib import Path
import pickle
import sys

import pandas as pd

from trial import HERE, feature_rows, identity, matcher, outcome, pair_links, resolve, reviewed_labels, write_workbook

sys.path.insert(0, str(HERE.parent / "refine_candidates"))
from resolve_expansion import expand_named_full_name


def selection(frame, named_count, paired, score_floor, clear_address):
    full_flat = frame["unique_unit"]
    exact_name = frame["direct"] & frame["multiword"] & frame["score"].eq(100)
    explicit = frame["explicit"]
    score = frame[["score", "linked_score"]].min(axis=1)
    strong = explicit | (named_count.ge(2) & full_flat & score.ge(75)) | paired
    supported_section = named_count.ge(1) & (full_flat | score.ge(score_floor))
    keep = explicit | supported_section | paired | (full_flat & exact_name & clear_address)
    return keep, strong


def score95_routes(frame, clear_address, multiple_voter_tokens):
    """Explore extra ways for a preliminary candidate to qualify at a 95% name score."""
    high_score = frame[["score", "linked_score"]].min(axis=1).ge(95)
    # This route keeps both original guards on the isolated 100% own-name fallback.
    yield "95_clear_flat", high_score & frame["direct"] & frame["multiword"] & frame["unique_unit"] & clear_address
    # This route relaxes the flat parser, but still excludes leftover address text.
    yield "95_clear_text", high_score & clear_address
    named = frame[frame["explicit"] & frame["unique_unit"]].groupby("section_raw")["apartment_unit"].agg(set).to_dict()
    same_section = pd.Series([
        bool(str(section).strip() and named.get(section, set()) - {flat})
        for section, flat in zip(frame["section_raw"], frame["apartment_unit"])
    ], index=frame.index, dtype=bool)
    yield "95_named_section", high_score & same_section
    # For ambiguous units, require the voter's own name with more than a single token.
    own_name = frame["direct"] & multiple_voter_tokens
    yield "95_named_section_guarded", high_score & same_section & (frame["unique_unit"] | own_name)
    yield "95_name_only", high_score


def run(score_floors, expand, write, allow_address_text, compare_95=False):
    labels = reviewed_labels()
    snapshots = HERE.parent / "refine_scores" / "generated"
    generated = HERE / "generated"
    generated.mkdir(exist_ok=True)
    configs, _, _ = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    results = []
    changes = []
    for apartment in configs:
        print(f"Running {apartment}", flush=True)
        with (snapshots / f"{apartment}.pickle").open("rb") as handle:
            captured, baseline, list_name = pickle.load(handle)
        voters, _, config, evidence, _, _ = captured["args"]
        frame = pd.DataFrame(feature_rows(captured, baseline, labels))
        first = captured["initial"].copy()
        booths = matcher.matched_units_at_booth(first)
        first["other_hh_matched_booth"] = matcher.other_households_matched_at_booth(first, booths)
        discarded = matcher.dominated_voter_links(first)
        pair_keys = pair_links(first, evidence, voters.set_index("_row_id"), complete=True)
        keys = list(zip(frame["_row_id"], frame["apartment_unit"]))
        paired = pd.Series([key in pair_keys for key in keys], index=frame.index)
        named_flats = frame[frame["unique_unit"] & frame["explicit"]].groupby(["part", "section_raw"])["apartment_unit"].agg(set).to_dict()
        named_count = pd.Series([
            len(named_flats.get((part, section), set()) - {flat}) if str(section).strip() else 0
            for part, section, flat in zip(frame["part"], frame["section_raw"], frame["apartment_unit"])
        ], index=frame.index, dtype=int)
        residual = frame["_row_id"].map(voters.set_index("_row_id")["unexplained_address_text"])
        clear_address = ~frame["long_unexplained_address"] if allow_address_text else residual.fillna("").str.strip().eq("")
        frame["named_flats_in_section"] = named_count
        expansion = expand_named_full_name(captured, config, containment=True) if expand else None
        variants = [(floor, "", False) for floor in score_floors]
        if compare_95:
            voter_names = frame["_row_id"].map(voters.set_index("_row_id")["name"])
            multiple_voter_tokens = voter_names.map(lambda name: len(matcher.matcher.tokenize_name(name)) >= 2)
            variants.extend((floor, f"_{route}", extra) for floor in score_floors
                            for route, extra in score95_routes(frame, clear_address, multiple_voter_tokens))
        for floor, route, extra in variants:
            name = f"named_section_{floor}{'_expanded' if expand else ''}{'_allow_text' if allow_address_text else ''}{route}"
            keep, strong = selection(frame, named_count, paired, floor, clear_address)
            resolved, assigned, unmapped = resolve(captured, frame, keep | extra, strong, discarded, booths, expansion=expansion)
            mapped = resolved.loc[assigned].to_dict("records")
            result = outcome(apartment, name, mapped, baseline, labels)
            results.append(result)
            seen = {identity(row) for row in mapped}
            lookup = {identity(row): row for row in first.to_dict("records")}
            lookup.update({identity(row): row for row in mapped})
            for direction, keys in (("gained", seen - baseline), ("lost", baseline - seen), ("retained", seen & baseline)):
                for key in keys:
                    label = labels.get((apartment, *key), "Unreviewed")
                    row = lookup[key]
                    changes.append(dict(apartment=apartment, variant=name, change=direction, reviewer=label,
                                        serial=key[0], unit=key[1], status=key[2], name=row["voter_name"],
                                        address=row["house_number"], part=row["part"], section=row["section_raw"],
                                        roster_connection=row["apartment_connection"], grade=row.get("_match_confidence", ""),
                                        link_type=row["voter_link_type"]))
            print(result, flush=True)
            if write:
                write_workbook(captured, resolved, assigned, unmapped,
                               generated / name / f"{apartment}_voters.xlsx", list_name)
        suffix = f"{'_expanded' if expand else ''}{'_allow_text' if allow_address_text else ''}{'_score95' if compare_95 else ''}"
        pd.DataFrame(results).to_csv(generated / f"finalists{suffix}.csv", index=False)
        pd.DataFrame(changes).to_csv(generated / f"finalist_changes{suffix}.csv", index=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--score-floor", nargs="+", type=int, default=[80])
    parser.add_argument("--expand", action="store_true", help="Search the roll for exact full words at a named apartment and flat.")
    parser.add_argument("--write", action="store_true", help="Write the three-sheet workbooks for each selected rule.")
    parser.add_argument("--allow-address-text", action="store_true", help="Allow short extra text in the isolated exact-name fallback.")
    parser.add_argument("--compare-95", action="store_true", help="Compare 95%% fallback routes against the selected trial.")
    options = parser.parse_args()
    run(options.score_floor, options.expand, options.write, options.allow_address_text, options.compare_95)


if __name__ == "__main__":
    main()
