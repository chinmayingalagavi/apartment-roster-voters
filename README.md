# Apartment voter matching

This folder contains a standalone matcher for linking apartment rosters to voter-list rows.

```sh
python3 code/build_apartment_matches.py
```

This runs every apartment listed in `data/apartments.csv` using the default voter list.

Paths below are shown from this repository folder.

## Files

| path | purpose |
|---|---|
| `code/` | Matcher, dependencies, and the apartment list template. |
| `data/` | Local apartment list, voter lists, and original rosters. |
| `output/` | Generated workbooks and timestamped run logs. |

The script needs Python 3, `pandas`, and `openpyxl` (for the Excel output).

Install Python dependencies with:

```sh
python3 -m pip install -r code/requirements.txt
```

`data/` and `output/` are ignored by Git.

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
data/apartments.csv
```

Create it from `code/apartments.example.csv`. The sample roster path assumes the roster is alongside the apartment list in `data/`.

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
sample_residency,Sample Residency,sample_residency.xlsx,sample residency;sampel residency,PHASE
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
| `relation_name` | Recorded relative's name. Compared with roster names and the names of voters already matched to the flat. |
| `house_number` | Address text. Used to find apartment names and unit numbers. |
| `part` | Voter-list part. Used to keep number-only address groups local. |

The other columns are copied into the output.

## Run

Run all apartments with the default voter list:

```sh
python3 code/build_apartment_matches.py
```

Run all apartments with the prepared constituency voter list:

```sh
python3 code/build_apartment_matches.py all --voter-csv data/ac_voters.csv --output-dir output/ac
```

Run one apartment:

```sh
python3 code/build_apartment_matches.py <apartment_key>
```

Run one apartment and choose the exact output file:

```sh
python3 code/build_apartment_matches.py <apartment_key> --output-xlsx output/check.xlsx
```

Run with a different apartment list:

```sh
python3 code/build_apartment_matches.py all --apartments-csv path/to/apartments.csv
```

Run with a different voter list:

```sh
python3 code/build_apartment_matches.py all --voter-csv path/to/voters.csv
```

The apartment argument defaults to `all`. Use an apartment key from the apartment list to run just that apartment. Use `--output-dir` to change where the workbooks and log are written.

## Outputs

Each apartment gets one Excel workbook. The default path is:

```text
output/{apartment_key}_voters.xlsx
```

Each workbook has three sheets:

| sheet | contents |
|---|---|
| `voters_mapped_tohouse` | Voter-list rows linked to an apartment unit. |
| `voters_unmapped` | Household groups whose voter-roll address gives the configured apartment name and whose members have no linked unit. |
| `not_found_in_voterlist` | Roster rows that no voter row is connected through, in roster order and in the roster format used for matching. |

Together, the roster people named in `apartment_connection` on `voters_mapped_tohouse` and the rows on `not_found_in_voterlist` cover the prepared roster. A roster person counts as matched only when a voter row in their own unit names them in `apartment_connection`. A roster person whose household was found through someone else, or only through an address, is still listed on `not_found_in_voterlist`.

### `voters_mapped_tohouse` sheet

Each row is one voter-list row linked to one apartment unit. Rows are sorted by apartment unit, then status, then voter-list order. Each unit's rows share a light fill that alternates between consecutive units.

Columns come in this order: apartment details, the roster connection with its part-name and full-name match %, the count of other households matched at the same booth, the link type, the voter-list name and relation, then the other voter-list columns.

| column | meaning |
|---|---|
| `apartment` | Apartment name. |
| `apartment_unit` | Normalized unit id used by the matcher. |
| `apartment_block` | Normalized block value, if any. |
| `apartment_unit_part` | Normalized non-block unit part. |
| `apartment_status` | Status from the roster (for example `Owner`, `Tenant`, or a `Yes`/`No` residency flag). `Unassigned` means the unit is known and the roster status is unresolved. |
| `apartment_connection` | The roster person this voter row is connected through (see below). Blank for address-only rows. |
| `part_name_match` | 0–100 similarity of the part of the name the match rule used: the weakest matched word pair (identical words = 100), or the whole-name similarity when the whole-name rule matched. Never below 90 for a name match. Household-member rows show the value of the voter they are linked through. Blank for address-only and `Unmapped` rows. |
| `name_match_pct` | 0–100 similarity between the voter-list name (or relation name) and `apartment_connection`. Household-member rows show the match % of the voter they are linked through. Blank for address-only and `Unmapped` rows. |
| `other_hh_matched_booth` | Number of other units with a candidate voter link at this row's polling booth before competing links are filtered. A row without a unit counts all units linked to the booth at that stage. |
| `voter_link_type` | Why this voter row was included. |
| `voter_name`, `relation_type`, `relation_name` | Name fields from the voter list. `voter_name` is the voter list's `name` column. |
| other columns | The remaining voter-list columns. |

`apartment_connection` is chosen in this order:

1. The roster person the voter's own name matched.
2. Otherwise, the roster person identified by the voter's recorded relation, when that person also appears as a voter directly matched to the flat.
3. Otherwise, for `same_address_household_member` rows, the roster person matched by the linked household voter's own name.

If the voter's own name also matched the roster person their relation name matched, the voter's other name match is used when there is one. If several roster people tie at the same match %, all are listed, separated by semicolons. Spellings of one name that differ only in case, spacing, or punctuation are listed once.

`name_match_pct` ignores case, punctuation, honorifics, spacing, and word order. It describes how similar the two names are; it does not decide the match. Names accepted through initials or one-word roster names (for example `Mira` against `Mira Example Name`) can show a low percentage.

Common `voter_link_type` values:

| value | meaning |
|---|---|
| `voter_name_match` | The voter name matched a roster name. |
| `relation_name_match` | The recorded relation matched a roster person and a different voter whose own name links that person to the same flat. The two voter-roll names must have the same name parts, or at least 90% full-name similarity with compatible first names or initials. Used when the voter's own name matched no one in the apartment. |
| `explicit_apartment_address` | The voter address names the apartment. Without a name match, the row is linked to a unit only if the address points to exactly one unit; otherwise it is `Unmapped`. |
| `same_address_household_member` | The row shares an address and a name link with a voter whose own name matched the roster at that flat. |

Multiple link types are separated by semicolons.

### `voters_unmapped` sheet

The sheet lists one row per voter-roll household group. It includes the reported address, voter-roll part and section, polling station, voter count, and voter serial numbers for lookup in the source voter list. Household IDs group nearby entries in the same part and section using the matcher's address or unit key.

The address must contain the full name from `apartment_name` after normalizing case, punctuation, and spacing. A group appears when at least one row meets that rule and no member links to a unit. The voter count and serial numbers refer to the qualifying rows.

## Run Logs

Every run writes a timestamped JSON log:

```text
output/log/run_YYYYMMDD_HHMMSS.json
```

The log starts with these column lists, in this order:

1. `apartments_csv_columns`: columns expected in the apartment list CSV.
2. `individual_related_columns`: voter/person columns such as name, relation name, age, and gender.
3. `household_related_columns`: address, unit, status, and household-link columns.
4. `voters_sheet_columns`: all columns on `voters_mapped_tohouse`.

Then it records run metadata and one summary per apartment:

| field | meaning |
|---|---|
| `voter_csv` | Voter-list CSV used for the run. |
| `apartments_csv` | Apartment list CSV used for the run. |
| `roster_source` | Original workbook or CSV read for the apartment. |
| `output_xlsx` | Output workbook written for the apartment. |
| `roster_rows` | Number of person rows in the apartment roster. |
| `roster_households` | Number of unique roster units. |
| `roster_rows_not_matched` | Number of rows on `not_found_in_voterlist`. |
| `unmapped_households` | Number of household groups on `voters_unmapped`. |
| `mapped_voter_rows` | Number of rows on `voters_mapped_tohouse`. |
| `output_rows` | Number of voter rows linked to the apartment, including rows without a unit. |
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

The matcher uses the address to find possible apartment units. It then checks voter names against roster names. Two name words count as the same if they are identical, or both have at least 5 letters and are at least 90% similar. The whole-name rule also needs at least 90% similarity. The other rules need some words (or an initial) to agree, so the full-name `name_match_pct` can be well below 90. A voter with an own-name match keeps their direct links. Relation and same-address household matches require a voter already linked to the same flat by their own name.

Address-only rows are linked to a unit only when the address names the apartment and maps cleanly to one unit.

If an address points to multiple possible units, name or relation evidence can choose the unit. If the address names the apartment but there is no name or relation evidence and no single unit (none found, or several possible), the row is kept with status `Unmapped` and no unit.

Two distinct voters can confirm a flat when each independently matches a different roster person there. The voter roll must link them through a recorded relation or through the same address in the same voter-roll household group. An unambiguous pair reserves those voter and roster matches within the apartment. Other people at the flat can still match through the usual rules. When pairs compete, a recorded relation takes priority, followed by a shared address within the same household group. Equally supported alternatives follow the usual matching rules.

For each roster person in a flat, an own-name candidate is kept if at most one other distinct voter record is at least as high on both full-name similarity and booth support and strictly higher on one. Equal scores on both measures stay tied. Booth support is counted once before filtering. Existing household links must still have a retained own-name match to support them.

## Check After Edits

After editing the code, run:

```sh
python3 -m py_compile code/build_apartment_matches.py code/matching.py
python3 code/build_apartment_matches.py
```
