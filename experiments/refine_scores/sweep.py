# Compare simple candidate-selection rules on fresh matches and rerun the resolver for finalists.
# Inputs are the private snapshots from capture.py and the independent review labels.
# AUTHOR: Chinmay and AI

from collections import Counter
from dataclasses import dataclass
from itertools import product
import argparse
import pickle

import pandas as pd

from capture import HERE, matcher
from features import feature_rows, link_key, reviewed_labels
from run_pipeline import identity


SUPPORTED = {"Strong", "Medium"}
LOWER_RATED = {"Unlikely", "No Match"}


@dataclass(frozen=True)
class Rule:
    support: str
    strong_section: int
    minimum_section: int
    minimum_score: int
    require_unit: bool
    allow_exact_name: bool
    allow_corroborated: bool

    def mask(self, rows):
        accepted = rows["explicit"] | rows[self.support].ge(self.strong_section)
        low_section = rows[self.support].ge(self.minimum_section) & rows["qualification_score"].ge(self.minimum_score)
        if self.require_unit:
            low_section &= rows["unique_unit"]
        if self.allow_exact_name:
            accepted |= rows["direct"] & rows["unique_unit"] & rows["multiword"] & rows["score"].eq(100)
        if self.allow_corroborated:
            accepted |= rows["corroborated"]
        return (accepted | low_section).to_numpy()

    def description(self):
        return (f"{self.support.removeprefix('section_other_')}:"
                f"{self.strong_section}/{self.minimum_section}+{self.minimum_score}"
                f"{'/unit' if self.require_unit else ''}"
                f"{'/exactname' if self.allow_exact_name else ''}"
                f"{'/pair' if self.allow_corroborated else ''}")


def rules():
    # A sentinel of 1000 disables the route that accepts any score at high support.
    for support, strong, medium, score, unit, exact, pair in product(
        ("section_other_flats", "section_other_exact_flats", "section_other_seed_flats", "section_other_named_flats"),
        (5, 10, 1000), (1, 2, 3, 5), (0, 60, 70, 75, 80, 85, 90, 95, 100),
        (False, True), (False, True), (False, True),
    ):
        if medium >= strong:
            continue
        yield Rule(support, strong, medium, score, unit, exact, pair)


def score_set(rows, accepts):
    counts = Counter()
    for row in rows:
        if row["apartment_status"] == "Unassigned":
            continue
        group = "supported" if row["review"] in SUPPORTED else "lower" if row["review"] in LOWER_RATED else "unreviewed"
        if accepts(row):
            counts[group] += 1
            if not row["baseline"]:
                counts[f"gained_{group}"] += 1
        elif row["baseline"]:
            counts[f"lost_{group}"] += 1
    return counts


def resolve(captured, data, rule):
    voters, roster_rows, config, evidence, address_groups, _ = captured["args"]
    first = captured["initial"].copy()
    first["other_hh_matched_booth"] = matcher.other_households_matched_at_booth(
        first, matcher.matched_units_at_booth(first)
    )
    chosen = {link_key(row) for row, accepted in zip(data, rule.mask(scoring_frame(data))) if accepted}
    exclusions = {link_key(row) for row in data} - chosen
    discarded = matcher.dominated_voter_links(first)
    # The resolver only reads this frame for explicitly named apartments. Direct
    # evidence and same-address groups are passed separately and retain all rows.
    named_voters = voters[voters["has_target_label"]]
    resolved, unmapped = matcher.resolve_voter_links(
        named_voters, roster_rows, config, evidence, address_groups, discarded,
        original_links=chosen, excluded_links=exclusions,
    )
    return resolved, unmapped


def scoring_frame(data):
    features = pd.DataFrame(data)
    features["qualification_score"] = features[["score", "linked_score"]].min(axis=1)
    return features


def output_counts(resolved, baseline, apartment, reviews):
    visible = {identity(row) for row in resolved.to_dict("records") if row["apartment_unit"]
               and row["apartment_status"] != matcher.UNASSIGNED_STATUS}
    matched = [{"review": reviews.get((apartment, *link), "Unreviewed"),
                "apartment_status": link[2], "baseline": link in baseline, "accepted": link in visible}
               for link in visible | baseline]
    return score_set(matched, lambda row: row["accepted"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve", action="append", metavar="RULE", default=[])
    args = parser.parse_args()
    snapshots = sorted((HERE / "generated").glob("*.pickle"))
    if not snapshots:
        parser.error("No candidate captures found. Run capture.py first.")
    reviews = reviewed_labels()
    frame = []
    selected = {rule.description(): rule for rule in rules() if rule.description() in args.resolve}
    if args.resolve:
        assert len(selected) == len(args.resolve), "Unknown rule name"
    for snapshot in snapshots:
        with snapshot.open("rb") as handle:
            captured, baseline, _ = pickle.load(handle)
        data = feature_rows(captured, baseline, reviews)
        if not args.resolve:
            frame.extend(data)
            continue
        for name, rule in selected.items():
            resolved, _ = resolve(captured, data, rule)
            counts = output_counts(resolved, baseline, snapshot.stem, reviews)
            frame.append({"apartment": snapshot.stem, "rule": name, **counts})
            print(snapshot.stem, name, dict(counts), flush=True)
    if args.resolve:
        pd.DataFrame(frame).fillna(0).to_csv(HERE / "generated" / "resolved.csv", index=False)
        return
    # This initial screen is deliberately fast. It does not apply the resolver.
    features = scoring_frame(frame)
    features = features[features["apartment_status"].ne(matcher.UNASSIGNED_STATUS)]
    groups = {"supported": features["review"].isin(SUPPORTED).to_numpy(),
              "lower": features["review"].isin(LOWER_RATED).to_numpy(),
              "unreviewed": features["review"].eq("Unreviewed").to_numpy()}
    baseline = features["baseline"].to_numpy()
    rows = []
    for rule in rules():
        selected = rule.mask(features)
        counts = {"rule": rule.description()}
        for group, mask in groups.items():
            counts[group] = (selected & mask).sum()
            counts[f"gained_{group}"] = (selected & ~baseline & mask).sum()
            counts[f"lost_{group}"] = (~selected & baseline & mask).sum()
        rows.append(counts)
    ranking = pd.DataFrame(rows)
    ranking.sort_values(["supported", "lower"], ascending=[False, True]).to_csv(
        HERE / "generated" / "sweep.csv", index=False
    )
    print(ranking[ranking["supported"] >= 700].sort_values(["lower", "supported"], ascending=[True, False])
          .drop_duplicates(["supported", "lower"]).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
