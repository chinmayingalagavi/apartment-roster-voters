# Compare uniform section, name, and flat rules through the existing resolver and workbook writer.
# Inputs: local preliminary captures from refine_scores/capture.py and the reviewed candidate workbooks.
# AUTHOR: Chinmay and AI

import argparse
from collections import Counter
from pathlib import Path
import pickle
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "refine_scores"))
sys.path.insert(0, str(HERE.parent / "refine_seeds"))
from features import feature_rows, reviewed_labels
from live_rule import pair_links
from run_pipeline import identity, matcher, rows


def eligibility(frame, *, dense, sparse, exact_name, pair):
    """Keep rows with independent location evidence or additional identity evidence."""
    # Use the same name evidence from the linked voter for dependent rows.
    score = frame[["score", "linked_score"]].min(axis=1)
    full_flat = frame["unique_unit"]
    clear_address = ~frame["long_unexplained_address"]
    named = frame["explicit"]
    dense_section = dense & full_flat & (score.ge(70) | frame["section_other_named_flats"].ge(1))
    sparse_section = sparse & full_flat & clear_address & frame["multiword"] & score.ge(90)
    exact_match = exact_name & full_flat & clear_address & frame["multiword"] & score.eq(100)
    confirmed_pair = pair & frame["corroborated"]
    keep = named | dense_section | sparse_section | exact_match | confirmed_pair
    strong = named | dense_section | confirmed_pair
    return keep, strong


def policies(frame, paired):
    none = pd.Series(False, index=frame.index)
    counts = {
        "section5": frame["section_other_flats"].ge(5),
        "verified5": frame["section_other_exact_flats"].ge(5),
        "seed2": frame["section_other_seed_flats"].ge(2),
        "named1": frame["section_other_named_flats"].ge(1),
    }
    for density, support in counts.items():
        for sparse, exact, pair in ((False, False, False), (True, False, True), (False, True, True)):
            sparse_support = frame["section_other_flats"].ge(2) if sparse else none
            tag = "core" if not sparse and not exact else "sparse" if sparse else "exact"
            yield f"{density}_{tag}", *eligibility(frame, dense=support, sparse=sparse_support, exact_name=exact, pair=pair)
    # Compare alternatives that trade location strength for more flexible name evidence.
    named = frame["explicit"]
    dense = frame["section_other_exact_flats"].ge(5) & frame["unique_unit"]
    seed = frame["section_other_named_flats"].ge(1)
    pair = frame["corroborated"]
    full_name = frame["multiword"] & frame["score"].eq(100) & frame["linked_score"].eq(100)
    clear = ~frame["long_unexplained_address"] & frame["unique_unit"]
    yield "dense_or_named", named | dense | seed, named | dense | (seed & frame["unique_unit"])
    yield "dense_or_named_pair", named | dense | seed | pair, named | dense | (seed & frame["unique_unit"]) | pair
    yield "dense_or_named_exact", named | dense | seed | pair | (full_name & clear), named | dense | (seed & frame["unique_unit"]) | pair

    # Build location around explicitly named addresses and allow independent identity evidence elsewhere.
    strong_location = named | (seed & frame["unique_unit"])
    for score_floor in (0, 70, 85, 95):
        score = frame[["score", "linked_score"]].min(axis=1)
        section = seed & (frame["unique_unit"] | score.ge(score_floor))
        for include_dense in (False, True):
            dense_route = dense if include_dense else none
            strong = strong_location | paired | dense_route
            yield f"named_family_exact_{score_floor}{'_dense' if include_dense else ''}", (
                named | section | paired | (full_name & clear) | dense_route
            ), strong


def resolve(captured, frame, keep, strong, discarded, booth_units, *, expansion=None):
    voters, roster, config, evidence, address_groups, _ = captured["args"]
    all_links = set(zip(frame["_row_id"], frame["apartment_unit"]))
    chosen = set(zip(frame.loc[keep, "_row_id"], frame.loc[keep, "apartment_unit"]))
    strong_links = set(zip(frame.loc[strong, "_row_id"], frame.loc[strong, "apartment_unit"]))
    if expansion is not None:
        evidence, additions = expansion
        chosen |= additions
        strong_links |= additions
    # The resolver uses the full source frame only to scan explicitly named addresses.
    # Its own-name and household evidence is passed separately and includes every voter.
    resolved, unmapped = matcher.resolve_voter_links(
        voters.loc[voters["has_target_label"]], roster, config, evidence, address_groups, discarded,
        original_links=chosen, excluded_links=all_links - chosen,
    )
    assigned = resolved["apartment_unit"].ne("") & resolved["apartment_status"].ne(matcher.UNASSIGNED_STATUS)
    resolved["_match_confidence"] = [
        "Strong" if key in strong_links or "explicit_apartment_address" in kind.split(";") else "Probable"
        for key, kind in zip(zip(resolved["_row_id"], resolved["apartment_unit"]), resolved["voter_link_type"])
    ]
    resolved.loc[~assigned, "_match_confidence"] = "Strong"
    resolved["other_hh_matched_booth"] = matcher.other_households_matched_at_booth(resolved, booth_units)
    section_counts = dict(zip(zip(frame["_row_id"], frame["apartment_unit"]), frame["section_other_flats"]))
    resolved["other_hh_matched_section_in_part"] = [section_counts.get(key, 0) for key in zip(resolved["_row_id"], resolved["apartment_unit"])]
    if "named_flats_in_section" in frame:
        named_counts = dict(zip(zip(frame["_row_id"], frame["apartment_unit"]), frame["named_flats_in_section"]))
        resolved["other_named_flats_in_section"] = [named_counts.get(key, 0) for key in zip(resolved["_row_id"], resolved["apartment_unit"])]
    return resolved, assigned, unmapped


