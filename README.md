# Apartment voter matching

This folder contains a standalone matcher for linking apartment rosters to voter-list rows.

```sh
python3 build_apartment_matches.py
```

This runs every apartment listed in `apartments.csv`.

Paths below are shown from this repository folder.

## Files

| path | purpose |
|---|---|
| `build_apartment_matches.py` | Main script. Run this file. |
| `matching.py` | Shared address and name matching logic. |
| `apartments.example.csv` | Template for the apartment list CSV. |
| `apartments.csv` | Local apartment list CSV that you create from the template. |
| `data/` | Voter-list CSV input files. |
| `standardized_rosters/` | Apartment roster CSV input files. |
| `outputs/` | Default output folder. |
| `outputs/log/` | Timestamped run logs created when you run the script. |

The script needs Python 3 and `pandas`.

Install Python dependencies with:

```sh
python3 -m pip install -r requirements.txt
```

`apartments.csv`, `data/`, `standardized_rosters/`, and `outputs/` are local working inputs and outputs. They are ignored by git.

## Inputs

The matcher needs three kinds of CSV input:

1. One voter-list CSV.
2. One apartment list CSV.
3. One standardized roster CSV for each apartment.

The default voter list is:

```text
data/voters.csv
```

The default apartment list is:

```text
apartments.csv
```

Create it by using `apartments.example.csv` as a template.

## Apartment List CSV Format

The apartment list CSV tells the script which apartments to run and where their roster files are.

It should have these columns:

```text
key,apartment_name,roster_path,keywords,extra_filler_terms,output_path
```

| column | meaning |
|---|---|
| `key` | Short apartment key. This is the command-line key and should match `apartment_key` in the roster CSV. |
| `apartment_name` | Apartment name written to the output. |
| `roster_path` | Path to the standardized roster CSV. Relative paths are read relative to the apartment list CSV. |
| `keywords` | Semicolon-separated words or phrases that identify this apartment in voter addresses. Include the full apartment name, each word in the apartment name, and useful misspellings. |
| `extra_filler_terms` | Optional semicolon-separated address words to ignore while parsing unit numbers. These terms do not identify the apartment by themselves. |
| `output_path` | Optional default output file if no output option is given. Relative paths are read relative to the apartment list CSV. Blank means `outputs/{key}_voters.csv`. |

Example row:

```csv
key,apartment_name,roster_path,keywords,extra_filler_terms,output_path
sample_residency,Sample Residency,standardized_rosters/sample_residency.csv,sample residency;sample;residency;sampel residency,PHASE,outputs/sample_residency_voters.csv
```

Do not put another apartment's name in `keywords` or `extra_filler_terms`.

## Roster CSV Format

Each roster CSV must have these columns:

```text
apartment_key,unit,block,unit_part,name,status
```

| column | meaning |
|---|---|
| `apartment_key` | Short apartment key. If filled, it must match `key` in `apartments.csv`. Blank values are treated as the current apartment key. |
| `unit` | Full unit id if available. It can be raw. Examples: `B102`, `B-102`, `203`, `10191`. |
| `block` | Block, wing, tower, or row-house prefix if separate from the number. Examples: `A`, `B`, `Cedar`. Leave blank if there is no block. |
| `unit_part` | Unit number without the block. Examples: `102`, `203`, `10191`. |
| `name` | Person name from the apartment roster. Use one row per person. |
| `status` | Roster status copied to the output. Examples: `Owner`, `Tenant`, `Resident`. Blank status becomes `Unknown`. |

For a blocked apartment, either of these is enough:

```text
unit=B102
```

or:

```text
block=B
unit_part=102
```

For an apartment without blocks, put the unit number in either `unit` or `unit_part`.

You do not need to fill both `unit` and `block` / `unit_part`. If both are filled and they disagree, `unit` wins.

The script normalizes units before matching:

| roster values | normalized unit |
|---|---|
| `unit=B-102` | `B102` |
| `block=B`, `unit_part=102` | `B102` |
| `unit=203` | `203` |
| `unit=10191` | `10191` |

Full block names are supported. If the roster has `block=Cedar`, the matcher can read voter addresses such as `Cedar 112`, `112 Cedar`, `C112`, and `C-112`, as long as `C` is not also the first letter of another block in the same apartment.

## Voter CSV Format

The voter CSV must have these columns:

```text
serial_number,epic_number,name,relation_type,relation_name,house_number,age,gender,section_raw,part,ward,corporation,pincode,pollingname,pollingaddress
```

