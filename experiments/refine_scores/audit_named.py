# Audit the retained lower-rated links in the named-section and family trial.
# Inputs are private first-pass captures and the historical independent review workbooks.
# AUTHOR: Chinmay and AI

from collections import Counter
import pickle
import sys
from unittest.mock import patch

import pandas as pd

from capture import HERE, matcher
from features import feature_rows, link_key, reviewed_labels
from run_pipeline import identity

sys.path.insert(0, str(HERE.parent / "refine_seeds"))
from live_rule import pair_links, section_key, select


def test_guards(captured, baseline, labels, features):
    """Check guards with the resolver so dependent additions or losses are included."""
    voters, _, cfg, source_evidence, _, _ = captured["args"]
    source = voters.set_index("_row_id")
    paired = pair_links(captured["initial"], source_evidence, source, complete=True)
    seeds = {}
    for row in features.values():
        if row["explicit"] and row["unique_unit"] and row["section_raw"]:
            seeds.setdefault((row["part"], row["section_raw"]), set()).add(row["apartment_unit"])

    original_resolver = matcher.resolve_voter_links
    original_household = matcher.same_address_word_link

    def clear_relative(voter, anchors):
        clear = []
        for record in anchors:
            anchor = record["voter"]
            relation = matcher.matcher.normalized_name_words(voter["relation_name"])
            anchor_relation = matcher.matcher.normalized_name_words(anchor["relation_name"])
            if (
                matcher.matcher.relation_identifies_voter(voter["relation_name"], anchor["name"])
                or matcher.matcher.relation_identifies_voter(anchor["relation_name"], voter["name"])
                or (relation and relation == anchor_relation)
            ):
                clear.append(record)
        return original_household(voter, clear)

    def guard(*args, original_links, excluded_links, **kwargs):
        keep = set()
        for row_id, unit in original_links:
            key = row_id, unit
            row = features[key]
            if row["explicit"] or key in paired:
                keep.add(key)
                continue
            named_neighbors = seeds.get((row["part"], row["section_raw"]), set()) - {unit}
            if named_neighbors:
                if minimum_ambiguous and not row["unique_unit"] and min(row["score"], row["linked_score"]) < 80:
                    continue
            elif strict_residue and source.at[row_id, "unexplained_address_text"].strip():
                continue
            keep.add(key)
        removed = original_links - keep
        named_voters = voters[voters["has_target_label"]]
        if require_relative:
            with patch.object(matcher, "same_address_word_link", clear_relative):
                return original_resolver(named_voters, *args[1:], original_links=keep, excluded_links=excluded_links | removed, **kwargs)
        return original_resolver(named_voters, *args[1:], original_links=keep, excluded_links=excluded_links | removed, **kwargs)

    for strict_residue, minimum_ambiguous, require_relative in (
        (False, False, False), (True, False, False), (True, True, False), (True, True, True),
    ):
        with patch.object(matcher, "resolve_voter_links", guard):
            resolved, _, _ = select(captured, "family_and_exact")
        visible = {identity(row) for row in resolved.to_dict("records") if row["apartment_unit"]
                   and row["apartment_status"] != matcher.UNASSIGNED_STATUS}
        label_counts = Counter(labels.get((cfg.key, *key), "Unreviewed") for key in visible)
        print(cfg.key, strict_residue, minimum_ambiguous, require_relative, label_counts, flush=True)


def main():
    labels = reviewed_labels()
    results = []
    for snapshot in sorted((HERE / "generated").glob("*.pickle")):
        with snapshot.open("rb") as handle:
            captured, baseline, _ = pickle.load(handle)
        cfg = captured["args"][2]
        rows, _, evidence = select(captured, "family_and_exact")
        features = {link_key(row): row for row in feature_rows(captured, baseline, labels)}
        if "--guards" in sys.argv:
            test_guards(captured, baseline, labels, features)
            continue
        kept = []
        for row in rows.to_dict("records"):
            if not row["apartment_unit"] or row["apartment_status"] == matcher.UNASSIGNED_STATUS:
                continue
            key = link_key(row)
            label = labels.get((cfg.key, *identity(row)), "Unreviewed")
            keep = {
                **row,
                **features[key],
                "review": label,
                "route_named_section": bool(evidence["named_flats"].get(section_key(row), set()) - {row["apartment_unit"]}),
                "route_pair": key in evidence["paired"],
                "route_exact": key in evidence["exact"],
                "route_explicit": key in evidence["explicit"],
            }
            kept.append(keep)
        results += kept
        print(cfg.key, Counter(row["review"] for row in kept))
    if not results:
        return
    retained = pd.DataFrame(results)
    retained.to_csv(HERE / "generated" / "audit_named.csv", index=False)
    rejected = retained[retained["review"].isin(["No Match", "Unlikely"])]
    print(rejected.groupby(["apartment", "route_explicit", "route_named_section", "route_pair", "route_exact"]).size())


if __name__ == "__main__":
    main()
