# V6 comparison

Run on 05 November 2026 using the supplied AC workbook and existing ward CSV.

The AC source has 422,012 voter rows and 605 polling-station entries (source update: 24-08-2026). The ward CSV has 20,200 rows. The AC source has no separate roll-part column: its station-number prefix is used explicitly as a local grouping key. The original source files were preserved.

## Result counts

The two AC columns use the same source. Ward uses the original v5 rules. Restricted AC first selects booths from development-specific apartment-label evidence, with exact-name/unit clusters as fallback when label evidence is insufficient.

| Apartment | Original ward | Original on AC | Restricted AC | Selected booths | Eligible AC voters |
|---|---:|---:|---:|---:|---:|
| Concorde Midway | 350 | 2,629 | 231 | 4 | 2,390 |
| Purnima Classic | 48 | 538 | 0 | 0 | 0 |
| Silicon Oasis | 415 | 1,350 | 518 | 8 | 6,421 |

Counts are output rows, each linking a source voter row to a unit or retaining an apartment-only Unmapped entry. Fewer rows do not by themselves prove higher precision.

## Additional coverage and shared ward links

Only 9,388 of the ward's 20,199 unique voter IDs appear in the AC source (46.48%). AC is not a superset of this ward extract, so changes in total counts combine source differences and matching effects.

| Apartment | AC original voters absent from ward output | AC restricted voters absent from ward output | Ward unit-links whose IDs occur in AC | Those links found by AC original | Those links found by AC restricted |
|---|---:|---:|---:|---:|---:|
| Concorde Midway | 2,165 | 19 | 219 | 213 | 209 |
| Purnima Classic | 518 | 0 | 26 | 20 | 0 |
| Silicon Oasis | 1,014 | 186 | 339 | 336 | 332 |

Additional voters are candidates for review, not verified new residents. The ward matches are also algorithmic links, not a ground-truth identity set. Shared-ID unit-link overlap is a coverage check only.

## Station selection and review

- **Concorde Midway**: station numbers 335, 336, 334, 337. The restriction excludes 2,398 original AC links and adds 0; excluded rows remain in the local review CSV.
- **Purnima Classic**: station numbers none. The restriction excludes 538 original AC links and adds 0; excluded rows remain in the local review CSV. No station passed the automatic evidence thresholds; the empty result means abstention, not absence of voters.
- **Silicon Oasis**: station numbers 345, 346, 344, 357, 356, 353, 354, 351. The restriction excludes 832 original AC links and adds 0; excluded rows remain in the local review CSV.

Bare Concorde brand aliases initially suggested 20 booths / 10,736 voters, including other developments such as Manhattan and Tech Turf. Restricting discovery to Midway-specific phrases selects four booths / 2,390 voters. Discovery keywords therefore need to identify a development across the entire AC, not merely its brand.

Purnima has too little compound-label/exact-name evidence under the default thresholds. Its low-evidence booths remain in the station report for manual selection or a separately labeled threshold-sensitivity run. The matcher never silently falls back to searching the full AC.

## One-label sensitivity experiment

This separate experiment lowers both label thresholds to one. It does not change the default shortlist. A booth supported by one voter needs review.

- Purnima Classic: 6 rows at 2 booths, including 2 voter IDs absent from the ward output. Separate CSVs and log: outputs/ac_purnima_single_label/.

## Multiple-unit ambiguity

A voter linked to several flats in one apartment needs review. These links are preserved rather than assigned arbitrarily; retained ambiguous rows are written to review/{key}_multiple_units.csv.

| Apartment | AC original voters linked to multiple units | AC restricted voters linked to multiple units |
|---|---:|---:|
| Concorde Midway | 183 | 2 |
| Purnima Classic | 0 | 0 |
| Silicon Oasis | 0 | 0 |

## Verification and simple next steps

Ward outputs are byte-identical to v5 (350 Concorde, 48 Purnima, 415 Silicon Oasis rows). Indexed AC lookup is also byte-identical on that full ward regression. Behavioral tests cover collisions, seed independence, label priority, station identity, abstention, reviewed overrides, and indexed/original equivalence.

Use full apartment phrases first. When labels are sparse, review clusters supported by several distinct exact names and flats rather than the raw fuzzy-match count. Review excluded matches and common-name cases before changing thresholds. Distance could later help rank nearby booths, but it needs reliable coordinates and may miss legitimate registrations at older addresses; no coordinates are provided here.

Regenerate this report after running AC with --compare-baseline:

```sh
python3 compare_runs.py --ac-csv data/ac_voters.csv --sensitivity-dir outputs/ac_purnima_single_label
```
