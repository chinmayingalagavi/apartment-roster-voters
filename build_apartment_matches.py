#!/usr/bin/env python3
# Build ward or polling-station-restricted AC matches from a voter CSV and standardized apartment roster CSVs.
# AUTHOR: Chinmay and AI
"""Run the original ward matcher or the v6 polling-station-restricted AC matcher."""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

import polling_stations as stations
import ward
from ac_matching import add_exact_match_evidence, compare_outputs, match_rows, multiple_unit_rows


# CLI and input handling stay separate from the unchanged ward matching rules.
PROJECT_ROOT = Path(__file__).resolve().parent


def read_voters(path: Path) -> pd.DataFrame:
    voters = pd.read_csv(path, low_memory=False)
    required = {"name" if c == "voter_name" else c for c in ward.VOTER_OUTPUT_COLUMNS}
    missing = sorted(required - set(voters.columns))
    if missing:
        raise ValueError(f"Voter CSV is missing columns: {', '.join(missing)}")
    voters["_row_id"] = range(len(voters))
    return voters


def configured_station_keywords(apartments_csv: Path, key: str) -> tuple[str, ...] | None:
    config = pd.read_csv(apartments_csv, dtype=str, keep_default_na=False)
    if "station_keywords" not in config:
        return None
    value = config.loc[config["key"] == key, "station_keywords"].iloc[0]
    return ward.split_config_terms(value) or None


def read_station_override(path: Path | None, config_keys: set[str]) -> pd.DataFrame | None:
    if path is None:
        return None
    overrides = pd.read_csv(path, dtype=str, keep_default_na=False)
    flag = "selected" if "selected" in overrides else "suggested"
    required = {"apartment_key", "station_key", flag}
    if not required.issubset(overrides.columns):
        raise ValueError("Station override needs apartment_key, station_key, and selected (or suggested)")
    if not set(overrides["apartment_key"]).issubset(config_keys):
        raise ValueError("Station override contains an unknown apartment_key")
    truth = {"true", "yes", "1"}
    false = {"false", "no", "0", ""}
    flags = overrides[flag].str.strip().str.lower()
    if not flags.isin(truth | false).all():
        raise ValueError("Station selection values must be true/false, yes/no, or 1/0")
    if overrides.duplicated(["apartment_key", "station_key"]).any():
        raise ValueError("Station override contains duplicate apartment/station entries")
    overrides = overrides.copy()
    overrides["_selected"] = flags.isin(truth)
    return overrides


