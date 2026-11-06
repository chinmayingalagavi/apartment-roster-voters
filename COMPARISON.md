# V6 comparison

Run on 05 November 2026 using the supplied AC workbook and existing ward CSV.

The AC source has 422,012 voter rows and 605 polling-station entries (source update: 24-08-2026). The ward CSV has 20,200 rows. The AC source has no separate roll-part column: its station-number prefix is used explicitly as a local grouping key. The original source files were preserved.

## Result counts

The two AC columns use the same source. Ward uses the original v5 rules. Restricted AC first selects booths from development-specific apartment-label evidence, with exact-name/unit clusters as fallback when label evidence is insufficient.

| Apartment | Original ward | Original on AC | Restricted AC | Selected booths | Eligible AC voters |
|---|---:|---:|---:|---:|---:|
| Concorde Midway | 350 | 1,227 | 222 | 4 | 2,390 |
| Purnima Classic | 48 | 396 | No shortlist | 0 | 0 |
| Silicon Oasis | 415 | 949 | 520 | 8 | 6,421 |

Counts are output rows, each linking a source voter row to a unit or retaining an apartment-only Unmapped entry. No shortlist means no booth was selected and matching was withheld; it is not a zero-voter finding. Fewer rows do not by themselves prove higher precision. AC relationship prefixes are parsed into relationship type and relative name; the raw field is retained in the prepared CSV.

## Additional coverage and shared ward links

Only 9,388 of the ward's 20,199 unique voter IDs appear in the AC source (46.48%). AC is not a superset of this ward extract, so changes in total counts combine source differences and matching effects.

| Apartment | AC original voters absent from ward output | AC restricted voters absent from ward output | Ward unit-links whose IDs occur in AC | Those links found by AC original | Those links found by AC restricted |
|---|---:|---:|---:|---:|---:|
| Concorde Midway | 1,000 | 11 | 219 | 217 | 210 |
| Purnima Classic | 371 | 0 | 26 | 25 | 0 |
| Silicon Oasis | 610 | 185 | 339 | 339 | 335 |

Additional voters are candidates for review, not verified new residents. The ward matches are also algorithmic links, not a ground-truth identity set. Shared-ID unit-link overlap is a coverage check only.

## Station selection and review

- **Concorde Midway**: station numbers 335, 336, 334, 337. The restriction excludes 1,005 original AC links and adds 0; excluded rows remain in the local review CSV.
- **Purnima Classic**: station numbers none. The restriction excludes 396 original AC links and adds 0; excluded rows remain in the local review CSV. No station was selected; the empty result means matching was withheld, not absence of voters.
- **Silicon Oasis**: station numbers 345, 346, 344, 357, 356, 353, 354, 351. The restriction excludes 429 original AC links and adds 0; excluded rows remain in the local review CSV.

Bare Concorde brand aliases initially suggested 20 booths / 10,736 voters, including other developments such as Manhattan and Tech Turf. Restricting discovery to Midway-specific phrases selects four booths / 2,390 voters. Discovery keywords therefore need to identify a development across the entire AC, not merely its brand.

Purnima has too little compound-label/exact-name evidence under the default thresholds. Its low-evidence booths remain in the station report for manual selection or a separately labeled threshold-sensitivity run. The matcher never silently falls back to searching the full AC.

## Station filter tested on ward data

This diagnostic applies the AC station filter to the smaller ward roll. Normal ward mode continues to use the original algorithm.

| Apartment | Original ward | Station filter on ward |
|---|---:|---:|
| Concorde Midway | 350 | 311 |
| Purnima Classic | 48 | No shortlist |
| Silicon Oasis | 415 | 400 |

For Purnima the default filter is too restrictive for sparse labels. Its ward booths have at most two apartment-labeled voters each, below the default three. Most roster names cannot supply multi-word exact seed evidence.

- Purnima Classic: lowering both ward label thresholds to one returns 22 rows; original ward mode returns 48.

## One-label sensitivity experiment

This separate experiment lowers both label thresholds to one. It does not change the default shortlist. A booth supported by one voter needs review.

- Purnima Classic: 7 rows at 2 booths, including 0 voter IDs absent from the ward output. Separate CSVs and log: outputs/ac_purnima_single_label/.

## Multiple-unit ambiguity

A voter linked to several flats in one apartment needs review. These links are preserved rather than assigned arbitrarily; retained ambiguous rows are written to review/{key}_multiple_units.csv.

| Apartment | AC original voters linked to multiple units | AC restricted voters linked to multiple units |
|---|---:|---:|
| Concorde Midway | 9 | 0 |
| Purnima Classic | 0 | 0 |
| Silicon Oasis | 0 | 0 |

## Verification and simple next steps

Ward outputs are byte-identical to v5 (350 Concorde, 48 Purnima, 415 Silicon Oasis rows). Indexed AC lookup is also byte-identical on that full ward regression. Behavioral tests cover collisions, seed independence, label priority, station identity, abstention, reviewed overrides, and indexed/original equivalence.

Use full apartment phrases first. When labels are sparse, review clusters supported by several distinct exact names and flats rather than the raw fuzzy-match count. Review excluded matches and common-name cases before changing thresholds. Distance could later help rank nearby booths, but it needs reliable coordinates and may miss legitimate registrations at older addresses; no coordinates are provided here.

Regenerate this report after running AC with --compare-baseline:

```sh
python3 compare_runs.py --ac-csv data/ac_voters.csv --sensitivity-dir outputs/ac_purnima_single_label --ward-filter-outputs outputs/ward_station_check --ward-single-label-outputs outputs/ward_purnima_single_label
```
