# Rerun the actual resolver with exact reordered names at explicitly named, uniquely parsed flats.
# Inputs: local captured candidate pools from refine_scores, reviewed candidate workbooks, and the active matcher.
# AUTHOR: Chinmay and AI

from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import patch
import argparse
import pickle
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline_section"))
from run_pipeline import matcher, select_by_named_section
from screen import contained_full_name, exact_name, make_candidates


def expand_named_full_name(captured, config, *, containment=False):
    """Return updated evidence and the newly eligible voter/flat keys without mutating the pool."""
    voters, roster, _, evidence, _, _ = captured["args"]
    initial = captured["initial"]
    mapped = initial.loc[initial["apartment_unit"].ne("") & initial["apartment_status"].ne(matcher.UNASSIGNED_STATUS)]
    already_mapped = set(mapped["_row_id"])
    occupied_by_name = {
        (row.apartment_unit, matcher.connection_name_key(name))
        for row in mapped.itertuples(index=False)
        for name in str(row.apartment_connection or "").split("; ")
        if name and "voter_name_match" in row.voter_link_type.split(";")
    }
    people_by_flat = defaultdict(list)
    for (unit, status), people in matcher.roster_by_unit_group(roster).items():
        people_by_flat[unit].extend((status, person) for person in people)

    # Actual parsed-unit agreement is essential: an apartment label alone cannot identify a flat.
    target = matcher.compile_terms_re(config.address_names, allow_joined_words=False)
    candidates = voters.loc[
        voters["address_norm"].str.contains(target) & voters["parsed_unit"].notna()
        & ~voters["_row_id"].isin(already_mapped)
    ]
    proposals = defaultdict(list)
    for _, voter in candidates.iterrows():
        unit = voter["parsed_unit"]
        name = exact_name(voter["name"])
        if not name:
            continue
        relation = exact_name(voter["relation_name"])
        options = []
        for status, person in people_by_flat[unit]:
            roster_key = exact_name(person["name"])
            if not roster_key or relation == roster_key or (
                containment and contained_full_name(voter["relation_name"], person["name"])
            ):
                continue
            matches = name == roster_key or (
                containment and contained_full_name(voter["name"], person["name"])
            )
            if matches:
                options.append((status, person))
        if len(options) != 1:
            continue
        status, person = options[0]
        roster_link = (unit, matcher.connection_name_key(person["name"]))
        if roster_link not in occupied_by_name:
            proposals[roster_link].append((voter, status, person))

    updated = evidence.copy()
    additions = set()
    for (unit, _), options in proposals.items():
        # More than one voter for the same roster person is ambiguous regardless of source order.
        if len(options) != 1:
            continue
        voter, status, person = options[0]
        with_name = {
            "voter_row_id": int(voter["_row_id"]), "serial_number": int(voter["serial_number"]),
            "voter_name": voter["name"], "roster_row_id": person["roster_row_id"],
            "roster_name": person["name"], "roster_name_norm": person["name_norm"],
            "match_source": "voter_name", "match_kind": "named_flat_full_words",
            "match_detail": "matching full words at a named building and parsed flat",
            "part_score": 1.0,
        }
        unit_key = (unit, status)
        row_id = int(voter["_row_id"])
        if unit_key not in updated or updated[unit_key] is evidence.get(unit_key):
            updated[unit_key] = updated.get(unit_key, {}).copy()
        if row_id in updated[unit_key]:
            record = updated[unit_key][row_id]
            updated[unit_key][row_id] = {
                **record, "person_hits": record["person_hits"].copy(), "scopes": record["scopes"].copy(),
            }
        matcher.add_evidence(updated[unit_key], voter, [with_name], [], "exact_unit")
        additions.add((row_id, unit))
    return updated, additions


def run(config, captured, containment):
    original = matcher.resolve_voter_links
    evidence, additions = expand_named_full_name(captured, config, containment=containment)

    def resolve(voters, roster, config, old_evidence, groups, discarded, original_links, excluded_links):
        return original(
            voters, roster, config, evidence, groups, discarded,
            original_links=original_links | additions, excluded_links=excluded_links - additions,
        )

    before, _, _ = select_by_named_section(captured, config, min_score=0, dominance=True, section2=True)
    with patch.object(matcher, "resolve_voter_links", resolve):
        after, _, _ = select_by_named_section(captured, config, min_score=0, dominance=True, section2=True)
    return additions, before, after


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apartments", nargs="*")
    args = parser.parse_args()
    benchmark = make_candidates()
    short = {"silicon_oasis": "silicon", "tirumala_vintage": "tirumala"}
    outcomes = []
    for file in sorted((HERE.parent / "refine_scores" / "generated").glob("*.pickle")):
        if args.apartments and file.stem not in args.apartments:
            continue
        with file.open("rb") as source:
            captured, _, _ = pickle.load(source)
        config = captured["args"][2]
        labels = {
            tuple(str(row[field] or "") for field in ("serial", "unit", "status")): row["manual"]
            for row in benchmark if row["apartment"] == short.get(config.key, config.key)
        }
        for containment in (False, True):
            proposals, before, after = run(config, captured, containment)
            gained = after - before
            lost = before - after
            print(config.key, "containment", containment, "proposals", len(proposals), "gained",
                  Counter(labels.get(key, "Unreviewed") for key in gained), "lost",
                  Counter(labels.get(key, "Unreviewed") for key in lost), flush=True)
            outcomes.extend([
                {"apartment": config.key, "containment": containment, "direction": direction,
                 "serial_number": key[0], "apartment_unit": key[1], "apartment_status": key[2],
                 "label": labels.get(key, "Unreviewed")}
                for direction, keys in (("gained", gained), ("lost", lost)) for key in sorted(keys)
            ])
        pd.DataFrame(outcomes).to_csv(HERE / "resolved_expansion.csv", index=False)
        del captured


if __name__ == "__main__":
    main()
