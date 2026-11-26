# Apartment voter matching

Match a voter list against apartment rosters and get one Excel workbook per apartment.

Download the desktop app for [Mac with Apple silicon](https://github.com/chinmayingalagavi/apartment-roster-voters/releases/latest/download/Apartment-Voter-Matcher-macOS-Apple-Silicon.zip) or [64-bit Windows](https://github.com/chinmayingalagavi/apartment-roster-voters/releases/latest/download/Apartment-Voter-Matcher-Windows-x64.exe). These links always use the latest release. Unzip the Mac download and open the app, or open the Windows executable. [Release notes and instructions](https://github.com/chinmayingalagavi/apartment-roster-voters/releases/latest)

## Run from a terminal

Create a `data/` folder in this repository. Put the voter list and apartment rosters in it. Each file can be CSV or XLSX and can have any filename. Save the apartment list itself as `data/apartments.csv` or `data/apartments.xlsx`.

```csv
Bangalore South,Bangalore South constituency.xlsx
Sample Residency,Owners and tenants.xlsx,Sample Apartments;Sample Residency Phase 1
Example Heights,Example residents.csv
```

Put the AC or ward name in the first cell of row 1 and the voter filename in the second cell. Starting on row 2, put the primary apartment name in column A and its roster filename in column B. Use optional column C for other names that appear in voter addresses. Separate multiple names with semicolons. The workbook uses the primary name, and the matcher checks addresses for all listed names. Use the first worksheet for XLSX files. Relative paths start at the folder containing the apartment list. [CSV template](code/apartments.example.csv)

Install Python 3.10 or newer. Open a terminal in this repository, then run the commands for your computer.

**Mac**

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r code/requirements.txt
.venv/bin/python code/build_apartment_matches.py
```

**Windows PowerShell**

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r code/requirements.txt
.\.venv\Scripts\python.exe code/build_apartment_matches.py
```

After setup, repeat just the last command. Open `output/` for the workbooks. The last column on each sheet, `searched_voter_list`, shows the AC or ward name.

The command uses `apartments.csv` first if both versions exist. To use a specific apartment list, add `--apartments-file` followed by its path. To choose a different voter file for one run, use `--voter-file` and give its AC or ward name with `--searched-voter-list`.

To export the preliminary name match list, run `python3 name_match/build_name_matches.py` with the same arguments. This writes the usual three sheets from the first resolved candidate list, before final selection, location support counts and strength grading. Both voter sheets have a blank `strength` column. The CLI defaults to `output/preliminary/` for this mode. You can also use `--preliminary-only` with the main command.

In the desktop app, select **Advanced → Include name match lists** to save both the scored workbook (`*_voters.xlsx`) and the preliminary workbook (`*_before_scoring.xlsx`) in the same results folder.

For new rosters, use one row per person with columns called `name` and `unit`. The four original roster formats are recognized by apartment name or by their usual `key` in an existing apartment list.

CSV and Excel column headings are case-insensitive in both the terminal and desktop app. For example, `Name`, `NAME`, and `name` all work. This applies to voter files, rosters, and apartment lists that use column headings.

You can use an original AC Excel export such as `AC_176_BANGALORE_SOUTH.xlsx` directly. The matcher recognizes its official column headings on the first worksheet. It reads the `Relation` column or the relationship prefix used in older exports. It uses a supplied `Part`, `Part No.` or `Part Number` value first, then the polling-station number. When neither is supplied, it groups consecutive rows at the same polling location and ward, using `Roll No.` resets when available to separate blocks. It fills a gap only when the surrounding station numbers leave exactly one unused number per block. Other blocks keep distinct negative local IDs.

For a prepared voter file, put these column names on the first row. `roll_number`, `relation_type` and `relation_name` are optional. The voter sheets keep their values when supplied.

```csv
serial_number,roll_number,epic_number,name,relation_type,relation_name,house_number,age,gender,section_raw,part,ward,corporation,pincode,pollingname,pollingaddress
```

## Matching algorithm

The terminal command and desktop app use the same algorithm. Every apartment uses the same rules, including the guarded 95% fallback described below. Its configured apartment names and roster determine the names and flats being searched.

### Definitions

- A **candidate** is a possible voter-to-flat link with a proposed roster person or household connection. Selection makes it eligible for final resolution.
- An **explicit apartment address** contains a configured primary or alternative apartment name as a complete phrase after address normalization. This ignores case, punctuation and repeated spaces, and separates letters from digits. Spelling variants must be supplied as alternative names.
- A **uniquely parsed flat** means `parsed_unit` identifies exactly one roster flat and equals the proposed flat. A number recovered by the fallback parser can produce a candidate without satisfying this condition. For example, `F207` for a roster containing only `207` can remain a number-based candidate.
- A **named flat** is a distinct flat in the preliminary candidate list with an explicit apartment address and a uniquely parsed flat. An address-only voter can establish this evidence without a roster-name connection. Multiple voters at one flat count once. A candidate's own flat is excluded from its supporting count.
- A **section** uses the exact, nonblank `section_raw` string. The main section route also requires the same voter-list `part`. The 95% fallback permits identical section text across parts.
- A **full name word** excludes single-letter initials and tokens recognized as bundles of initials. A **name token** includes initials. Both ignore configured honorifics.

The initial address parser also recognizes joined apartment-name words when attaching explicit-address evidence. Section support and the additional full-word search require the spaced normalized phrase.

### 1. Prepare addresses and generate preliminary candidates

Normalize roster names, blocks and flat numbers. Parse voter addresses against the roster, preserving block information. Consider complete flats, ambiguous block/number forms, number-only addresses and the existing long-number address rules. Evaluate names against people in the corresponding candidate flats.

The preliminary name matcher accepts several forms of evidence:

- Two matching full-word token pairs. Nonidentical words must each have at least five letters and reach 90% similarity.
- An exact full word when either name consists of that one word.
- A matching full word with compatible explicit initials.
- Whole-name similarity of at least 90%, comparing the full-word names with and without spaces. The shorter joined name must contain at least eight characters. Containment also qualifies when the shorter joined name contains at least ten characters.
- A prefix of at least five characters when the shorter word is that side's only full word.
- A contextual one-word own-name match supported by a separate independent own-name match to a different roster person at the flat. The shared matching word must be absent from that supporting voter's source and roster name words.

Own-name matches must also pass the first-name/initial identity check. Relation-to-roster comparisons use the stricter two-word, exact-single-word or word-plus-initial routes and the identity check. These preliminary rules do not impose a blanket minimum on the displayed `name_match_pct`.

Reserve unambiguous corroborated pairs before forming the preliminary list. Two distinct voters must independently match different roster people at one flat and be connected by either an identical normalized address within the same assigned voter-list household, or a named relation. Prefer named relations to shared-address evidence, and require an unambiguous best choice on both the voter and roster sides. Reserve those specific voter/roster pairs against competitors. Number-based candidates needing a second household match must satisfy the corroboration requirement.

Resolve the first candidate list using own-name evidence, eligible relations, eligible same-address members and explicit apartment addresses. The selection below operates on this list before confidence pruning.

### 2. Calculate name scores and freeze location evidence

`name_match_pct` is the rounded percentage from the best of three `difflib.SequenceMatcher` comparisons of normalized names: words in their original order with spaces, words joined without spaces, and words sorted alphabetically with spaces. Name normalization removes honorifics, ignores case and punctuation, and retains initials.

For an own-name link, this compares the voter name with the roster name. For a relation link, it compares the relation name with the roster name. A same-address household member inherits its supporting voter's roster-name score.

A separate **supporting voter score** records the actual own-name voter's score against that roster person. For own-name links it equals `name_match_pct`. When a rule requires both scores to reach a threshold, it tests the minimum of these two scores. Missing scores count as zero for eligibility and grading.

Count other distinct named flats in each `(part, section_raw)` group. Separately record named flats by `section_raw` alone for the 95% fallback. Compute these sets once from the preliminary list. Newly admitted candidates do not enlarge them.

### 3. Rank competing own-name connections

For candidates matching the same roster name at the same flat, compare `name_match_pct` and `other_hh_matched_booth`. A booth is the combination of `part` and `pollingname`. Booth support counts other distinct preliminary candidate flats there.

Discard a candidate's connection to that roster person if at least two distinct other voter records are at least as good on both measures and strictly better on at least one. Exact ties do not dominate. This can leave more than two candidates. Rankings use the full preliminary list, including rivals that might fail the later selection rules.

### 4. Select preliminary candidates

Keep a candidate if **any** of the following applies:

| Route | Required evidence |
| --- | --- |
| Explicit apartment address | The candidate's own voter address explicitly names the apartment. |
| Same-part section support | At least one other named flat is in the same part and exact section. Also require a uniquely parsed proposed flat, **or both name scores of at least 80%**. |
| Corroborated related pair | Two independent own-name voters match different roster people at the same flat, both addresses parse uniquely to that flat, one voter's relation name identifies the other voter, and the pair passes the unambiguous reservation rule. Each qualifying voter is eligible through this route. |
| Exact own name | An own-name match scores 100%, the voter's name has at least two full words, the proposed flat parses uniquely, and no unexplained address text remains after removing the flat, recognized apartment name and standard fillers. Initials do not count as full words. |
| Guarded 95% fallback | Both name scores are at least 95%, and another named flat has identical nonblank section text, including across parts. Also require a uniquely parsed proposed flat, **or an own-name match with at least two normalized name tokens**. Initials count as tokens. |

The 95% route admits a relation or household candidate through the uniquely parsed flat condition, subject to its surviving supporting voter in step 6. An ambiguous flat can use that route only through the voter's own name.

### 5. Search for additional full-word name matches

Search the full roll for voters not already mapped in the preliminary list. Require an explicit apartment name in the address and a uniquely parsed roster flat.

Both the voter and roster names must have at least two distinct full words. Accept if every full word on either side appears exactly in the other name, in any order. Ignore initials for this containment comparison. Reject the proposed own-name link if the voter's relation name also passes that containment test against the roster person.

Require exactly one matching roster entry at that flat, no existing preliminary own-name claim on that roster person, and exactly one new voter proposal for that person. Reject conflicting new claims together. Add accepted evidence to final resolution. These links do not change the frozen section counts or competing-match rankings.

### 6. Rebuild eligible household connections

Run the resolver using selected candidates, additional full-word matches and frozen competing-match exclusions. Resolve own-name links first. A contextual own-name link depends on its specific independent supporting match.

A relation link requires a different surviving own-name voter at the same flat who matches the same roster person. Its relation name must identify that voter. Identification requires at least 90% name similarity, plus either identical normalized name tokens or the first-name/initial identity check. A matching roster-relative name alone cannot establish the flat.

A same-address household member requires a surviving own-name voter at that flat in the same address group. Address groups include polling part and the normalized address or number-address key. The member must have that flat among their address candidates and share a matching full word or an accepted whole-name match with the supporting voter's own name or relation name. Conflicting own-name or relation assignments prevent the attachment.

Prefer own-name evidence over relation evidence, and relation evidence over a same-address household link. Within a connection type, retain the highest name score and preserve tied roster names. Consolidate repeated evidence for the same voter and flat. Unresolved roster status can move a voter to Unassigned.

### 7. Assign strength

A retained mapped link is **Strong** when any of the following applies:

- Its address has explicit apartment-address evidence, including an accepted additional full-word match.
- It belongs to a qualifying corroborated related pair.
- Its flat parses uniquely, at least two other named flats are in the same part and section, and both name scores are at least 75%.

Other retained mapped links are **Medium**. A link admitted only through the guarded 95% fallback is Medium. These rules produce no Needs review mapped rows.

Eligibility, support counts and strength qualifications use the frozen preliminary features. Final resolution can change the displayed connection or supporting voter; strength qualifications are not recalculated from changed scores. Explicit address-only voter records are Strong for their apartment-address evidence.

### 8. Write the output

- `voters_mapped_tohouse` contains surviving voters with resolved roster-flat connections, sorted by flat, roster status, part and serial number. Strength identifies name-linked and household-linked rows. Strong rows are light green and Medium rows light blue, with a dark border between flats.
- `voters_unmapped` shows individual voter records with their original roll addresses and details. The `flat_status` column reads **Roster link unresolved** when a flat is proposed and **Flat unresolved** when the flat fields are blank.
- `not_found_in_voterlist` contains source roster rows without a surviving connection in the resolved output.

On the first sheet, `other_hh_matched_booth` counts all other preliminary candidate flats at the booth. `other_hh_matched_section_in_part` counts all other preliminary candidate flats in the same part and section. `other_named_flats_in_section` counts only other flats with explicit apartment-name addresses and unique flat parses in that same part and section. Each counts distinct flats and excludes the row's own flat.

Every sheet ends with `searched_voter_list`, taken from the configured AC or ward name. Manual review labels are used to evaluate results and do not affect matching decisions.