def write_workbook(captured, resolved, assigned, unmapped, target, list_name):
    from unittest.mock import patch

    voters, roster, config, _, _, _ = captured["args"]
    source = matcher.read_roster_source(config)
    connected = {(unit, matcher.connection_name_key(name)) for unit, names in zip(
        resolved["apartment_unit"], resolved["_connection_names"]) for name in names}
    unmatched = matcher.roster_rows_not_matched(source, roster, connected)
    unmapped_voters = matcher.unmapped_voter_report(resolved, unmapped, voters, config)
    mapped = resolved.loc[assigned].sort_values(["apartment_unit", "apartment_status", "part", "serial_number"])
    unassigned = resolved[resolved["apartment_status"].eq(matcher.UNASSIGNED_STATUS)]
    target.parent.mkdir(parents=True, exist_ok=True)
    section_columns = [column for column in ("other_hh_matched_section_in_part", "other_named_flats_in_section")
                       if column in mapped]
    with patch.object(matcher, "MAPPED_OUTPUT_COLUMNS", [*matcher.MAPPED_OUTPUT_COLUMNS, *section_columns]):
        matcher.write_output_workbook(target, mapped, unmatched, unmapped_voters, unassigned, searched_voter_list=list_name)
    assert {identity(row) for row in rows(target)} == {identity(row) for row in mapped.to_dict("records")}


def outcome(apartment, variant, output, baseline, labels):
    keys = {identity(row) for row in output}
    categorized = Counter()

    def group(key):
        label = labels.get((apartment, *key))
        return "supported" if label in ("Strong", "Medium") else "lower" if label else "unreviewed"

    for row in output:
        cohort = group(identity(row))
        categorized[cohort] += 1
        if row["_match_confidence"] == "Strong":
            categorized[f"strong_{cohort}"] += 1
    categorized.update(f"gained_{group(key)}" for key in keys - baseline)
    categorized.update(f"lost_{group(key)}" for key in baseline - keys)
    fields = ("supported", "lower", "unreviewed", "strong_supported", "strong_lower",
              "gained_supported", "lost_supported", "gained_lower", "lost_lower")
    return {"apartment": apartment, "variant": variant, **{field: categorized[field] for field in fields}}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--apartment", nargs="+")
    cli.add_argument("--variant", nargs="+")
    cli.add_argument("--eligible-dominance", action="store_true", help="Compare only eligible candidates.")
    cli.add_argument("--write", action="store_true", help="Write selected trial workbooks.")
    options = cli.parse_args()
    labels = reviewed_labels()
    snapshots = HERE.parent / "refine_scores" / "generated"
    generated = HERE / "generated"
    generated.mkdir(exist_ok=True)
    for path in sorted(snapshots.glob("*.pickle")):
        if options.apartment and path.stem not in options.apartment:
            continue
        print(f"Evaluating {path.stem}", flush=True)
        with path.open("rb") as handle:
            captured, baseline, list_name = pickle.load(handle)
        frame = pd.DataFrame(feature_rows(captured, baseline, labels))
        first = captured["initial"].copy()
        booth_units = matcher.matched_units_at_booth(first)
        first["other_hh_matched_booth"] = matcher.other_households_matched_at_booth(first, booth_units)
        discarded = matcher.dominated_voter_links(first)
        voters, _, _, evidence, _, _ = captured["args"]
        paired_links = pair_links(first, evidence, voters.set_index("_row_id"), complete=True)
        paired = pd.Series([key in paired_links for key in zip(frame["_row_id"], frame["apartment_unit"])], index=frame.index)
        summary = []
        for name, keep, strong in policies(frame, paired):
            if options.variant and name not in options.variant:
                continue
            ranking = discarded
            if options.eligible_dominance:
                chosen = set(zip(frame.loc[keep, "_row_id"], frame.loc[keep, "apartment_unit"]))
                ranking = matcher.dominated_voter_links(first.loc[
                    [key in chosen for key in zip(first["_row_id"], first["apartment_unit"])]
                ])
                name += "_eligible"
            resolved, assigned, unmapped = resolve(captured, frame, keep, strong, ranking, booth_units)
            mapped = resolved.loc[assigned].to_dict("records")
            record = outcome(path.stem, name, mapped, baseline, labels)
            summary.append(record)
            print(record, flush=True)
            if options.write:
                target = generated / name / f"{path.stem}_voters.xlsx"
                write_workbook(captured, resolved, assigned, unmapped, target, list_name)
        suffix = "_eligible" if options.eligible_dominance else ""
        pd.DataFrame(summary).to_csv(generated / f"{path.stem}{suffix}_summary.csv", index=False)


if __name__ == "__main__":
    main()
