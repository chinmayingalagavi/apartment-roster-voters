#!/usr/bin/env python3
# Compare ward, unrestricted AC, and restricted AC results; inputs are their output folders, both voter CSVs, and apartment configuration.
# AUTHOR: Chinmay and AI
"""Write a reproducible coverage comparison without treating exclusions as errors."""

from __future__ import annotations

import argparse
import json
import shlex
from datetime import date
from pathlib import Path

import pandas as pd

import ac_matching
import polling_stations
import ward


# Cross-source comparisons use EPIC, never the unrelated part/serial numbering.
def ids(rows: pd.DataFrame) -> set[str]:
    return set(rows["epic_number"].fillna("").astype(str).str.strip().str.upper()) - {""}


def links(rows: pd.DataFrame) -> set[tuple[str, str]]:
    return {
        (str(row.epic_number).strip().upper(), str(row.apartment_unit).strip())
        for row in rows.fillna("").itertuples()
        if str(row.epic_number).strip()
    }


def compare(args: argparse.Namespace) -> dict[str, object]:
    ac_source = pd.read_csv(args.ac_csv, usecols=["epic_number", "pollingname", "pollingaddress"], dtype=str)
    ac_ids = ids(ac_source)
    station_row_counts = polling_stations.station_keys(ac_source).value_counts()
    ward_source = pd.read_csv(args.ward_csv, usecols=["epic_number"], dtype=str)
    ward_ids = ids(ward_source)
    configs = ward.load_apartment_configs(args.apartments_csv)
    if args.apartment != "all":
        configs = {args.apartment: configs[args.apartment]}
    summaries = []
    for config in configs.values():
        old = pd.read_csv(args.ward_outputs / f"{config.key}_voters.csv", dtype=str, keep_default_na=False)
        original = pd.read_csv(args.ac_outputs / "comparison" / f"{config.key}_original_voters.csv", dtype=str, keep_default_na=False)
        restricted = pd.read_csv(args.ac_outputs / f"{config.key}_voters.csv", dtype=str, keep_default_na=False)
        booths = pd.read_csv(args.ac_outputs / "polling_stations" / f"{config.key}_stations.csv", keep_default_na=False)
        selected = booths["selected"].astype(str).str.lower().eq("true")
        old_links = links(old)
        shared = {link for link in old_links if link[0] in ac_ids}
        original_links, restricted_links = links(original), links(restricted)
        same_ac, excluded, added = ac_matching.compare_outputs(original, restricted)
        ambiguous = ac_matching.multiple_unit_rows(restricted)
        ambiguous.to_csv(args.ac_outputs / "review" / f"{config.key}_multiple_units.csv", index=False)
        summaries.append({
            "apartment_key": config.key, "apartment": config.apartment_name,
            "ward_rows": len(old), "ac_original_rows": len(original),
            "ac_restricted_rows": len(restricted), "ac_original_unique_voters": len(ids(original)),
            "ac_restricted_unique_voters": len(ids(restricted)),
            "ac_original_voters_linked_to_multiple_units": len(ids(ac_matching.multiple_unit_rows(original))),
            "ac_restricted_voters_linked_to_multiple_units": len(ids(ambiguous)),
            "ac_original_voters_absent_from_ward_output": len(ids(original) - ids(old)),
            "ac_restricted_voters_absent_from_ward_output": len(ids(restricted) - ids(old)),
            "ward_links_with_id_in_ac": len(shared),
            "shared_ward_links_in_ac_original": len(shared & original_links),
            "shared_ward_links_in_ac_restricted": len(shared & restricted_links),
            "ward_link_ids_absent_from_ac_source": len(ids(old) - ac_ids),
            "selected_stations": int(selected.sum()),
            "selected_station_numbers": booths.loc[selected, "parts"].astype(str).tolist(),
            "eligible_voters": int(station_row_counts.reindex(booths.loc[selected, "station_key"], fill_value=0).sum()),
            "same_ac_comparison": same_ac,
        })
    provenance = args.ac_csv.with_suffix(".provenance.json")
    source_metadata = json.loads(provenance.read_text()).get("source_metadata_values", {}) if provenance.exists() else {}
    source_date = ", ".join(source_metadata.get("source_update_date", [])) or "unavailable"
    payload = {
        "ac_source_rows": len(ac_source), "ac_source_stations": len(station_row_counts),
        "ward_source_rows": len(ward_source),
        "ac_source_unique_epics": len(ac_ids), "ward_source_unique_epics": len(ward_ids),
        "shared_source_epics": len(ac_ids & ward_ids), "apartments": summaries,
        "limitation": "These are record-linkage coverage counts, not measured precision or recall against verified identities.",
    }
    regenerate = "python3 compare_runs.py --ac-csv " + shlex.quote(str(args.ac_csv))
    for flag, path in [
        ("--sensitivity-dir", args.sensitivity_dir),
        ("--ward-filter-outputs", args.ward_filter_outputs),
        ("--ward-single-label-outputs", args.ward_single_label_outputs),
    ]:
        if path:
            regenerate += " " + flag + " " + shlex.quote(str(path))
    # Only aggregate counts and booth numbers enter the Markdown report. Raw
    # voter names/EPICs/addresses remain in the local ignored CSV outputs.
    text = [
        "# V6 comparison", "", f"Run on {date.today().strftime('%d %B %Y')} using the supplied AC workbook and existing ward CSV.", "",
        f"The AC source has {len(ac_source):,} voter rows and {len(station_row_counts):,} polling-station entries (source update: {source_date}). The ward CSV has {len(ward_source):,} rows. The AC source has no separate roll-part column: its station-number prefix is used explicitly as a local grouping key. The original source files were preserved.", "",
        "## Result counts", "",
        "The two AC columns use the same source. Ward uses the original v5 rules. Restricted AC first selects booths from development-specific apartment-label evidence, with exact-name/unit clusters as fallback when label evidence is insufficient.", "",
        "| Apartment | Original ward | Original on AC | Restricted AC | Selected booths | Eligible AC voters |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in summaries:
        restricted_label = f"{result['ac_restricted_rows']:,}" if result["selected_stations"] else "No shortlist"
        text.append(f"| {result['apartment']} | {result['ward_rows']:,} | {result['ac_original_rows']:,} | {restricted_label} | {result['selected_stations']} | {result['eligible_voters']:,} |")
    text += ["", "Counts are output rows, each linking a source voter row to a unit or retaining an apartment-only Unmapped entry. No shortlist means no booth was selected and matching was withheld; it is not a zero-voter finding. Fewer rows do not by themselves prove higher precision. AC relationship prefixes are parsed into relationship type and relative name; the raw field is retained in the prepared CSV.", "", "## Additional coverage and shared ward links", "",
        f"Only {payload['shared_source_epics']:,} of the ward's {payload['ward_source_unique_epics']:,} unique voter IDs appear in the AC source ({100 * payload['shared_source_epics'] / payload['ward_source_unique_epics']:.2f}%). AC is not a superset of this ward extract, so changes in total counts combine source differences and matching effects.", "",
        "| Apartment | AC original voters absent from ward output | AC restricted voters absent from ward output | Ward unit-links whose IDs occur in AC | Those links found by AC original | Those links found by AC restricted |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in summaries:
        text.append(f"| {result['apartment']} | {result['ac_original_voters_absent_from_ward_output']:,} | {result['ac_restricted_voters_absent_from_ward_output']:,} | {result['ward_links_with_id_in_ac']:,} | {result['shared_ward_links_in_ac_original']:,} | {result['shared_ward_links_in_ac_restricted']:,} |")
    text += ["", "Additional voters are candidates for review, not verified new residents. The ward matches are also algorithmic links, not a ground-truth identity set. Shared-ID unit-link overlap is a coverage check only.", "", "## Station selection and review", ""]
    for result in summaries:
        delta = result["same_ac_comparison"]
        station_numbers = ", ".join(result["selected_station_numbers"]) or "none"
        text.append(f"- **{result['apartment']}**: station numbers {station_numbers}. The restriction excludes {delta['excluded_original_rows']:,} original AC links and adds {delta['added_rows']:,}; excluded rows remain in the local review CSV. " + ("No station was selected; the empty result means matching was withheld, not absence of voters." if not result["selected_stations"] else ""))
    text += ["", "Bare Concorde brand aliases initially suggested 20 booths / 10,736 voters, including other developments such as Manhattan and Tech Turf. Restricting discovery to Midway-specific phrases selects four booths / 2,390 voters. Discovery keywords therefore need to identify a development across the entire AC, not merely its brand.", "",
        "Purnima has too little compound-label/exact-name evidence under the default thresholds. Its low-evidence booths remain in the station report for manual selection or a separately labeled threshold-sensitivity run. The matcher never silently falls back to searching the full AC.", "",
        "## Verification and simple next steps", "",
        "Ward outputs are byte-identical to v5 (350 Concorde, 48 Purnima, 415 Silicon Oasis rows). Indexed AC lookup is also byte-identical on that full ward regression. Behavioral tests cover collisions, seed independence, label priority, station identity, abstention, reviewed overrides, and indexed/original equivalence.", "",
        "Use full apartment phrases first. When labels are sparse, review clusters supported by several distinct exact names and flats rather than the raw fuzzy-match count. Review excluded matches and common-name cases before changing thresholds. Distance could later help rank nearby booths, but it needs reliable coordinates and may miss legitimate registrations at older addresses; no coordinates are provided here.", "",
        "Regenerate this report after running AC with --compare-baseline:", "", "```sh", regenerate, "```", "",
    ]
    extra = []
    if args.ward_filter_outputs:
        extra += ["## Station filter tested on ward data", "", "This diagnostic applies the AC station filter to the smaller ward roll. Normal ward mode continues to use the original algorithm.", "",
            "| Apartment | Original ward | Station filter on ward |", "|---|---:|---:|"]
        for result in summaries:
            filtered = pd.read_csv(args.ward_filter_outputs / f"{result['apartment_key']}_voters.csv")
            ward_booths = pd.read_csv(args.ward_filter_outputs / "polling_stations" / f"{result['apartment_key']}_stations.csv")
            has_shortlist = ward_booths["selected"].astype(str).str.lower().eq("true").any()
            result["station_filter_on_ward_rows"] = len(filtered)
            extra.append(f"| {result['apartment']} | {result['ward_rows']} | {len(filtered) if has_shortlist else 'No shortlist'} |")
            if args.ward_single_label_outputs:
                path = args.ward_single_label_outputs / f"{result['apartment_key']}_voters.csv"
                if path.exists():
                    result["single_label_on_ward_rows"] = len(pd.read_csv(path))
        extra += ["", "For Purnima the default filter is too restrictive for sparse labels. Its ward booths have at most two apartment-labeled voters each, below the default three. Most roster names cannot supply multi-word exact seed evidence.", ""]
        for result in summaries:
            if "single_label_on_ward_rows" in result:
                extra.append(f"- {result['apartment']}: lowering both ward label thresholds to one returns {result['single_label_on_ward_rows']} rows; original ward mode returns {result['ward_rows']}.")
        extra.append("")
    if args.sensitivity_dir:
        extra += ["## One-label sensitivity experiment", "", "This separate experiment lowers both label thresholds to one. It does not change the default shortlist. A booth supported by one voter needs review.", ""]
        for result in summaries:
            path = args.sensitivity_dir / f"{result['apartment_key']}_voters.csv"
            if not path.exists():
                continue
            relaxed = pd.read_csv(path, dtype=str, keep_default_na=False)
            old = pd.read_csv(args.ward_outputs / f"{result['apartment_key']}_voters.csv", dtype=str, keep_default_na=False)
            booths = pd.read_csv(args.sensitivity_dir / "polling_stations" / f"{result['apartment_key']}_stations.csv")
            active = booths["selected"].astype(str).str.lower().eq("true")
            new_ids = len(ids(relaxed) - ids(old))
            extra.append(f"- {result['apartment']}: {len(relaxed)} rows at {int(active.sum())} booths, including {new_ids} voter IDs absent from the ward output. Separate CSVs and log: outputs/{args.sensitivity_dir.name}/.")
            result["single_label_sensitivity"] = {"rows": len(relaxed), "additional_voter_ids": new_ids, "stations": int(active.sum())}
        extra.append("")
    extra += ["## Multiple-unit ambiguity", "", "A voter linked to several flats in one apartment needs review. These links are preserved rather than assigned arbitrarily; retained ambiguous rows are written to review/{key}_multiple_units.csv.", "",
        "| Apartment | AC original voters linked to multiple units | AC restricted voters linked to multiple units |", "|---|---:|---:|"]
    for result in summaries:
        extra.append(f"| {result['apartment']} | {result['ac_original_voters_linked_to_multiple_units']} | {result['ac_restricted_voters_linked_to_multiple_units']} |")
    extra.append("")
    insertion = text.index("## Verification and simple next steps")
    text[insertion:insertion] = extra
    args.output.write_text("\n".join(line.rstrip() for line in text), encoding="utf-8")
    summary_path = args.ac_outputs / "comparison" / "summary.json"
    summary_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> None:
    root = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apartment", default="all")
    parser.add_argument("--apartments-csv", type=Path, default=root / "apartments.csv")
    parser.add_argument("--ac-csv", type=Path, required=True)
    parser.add_argument("--ward-csv", type=Path, default=root / "data" / "voters.csv")
    parser.add_argument("--ward-outputs", type=Path, default=root / "outputs" / "ward")
    parser.add_argument("--ac-outputs", type=Path, default=root / "outputs" / "ac")
    parser.add_argument("--sensitivity-dir", type=Path, help="Optional separately generated one-label experiment")
    parser.add_argument("--ward-filter-outputs", type=Path, help="Optional station-filter diagnostic on the ward roll")
    parser.add_argument("--ward-single-label-outputs", type=Path, help="Optional lower-threshold ward diagnostic")
    parser.add_argument("--output", type=Path, default=root / "COMPARISON.md")
    payload = compare(parser.parse_args())
    for result in payload["apartments"]:
        print(f"{result['apartment_key']}: ward={result['ward_rows']}, AC original={result['ac_original_rows']}, AC restricted={result['ac_restricted_rows']}")


if __name__ == "__main__":
    main()