Important matching columns:

| column | use |
|---|---|
| `name` | Voter name. Compared with roster names. |
| `relation_name` | Relation name. Also compared with roster names. |
| `house_number` | Address text. Used to find apartment names and unit numbers. |
| `part` | Voter-list part. Used to keep number-only address groups local. |

The other columns are copied into the output.

## Run

Run all apartments listed in `apartments.csv`:

```sh
python3 build_apartment_matches.py
```

That is the same as:

```sh
python3 build_apartment_matches.py all
```

Run all apartments and force a shared output folder:

```sh
python3 build_apartment_matches.py all --output-dir outputs
```

Run one apartment:

```sh
python3 build_apartment_matches.py <apartment_key> --output-dir outputs
```

Run one apartment and choose the exact output file:

```sh
python3 build_apartment_matches.py <apartment_key> --output-csv outputs/check.csv
```

Run with a different apartment list:

```sh
python3 build_apartment_matches.py all --apartments-csv path/to/apartments.csv --output-dir outputs
```

Run with a different voter list:

```sh
python3 build_apartment_matches.py all --voter-csv path/to/voters.csv --output-dir outputs
```

The apartment argument is optional. If omitted, it defaults to `all`. If provided, it must be `all` or one apartment key from `apartments.csv`.

## Outputs

With `--output-dir outputs`, output files are named:

```text
outputs/{apartment_key}_voters.csv
```

Without `--output-dir`, each apartment uses `output_path` from `apartments.csv`. If `output_path` is blank, the default is `outputs/{apartment_key}_voters.csv`.

Each output row is one voter-list row linked to one apartment unit.

Output columns include the original voter columns plus:

| column | meaning |
|---|---|
| `apartment` | Apartment name. |
| `apartment_unit` | Normalized unit id used by the matcher. |
| `apartment_block` | Normalized block value, if any. |
| `apartment_unit_part` | Normalized non-block unit part. |
| `apartment_status` | Status from the roster. |
| `apartment_names_in_house` | Roster names in that unit and status group. |
| `voter_link_type` | Why this voter row was included. |

Common `voter_link_type` values:

| value | meaning |
|---|---|
| `voter_name_match` | The voter name matched a roster name. |
| `relation_name_match` | The voter relation name matched a roster name. |
| `explicit_apartment_address` | The voter address names the apartment and points to one unit. |
| `same_address_household_member` | The row shares an address with another row that matched by name or relation. |

Multiple link types are separated by semicolons.

## Run Logs

Every run writes a timestamped JSON log:

```text
outputs/log/run_YYYYMMDD_HHMMSS.json
```

The log starts with these column lists, in this order:

1. `apartments_csv_columns`: columns expected in the apartment list CSV.
2. `individual_related_columns`: voter/person columns such as name, relation name, age, and gender.
3. `household_related_columns`: address, unit, status, and household-link columns.
4. `apartment_output_csv_columns`: all columns written to the generated apartment output CSV files.

Then it records run metadata and one summary per apartment:

| field | meaning |
|---|---|
| `voter_csv` | Voter-list CSV used for the run. |
| `apartments_csv` | Apartment list CSV used for the run. |
| `roster_rows` | Number of person rows in the apartment roster. |
| `roster_households` | Number of unique roster units. |
| `output_rows` | Number of voter rows written to the apartment output CSV. |
| `output_households` | Number of unique apartment units in the output. |
| `headline_match_rows` | Rows with a voter-name or relation-name match. |
| `headline_match_households` | Unique units with a voter-name or relation-name match. |
| `rows_by_status` | Output row counts by roster status. |
| `households_by_status` | Output household counts by roster status. |
| `rows_by_link_type` | Row counts for each match type. |
| `households_by_link_type` | Household counts for each match type. |
| `rows_by_exact_link_type` | Row counts for exact semicolon-combined `voter_link_type` values. |

The link-type counts are not mutually exclusive. A row can have more than one link type.

## Matching Summary

The matcher uses the address to find possible apartment units. It then checks voter names and relation names against roster names.

Address-only rows are included only when the address names the apartment and maps cleanly to one unit.

If an address points to multiple possible units, name or relation evidence can choose the unit. If there is no name or relation evidence and the unit is ambiguous, the row is not assigned.

## Check After Edits

After editing the code, run:

```sh
python3 -m py_compile build_apartment_matches.py matching.py
python3 build_apartment_matches.py
```
