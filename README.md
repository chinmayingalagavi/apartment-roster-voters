# Apartment voter matching v6

V6 has two explicit modes:

- **Ward:** the original v5 matching rules, without polling-station filtering.
- **AC:** suggest polling booths for each apartment, then apply the existing matching rules only to voters at the selected booths.

The AC restriction addresses repeated house numbers and names across a large constituency. It does not prove that every retained match is correct. See `COMPARISON.md` for the run on the supplied inputs.

## Run

Python 3 with `pandas` is required. Excel preparation also uses `openpyxl`.

```sh
python3 -m pip install -r requirements.txt

# Original ward algorithm; apartment defaults to all.
python3 build_apartment_matches.py --mode ward

# Prepare the supplied AC workbook once. Source records are preserved.
python3 prepare_voters.py --source ../data/AC_176_BANGALORE_SOUTH.xlsx \
  --output data/ac_voters.csv --sheet Voters_1 --station-number-as-part

# Suggest booths and match only within them.
python3 build_apartment_matches.py --mode ac --voter-csv data/ac_voters.csv

# Include an unrestricted run on the SAME AC roll for comparison.
python3 build_apartment_matches.py concorde --mode ac \
  --voter-csv data/ac_voters.csv --compare-baseline
```

AC mode requires an explicit `--voter-csv`; it never silently uses the ward input. `--output-dir` changes the output folder. `--output-csv` chooses one apartment's exact output filename.

## How AC station selection works

The default `--station-evidence labels-first` works independently for each apartment:

1. Count voters whose addresses explicitly name the apartment. Suggest booths supported by at least **3 distinct voters at 2 distinct normalized address strings**.
2. If no booth passes that test, use conservative exact-name seeds. Suggest booths supported by at least **3 distinct people, names, and units**. Each voter name must exactly match a multi-word roster name that identifies one roster unit globally, and the voter's address must be compatible with that unit. Initials are preserved; name word order, case, and punctuation are ignored. Fuzzy names, single-word names, relation names, and inherited household links cannot seed this fallback.
3. Match within the selected booths only. If neither signal supports a booth, write an empty match CSV with `selection_status=no_supported_stations`, plus the station and weak-label review reports. This means insufficient search-location evidence, not that the apartment has no voters.

Apartment-name evidence takes priority: exact-name clusters at other booths do not automatically widen a label-supported shortlist. `--station-evidence matches`, `labels`, and `either` expose alternatives for comparison. `--min-label-voters`, `--min-label-addresses`, and `--min-match-units` change the thresholds; defaults are initial practical rules, not statistically calibrated cutoffs.

Station keys use normalized **polling name plus polling address**, including booth/room numbers. Different booths in one building remain separate. Case, punctuation, and spacing normalize; spelling differences are not fuzzy-merged. With one field absent, the available field is used with an explicit prefix. With both absent, the row cannot select or enter a booth automatically.

Repeated EPIC IDs count once for discovery. Conflicting copies across stations cannot seed label evidence; conflicting station/unit copies also cannot seed exact-name evidence. Source voter rows are preserved in the matching results.

## Reviewing suggested booths

```sh
# Discovery and review files only; no final matching.
python3 build_apartment_matches.py concorde --mode ac \
  --voter-csv data/ac_voters.csv --suggest-only

# Edit the report's selected column, then rerun with the reviewed selection.
python3 build_apartment_matches.py concorde --mode ac \
  --voter-csv data/ac_voters.csv \
  --stations-csv outputs/ac/polling_stations/concorde_stations.csv
```

The station report includes all observed booths, label voters/addresses, exact-match voters/units/names, automatic `suggested`, active `selected`, and the evidence `reason`. A reviewed override needs `apartment_key`, `station_key`, and `selected` (true/false). Unknown/blank selected keys and duplicate apartment/station entries are rejected. One combined override file can cover multiple apartments.

Weak apartment-label rows outside the shortlist remain in a separate review file. With `--compare-baseline`, every original match excluded by the restriction is also saved. Lower output counts alone do not establish better accuracy.

## Inputs

Local inputs and outputs are ignored by Git.

`apartments.csv` identifies the apartments; use `apartments.example.csv` as a template:

