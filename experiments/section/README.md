# Section and booth grading experiment

The script compares simple geographical-support thresholds with manually reviewed,
pre-scoring voter-to-flat candidate rows. Run from the project root using
`python3 final/experiments/section/section_thresholds.py`.

- `manual_row_features.csv` records the input judgments and calculated support.
- `section_threshold_summary.csv` compares flat and voter counts at different thresholds.
- `grading_confusion.csv` contains the three-tier confusion tables for the two fixed rules.

Counts are calculated per apartment over all candidate flat assignments in that
apartment's original pre-scoring workbook. For each candidate, *other* excludes
all rows linked to its own flat. Section count groups identical nonblank
`section_raw` text across parts. A second count groups by part and section.
Booth count groups by part and polling station. Voter counts are candidate row
counts and can count multiple candidates or relatives, not distinct people.
Blank sections get zero section support. Full name in address requires the
configured primary apartment name, matched after punctuation and case normalization.

Manual Strong/Medium are treated as positive and Unlikely/No Match as negative
for the binary precision/recall summaries. Human Unlikely is not a confirmed
false match. Some Purnima and Tirumala address-only Unassigned rows are excluded
because this analysis uses mapped candidate rows.

Concorde review preserves 226 labeled rows and has 502 completely blank rows.
All source row values aside from strength are unique, and all 226 labeled rows
match their original source tuple exactly. The agent's report says 502 rows were
No Match. This experiment infers No Match for the 502 absent source rows. It is
a reconstruction and should be presented separately when possible.

The three-tier section example is Strong when the address names the apartment
or the section has at least 10 other candidate flats, Medium when the section
has at least 3 other candidate flats and name score at least 95, Weak otherwise.
The booth comparison is Strong when the address names the apartment or the booth
has at least 5 other candidate flats, Medium when it has at least 3, Weak otherwise.

This is exploratory in-sample analysis. The candidates are from older pre-scoring
workbooks and differ from today's dominance filtering, anchor cutoffs and
grey-row suppression. The judgments are not independently verified residences
and reviewers considered geographic evidence, so section-based results may be
circular. Many candidates share voter households. Candidate counts may include
false positives and can differ from the current algorithm's frozen pre-pruning
booth count. Thresholds chosen using these same apartments lack held-out
validation. Grading existing rows does not recover a real match omitted entirely
by candidate generation.
