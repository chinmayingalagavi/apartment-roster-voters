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
| `data/` | Voter-list CSV and source roster files. |
| `outputs/` | Default output folder. |
| `outputs/log/` | Timestamped run logs created when you run the script. |

The script needs Python 3, `pandas`, and `openpyxl` (for the Excel output).

Install Python dependencies with:

```sh
python3 -m pip install -r requirements.txt
```

`apartments.csv`, `data/`, and `outputs/` are local working inputs and outputs. They are ignored by git.

## Inputs

The matcher needs three kinds of input:

1. One voter-list CSV.
2. One apartment list CSV.
3. One source roster file for each apartment. The matcher prepares it in memory during the run.

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
key,apartment_name,roster_path,keywords,extra_filler_terms
```

| column | meaning |
|---|---|
| `key` | Short apartment key. Use it to select an apartment on the command line. |
| `apartment_name` | Apartment name written to the output. |
| `roster_path` | Path to the source roster workbook or CSV. Relative paths are read relative to the apartment list CSV. |
| `keywords` | Semicolon-separated phrases that identify this apartment in voter addresses. Use only the full apartment name and full-length misspellings of it. Do not add single words from the name, shortened forms, or anything that could name another place: a word like `classic` or `oasis` also matches other developments. |
| `extra_filler_terms` | Optional semicolon-separated address words to ignore while parsing unit numbers. These terms do not identify the apartment by themselves. |

Example row:

```csv
key,apartment_name,roster_path,keywords,extra_filler_terms
sample_residency,Sample Residency,data/sample_residency.xlsx,sample residency;sampel residency,PHASE
```

Do not put another apartment's name in `keywords` or `extra_filler_terms`.

## Source roster formats

The matcher reads the original Excel files for `concorde`, `purnima`, and `silicon_oasis`, and the original CSV for `tirumala_vintage`. Use these apartment keys to select the corresponding source format.

For other apartments, use a CSV or Excel file with the columns below. Include `name` and at least one of `unit` or `unit_part`. The remaining fields can be blank or omitted. Existing roster CSVs in this format also work.

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
python3 build_apartment_matches.py <apartment_key> --output-xlsx outputs/check.xlsx
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

Each apartment gets one Excel workbook. With `--output-dir outputs`, workbooks are named:

```text
outputs/{apartment_key}_voters.xlsx
```

Without `--output-dir`, workbooks are also written as `outputs/{apartment_key}_voters.xlsx`.

Each workbook has two sheets:

| sheet | contents |
|---|---|
| `voters` | The voter-list rows linked to the apartment, described below. |
| `roster_not_matched` | The roster rows that no voter row is connected through, in roster order and in the roster format used for matching. |

Together, the roster people named in `apartment_connection` on the `voters` sheet and the rows on the `roster_not_matched` sheet cover the prepared roster. A roster person counts as matched only when a voter row in their own unit names them in `apartment_connection`. A roster person whose household was found through someone else, or only through an address, is still listed on `roster_not_matched`.

### `voters` sheet

Each row is one voter-list row linked to one apartment unit, except `Unmapped` rows, which are linked to the apartment only. Rows are sorted by apartment unit, then status, then voter-list order, so each household's voters sit together. `Unmapped` rows come last.

Columns come in this order: apartment details, the roster connection with its part-name and full-name match %, the count of other households matched at the same booth, the link type, the voter-list name and relation, then the other voter-list columns.

| column | meaning |
|---|---|
| `apartment` | Apartment name. |
| `apartment_unit` | Normalized unit id used by the matcher. |
| `apartment_block` | Normalized block value, if any. |
| `apartment_unit_part` | Normalized non-block unit part. |
| `apartment_status` | Status from the roster (for example `Owner`, `Tenant`, or a `Yes`/`No` residency flag). `Unassigned`: the unit is known but the status is not (an address-only row, or a voter linked to the unit under two statuses). `Unmapped`: the address names the apartment but no single unit could be read from it; unit columns are blank. |
| `apartment_connection` | The roster person this voter row is connected through (see below). Blank for address-only rows. |
| `part_name_match` | 0–100 similarity of the part of the name the match rule used: the weakest matched word pair (identical words = 100), or the whole-name similarity when the whole-name rule matched. Never below 90 for a name match. Household-member rows show the value of the voter they are linked through. Blank for address-only and `Unmapped` rows. |
| `name_match_pct` | 0–100 similarity between the voter-list name (or relation name) and `apartment_connection`. Household-member rows show the match % of the voter they are linked through. Blank for address-only and `Unmapped` rows. |
| `other_hh_matched_booth` | Number of other apartment households (units) with at least one matched voter at this row's polling booth (`part`). 0 means this row's household is the only one matched there. `Unmapped` rows have no unit, so every household matched at their booth counts. A building's residents usually share a few booths, so real matches tend to have many other households at their booth, while chance name matches are often alone. |
| `voter_link_type` | Why this voter row was included. |
| `voter_name`, `relation_type`, `relation_name` | Name fields from the voter list. `voter_name` is the voter list's `name` column. |
| other columns | The remaining voter-list columns. |

`apartment_connection` is chosen in this order:

1. The roster person the voter's own name matched.
2. Otherwise, the roster person the voter's relation name matched.
3. Otherwise, for `same_address_household_member` rows, the roster person that the linked household member was connected through.

If the voter's own name also matched the roster person their relation name matched, the voter's other name match is used when there is one. If several roster people tie at the same match %, all are listed, separated by semicolons. Spellings of one name that differ only in case, spacing, or punctuation are listed once.

`name_match_pct` ignores case, punctuation, honorifics, spacing, and word order. It describes how similar the two names are; it does not decide the match. Names accepted through initials or one-word roster names (for example `Mira` against `Mira Example Name`) can show a low percentage.

Common `voter_link_type` values:

| value | meaning |
|---|---|
| `voter_name_match` | The voter name matched a roster name. |
| `relation_name_match` | The voter relation name matched a roster name. Used only when the voter's own name matched no one in the apartment. |
| `explicit_apartment_address` | The voter address names the apartment. Without a name match, the row is linked to a unit only if the address points to exactly one unit; otherwise it is `Unmapped`. |
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
4. `voters_sheet_columns`: all columns on the `voters` sheet of each output workbook.

Then it records run metadata and one summary per apartment:

| field | meaning |
|---|---|
| `voter_csv` | Voter-list CSV used for the run. |
| `apartments_csv` | Apartment list CSV used for the run. |
| `roster_source` | Original workbook or CSV read for the apartment. |
| `output_xlsx` | Output workbook written for the apartment. |
| `roster_rows` | Number of person rows in the apartment roster. |
| `roster_households` | Number of unique roster units. |
| `roster_rows_not_matched` | Number of rows on the `roster_not_matched` sheet. |
| `output_rows` | Number of voter rows on the `voters` sheet. |
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

The matcher uses the address to find possible apartment units. It then checks voter names against roster names. Two name words count as the same if they are identical, or both have at least 5 letters and are at least 90% similar. The whole-name rule also needs at least 90% similarity. The other rules need some words (or an initial) to agree, so the full-name `name_match_pct` can be well below 90. Relation names are checked only for voters whose own name matched no one in the apartment; a voter with a direct match keeps only their direct links.

Address-only rows are linked to a unit only when the address names the apartment and maps cleanly to one unit.

If an address points to multiple possible units, name or relation evidence can choose the unit. If the address names the apartment but there is no name or relation evidence and no single unit (none found, or several possible), the row is kept with status `Unmapped` and no unit.

## Check After Edits

After editing the code, run:

```sh
python3 -m py_compile build_apartment_matches.py matching.py
python3 build_apartment_matches.py
```