```text
key,apartment_name,roster_path,keywords,extra_filler_terms,station_keywords
```

- `key`: unique short key, also used in output filenames.
- `apartment_name`: readable output label.
- `roster_path`: CSV path relative to the apartment-list file.
- `keywords`: semicolon-separated legacy matching aliases; these still control ward/address matching.
- `extra_filler_terms`: optional address terms ignored while parsing units.
- `station_keywords`: optional, separately reviewed discovery aliases. Without these, full/compound apartment phrases are used. Use phrases specific to this development across the **entire AC**. A bare brand such as `Concorde` also names other developments; generic `Classic` or `Oasis` is unsuitable. Explicitly supplied single-word aliases are trusted, so use them carefully.

Each standardized roster uses one row per person:

```text
apartment_key,unit,block,unit_part,name,status
```

Provide either `unit`, such as `B-102`, or `block` plus `unit_part`. Units are normalized on load (`B-102` becomes `B102`; short numeric unit parts are padded to three digits). Status is copied from the roster. Whole-word block names and unambiguous first-letter block aliases are supported.

Both modes consume the existing voter CSV schema:

```text
serial_number,epic_number,name,relation_type,relation_name,house_number,age,gender,section_raw,part,ward,corporation,pincode,pollingname,pollingaddress
```

The supplied AC workbook has no separate electoral-roll `part` column. Its explicit polling-station number is used as a local grouping key only when `prepare_voters.py --station-number-as-part` is supplied. Its global serial numbers are preserved. Missing relation types and corporation values stay blank. Conversion produces a provenance JSON with source/output hashes, field mappings, duplicate counts, missing-value counts, and the source update date. Do not assume AC/ward numbering or source coverage is interchangeable.

## Outputs and matching rules

Default folders are `outputs/ward/` and `outputs/ac/`. Each contains `{key}_voters.csv` and timestamped logs. AC additionally writes:

```text
polling_stations/{key}_stations.csv
review/{key}_labels_outside_stations.csv
comparison/{key}_original_voters.csv       # with --compare-baseline
comparison/{key}_excluded_voters.csv
comparison/{key}_added_voters.csv
review/{key}_multiple_units.csv
```

Every match row preserves the v5 schema: apartment/unit/status, `apartment_connection`, `part_name_match`, `name_match_pct`, `voter_link_type`, and voter-list fields. `Unassigned` means the unit is known but roster status is unresolved. `Unmapped` means the apartment is identified but no single unit is established. Direct voter-name evidence takes priority over relation names; household members require address and name evidence. Address-only assignment requires an apartment label and exactly one unit candidate.

The existing fuzzy-name rules use 90% word/whole-name thresholds, with constrained initial and single-name rules. Similarity percentages describe name comparisons, not identity probabilities. V6 does not loosen these rules. AC uses equivalent indexed candidate lookup for speed; ward keeps the original lookup path.

## Files and checks

`build_apartment_matches.py` runs the two modes. `ward.py` contains the original matching pipeline with optional equivalent AC indexing. `matching.py` contains the unchanged v5 name/address helpers. `polling_stations.py` builds label-based booth reports. `ac_matching.py` supplies exact seeds, the shared matcher adapter, and comparison helpers. `prepare_voters.py` streams the source Excel workbook into CSV.

`compare_runs.py --ac-csv data/ac_voters.csv` generates `COMPARISON.md` and an aggregate JSON from the completed ward and AC outputs. It distinguishes output rows, unique voters, additional voter IDs, shared ward links, and voters linked to multiple units. To include the separate Purnima one-label experiment:

```sh
python3 build_apartment_matches.py purnima --mode ac --voter-csv data/ac_voters.csv \
  --min-label-voters 1 --min-label-addresses 1 --output-dir outputs/ac_purnima_single_label
python3 compare_runs.py --ac-csv data/ac_voters.csv --sensitivity-dir outputs/ac_purnima_single_label
```

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile build_apartment_matches.py ac_matching.py polling_stations.py ward.py matching.py prepare_voters.py
```

The behavioral tests cover unrelated name/unit collisions, seed independence, label priority, booth identity, missing metadata, overrides, abstention, and equivalence of indexed/original matching. The supplied ward outputs were also compared byte-for-byte with v5.