def save_csv(rows: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows.to_csv(path, index=False)


def station_selection(
    voters: pd.DataFrame, roster: pd.DataFrame, config: ward.ApartmentConfig,
    args: argparse.Namespace, overrides: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.Series]:
    suggestions = stations.suggest_polling_stations(
        voters, config, min_voters=args.min_label_voters,
        min_addresses=args.min_label_addresses,
        station_keywords=configured_station_keywords(args.apartments_csv, config.key),
    )
    # Exact full names plus address-compatible units provide independent, stricter
    # seeds. They never use relation names, mononyms, fuzzy matches, or propagation.
    suggestions = add_exact_match_evidence(
        voters, roster, config, suggestions, min_units=args.min_match_units,
    )
    label_ok = suggestions["label_suggested"].astype(bool)
    match_ok = suggestions["match_suggested"].astype(bool)
    if args.station_evidence == "labels-first":
        suggestions["suggested"] = label_ok if label_ok.any() else match_ok
    elif args.station_evidence == "labels":
        suggestions["suggested"] = label_ok
    elif args.station_evidence == "matches":
        suggestions["suggested"] = match_ok
    else:
        suggestions["suggested"] = label_ok | match_ok
    suggestions["selection_source"] = "automatic"
    suggestions["selected"] = suggestions["suggested"]
    suggestions.insert(0, "apartment_key", config.key)
    if overrides is not None:
        rows = overrides[overrides["apartment_key"] == config.key]
        if rows.empty:
            raise ValueError(f"Station override has no entries for {config.key}")
        keys = set(rows.loc[rows["_selected"], "station_key"])
        unknown = keys - set(suggestions["station_key"])
        if unknown or "" in keys:
            raise ValueError(f"Unknown or empty selected station keys for {config.key}: {sorted(unknown)}")
        suggestions["selected"] = suggestions["station_key"].isin(keys)
        suggestions["selection_source"] = "override"
    # A missing-station bucket is reported for review, but never selected.
    suggestions.loc[suggestions["station_key"].eq(""), ["suggested", "selected"]] = False
    suggestions = suggestions.sort_values(
        ["selected", "label_voters", "exact_match_units", "station_key"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
    selected = set(suggestions.loc[suggestions["selected"], "station_key"])
    return suggestions, stations.station_keys(voters).isin(selected)


# Each run has a scope-specific output directory, so ward and AC results coexist.
def run(args: argparse.Namespace) -> Path:
    configs = ward.load_apartment_configs(args.apartments_csv)
    all_config_keys = set(configs)
    if args.apartment != "all":
        if args.apartment not in configs:
            raise ValueError(f"Unknown apartment key: {args.apartment}")
        configs = {args.apartment: configs[args.apartment]}
    if args.output_csv and args.apartment == "all":
        raise ValueError("--output-csv requires one apartment")
    if args.output_csv and args.output_dir:
        raise ValueError("--output-csv and --output-dir cannot be used together")
    output_root = args.output_dir or (args.output_csv.parent if args.output_csv else PROJECT_ROOT / "outputs" / args.mode)
    if args.suggest_only and args.mode != "ac":
        raise ValueError("--suggest-only requires --mode ac")
    if args.mode == "ward" and (args.stations_csv or args.compare_baseline):
        raise ValueError("Station overrides and --compare-baseline require --mode ac")
    voters = read_voters(args.voter_csv)
    overrides = read_station_override(args.stations_csv, all_config_keys)
    summaries: list[dict[str, object]] = []
    started = time.perf_counter()
    for config in configs.values():
        apartment_started = time.perf_counter()
        roster = ward.load_roster(config)
        eligible = voters
        summary: dict[str, object] = {"apartment_key": config.key, "input_voters": len(voters)}
        if args.mode == "ac":
            suggestions, mask = station_selection(voters, roster, config, args, overrides)
            save_csv(suggestions, output_root / "polling_stations" / f"{config.key}_stations.csv")
            eligible = voters.loc[mask].copy()
            weak_labels = stations.strong_apartment_label_mask(
                voters["house_number"], config,
                station_keywords=configured_station_keywords(args.apartments_csv, config.key),
            ) & ~mask
            review = voters.loc[weak_labels].drop(columns=["_row_id"]).copy()
            review["review_reason"] = "apartment_label_outside_selected_stations"
            save_csv(review, output_root / "review" / f"{config.key}_labels_outside_stations.csv")
            summary.update({
                "selected_stations": suggestions.loc[suggestions["selected"], "station_key"].tolist(),
                "stations_with_metadata": int(suggestions["station_key"].ne("").sum()),
                "missing_station_voters": int(stations.station_keys(voters).eq("").sum()),
                "eligible_voters": len(eligible),
                "excluded_from_search": len(voters) - len(eligible),
                "labeled_rows_outside_stations": len(review),
                "selection_status": "selected" if mask.any() else "no_supported_stations",
            })
            print(f"{config.key}: {int(suggestions['selected'].sum())} stations; {len(eligible)}/{len(voters)} voters eligible", flush=True)
            if not mask.any():
                print("  No supported polling stations: AC matcher abstains. Review the station report or supply --stations-csv.", flush=True)
        if args.suggest_only:
            summaries.append(summary)
            continue
        output = match_rows(eligible, roster, config, indexed_candidates=args.mode == "ac")
        destination = args.output_csv or output_root / f"{config.key}_voters.csv"
        save_csv(output, destination)
        if args.mode == "ac":
            ambiguous = multiple_unit_rows(output)
            save_csv(ambiguous, output_root / "review" / f"{config.key}_multiple_units.csv")
            summary["voters_linked_to_multiple_units"] = int(ambiguous["epic_number"].nunique())
        summary.update(ward.apartment_run_summary(config, roster, output, destination))
        summary["matching_elapsed_seconds"] = round(time.perf_counter() - apartment_started, 3)
        if args.mode == "ac" and args.compare_baseline:
            # Both algorithms see the same source roll. This isolates the effect
            # of the restriction; it does not establish that excluded rows are wrong.
            baseline = match_rows(voters, roster, config, indexed_candidates=True)
            save_csv(baseline, output_root / "comparison" / f"{config.key}_original_voters.csv")
            comparison, excluded, added = compare_outputs(baseline, output)
            summary["comparison"] = comparison
            save_csv(excluded, output_root / "comparison" / f"{config.key}_excluded_voters.csv")
            save_csv(added, output_root / "comparison" / f"{config.key}_added_voters.csv")
            print(f"  original={len(baseline)}, restricted={len(output)}, excluded={len(excluded)}, added={len(added)}", flush=True)
        summaries.append(summary)
        print(f"{config.key}: {len(output)} output rows -> {destination}", flush=True)
    generated = datetime.now().astimezone()
    payload = {
        "version": 6, "mode": args.mode, "generated_at": generated.isoformat(timespec="seconds"),
        "voter_csv": str(args.voter_csv.resolve()), "apartments_csv": str(args.apartments_csv.resolve()),
        "station_parameters": {
            "evidence": args.station_evidence, "min_label_voters": args.min_label_voters,
            "min_label_addresses": args.min_label_addresses, "min_match_units": args.min_match_units,
            "override_csv": str(args.stations_csv) if args.stations_csv else None,
        } if args.mode == "ac" else None,
        "suggest_only": args.suggest_only,
        "elapsed_seconds": round(time.perf_counter() - started, 3), "apartments": summaries,
        "interpretation": "Counts measure coverage and selection; precision requires reviewed ground truth.",
    }
    log_path = output_root / "log" / f"run_{generated.strftime('%Y%m%d_%H%M%S_%f')}.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"run_log: {log_path}", flush=True)
    return log_path


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apartment", nargs="?", default="all")
    parser.add_argument("--mode", choices=["ward", "ac"], default="ward")
    parser.add_argument("--apartments-csv", type=Path, default=PROJECT_ROOT / "apartments.csv")
    parser.add_argument("--voter-csv", type=Path)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--station-evidence", choices=["labels-first", "labels", "matches", "either"], default="labels-first")
    parser.add_argument("--min-label-voters", type=positive_int, default=3)
    parser.add_argument("--min-label-addresses", type=positive_int, default=2)
    parser.add_argument("--min-match-units", type=positive_int, default=3)
    parser.add_argument("--stations-csv", type=Path, help="Reviewed station report with selected=true/false per apartment")
    parser.add_argument("--suggest-only", action="store_true")
    parser.add_argument("--compare-baseline", action="store_true", help="Also run original algorithm on this same CSV")
    args = parser.parse_args()
    if args.mode == "ac" and args.voter_csv is None:
        parser.error("--mode ac requires --voter-csv pointing to the AC roll")
    args.voter_csv = args.voter_csv or PROJECT_ROOT / "data" / "voters.csv"
    try:
        run(args)
    except (ValueError, OSError, pd.errors.ParserError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    main()
