# Add conservative station evidence and compare original/restricted matches; inputs are voter, roster, and station DataFrames.
# AUTHOR: Chinmay and AI
"""AC-specific seed evidence and shared adapters around the original matcher."""

from __future__ import annotations

import pandas as pd

import matching
import polling_stations as stations
import ward


# Full-name seeds retain initials and require at least two full words. A one-word
# roster name is too common to justify widening the geographic search area.
def exact_name_key(value: object) -> str:
    if pd.isna(value):
        return ""
    tokens = matching.tokenize_name(value)
    if len(matching.full_word_tokens(tokens)) < 2:
        return ""
    return " ".join(sorted(token.text for token in tokens))


def add_exact_match_evidence(
    voters: pd.DataFrame, roster: pd.DataFrame, config: ward.ApartmentConfig,
    suggestions: pd.DataFrame, *, min_units: int = 3,
) -> pd.DataFrame:
    by_name: dict[str, set[str]] = {}
    for _, row in roster.iterrows():
        key = exact_name_key(row["name"])
        if key:
            by_name.setdefault(key, set()).add(str(row["unit"]))
    by_name = {key: units for key, units in by_name.items() if len(units) == 1}
    # Normalize each distinct name once, not once per copy in a large source roll.
    names = voters["name"].fillna("").astype(str)
    normalized = {name: exact_name_key(name) for name in names.unique()}
    keys = names.map(normalized)
    # Only exact-name candidates incur the more expensive address parser. No
    # original matcher is run across the entire AC to discover seed stations.
    candidates = voters.loc[keys.isin(by_name)].copy()
    candidates["_exact_name_key"] = keys.loc[candidates.index]
    seed_rows: list[dict[str, str]] = []
    if not candidates.empty:
        candidates = ward.build_address_fields(candidates, roster, config)
        candidates["_station_key"] = stations.station_keys(candidates)
        candidates["_person_key"] = stations.person_keys(candidates)
        for _, row in candidates.iterrows():
            possible = by_name[row["_exact_name_key"]] & set(row["identity_candidate_units"])
            if len(possible) != 1 or row["has_long_unexplained_address"] or not row["_station_key"]:
                continue
            seed_rows.append({
                "station_key": str(row["_station_key"]),
                "unit": next(iter(possible)), "person": row["_person_key"],
                "name_key": row["_exact_name_key"],
            })
    seeds = pd.DataFrame(seed_rows, columns=["station_key", "unit", "person", "name_key"])
    out = suggestions.copy()
    if seeds.empty:
        out["exact_match_voters"] = 0
        out["exact_match_units"] = 0
        out["exact_match_names"] = 0
    else:
        # An EPIC repeated in several rows cannot vote for several units when
        # deciding whether a station has broad independent support.
        conflicts = seeds.groupby("person")[["station_key", "unit"]].nunique().gt(1).any(axis=1)
        seeds = seeds.loc[~seeds["person"].isin(conflicts.index[conflicts])].drop_duplicates("person")
        grouped = seeds.groupby("station_key").agg(
            exact_match_voters=("person", "nunique"), exact_match_units=("unit", "nunique"),
            exact_match_names=("name_key", "nunique"),
        )
        out = out.merge(grouped, on="station_key", how="left")
        for column in ["exact_match_voters", "exact_match_units", "exact_match_names"]:
            out[column] = out[column].fillna(0).astype(int)
    out["label_suggested"] = out["suggested"].astype(bool)
    out["match_suggested"] = (
        out["station_key"].ne("") & out["exact_match_units"].ge(min_units)
        & out["exact_match_voters"].ge(min_units) & out["exact_match_names"].ge(min_units)
    )
    out["reason"] = [
        "; ".join(reason for reason, supported in [
            ("apartment_label", bool(label)), ("exact_name_and_unit_cluster", bool(exact)),
        ] if supported) or "insufficient_evidence"
        for label, exact in zip(out["label_suggested"], out["match_suggested"])
    ]
    return out


# The ward algorithm is reused verbatim after filtering, including its output
# schema and name/status rules. Original source row IDs survive the restriction.
def match_rows(
    voters: pd.DataFrame, roster: pd.DataFrame, config: ward.ApartmentConfig,
    *, indexed_candidates: bool = False,
) -> pd.DataFrame:
    if voters.empty:
        return pd.DataFrame(columns=ward.OUTPUT_COLUMNS)
    prepared = ward.build_address_fields(voters, roster, config)
    prepared = matching.assign_households(prepared)
    output = ward.build_apartment_voter_rows(
        prepared, roster, ward.roster_by_unit_group(roster), config,
        indexed_candidates=indexed_candidates,
    )
    return output.reindex(columns=ward.OUTPUT_COLUMNS)


def output_keys(rows: pd.DataFrame) -> pd.Series:
    # Part and serial identify a source voter row within one AC. EPIC is included
    # but never used alone: an input can contain repeated or missing EPIC values.
    columns = ["part", "serial_number", "epic_number", "apartment_unit"]
    return rows[columns].fillna("").astype(str).apply(tuple, axis=1)


def multiple_unit_rows(rows: pd.DataFrame) -> pd.DataFrame:
    """Expose voters linked to different units for review; preserve their links."""
    usable = rows[["epic_number", "apartment_unit"]].astype("string").fillna("")
    known = usable.loc[usable["epic_number"].ne("") & usable["apartment_unit"].ne("")]
    counts = known.groupby("epic_number")["apartment_unit"].nunique()
    return rows.loc[usable["epic_number"].isin(counts.index[counts.gt(1)])].copy()


def compare_outputs(original: pd.DataFrame, restricted: pd.DataFrame) -> tuple[dict[str, object], pd.DataFrame, pd.DataFrame]:
    original_keys, restricted_keys = output_keys(original), output_keys(restricted)
    excluded = original.loc[~original_keys.isin(set(restricted_keys))].copy()
    added = restricted.loc[~restricted_keys.isin(set(original_keys))].copy()
    return {
        "original_rows": len(original), "restricted_rows": len(restricted),
        "retained_original_rows": len(original) - len(excluded),
        "excluded_original_rows": len(excluded), "added_rows": len(added),
        "original_units": ward.household_count(original), "restricted_units": ward.household_count(restricted),
        "retained_original_pct": round(100 * (len(original) - len(excluded)) / len(original), 2) if len(original) else None,
        "excluded_by_station": excluded.groupby(["pollingname", "pollingaddress"], dropna=False).size().reset_index(name="rows").to_dict("records"),
        "excluded_by_link_type": {str(key): int(value) for key, value in excluded["voter_link_type"].value_counts().items()},
    }, excluded, added
