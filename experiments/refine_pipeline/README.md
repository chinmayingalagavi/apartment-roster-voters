# Revised apartment matcher experiment

The same rules run on every apartment. This experiment changes candidate generation, candidate selection, and grading. The production matcher is separate. All reported totals count voter-to-flat links on the first sheet.

## Recommended rule

1. Generate preliminary candidates with the current matcher. Add a direct name candidate when the voter address explicitly names the apartment and parses to exactly one roster flat, and all of the full words of either name occur in the other name, with at least two distinct full words on each side. Require a unique available roster person and an uncontested claim. Reject the proposed own-name link if the voter's relation name also matches that roster person by the full-word rule.
2. Keep preliminary voter-to-flat candidates through any of the following routes:
   - The voter address names the apartment.
   - A **different flat** has an explicitly named and fully parsed address in the same polling part and exact nonblank `section_raw`. The candidate's own flat must parse uniquely to the proposed flat, or its name score and supporting voter score must both be at least 80. Named section flats are counted from the initial pool, including address-only records whose flat parses uniquely.
   - Two voters independently match distinct roster names at the proposed flat, both addresses parse to that flat, and one voter is named as the other's relation. The existing corroboration rule must find the pair unambiguous.
   - A direct own-name match is 100% with multiple name words, a uniquely parsed flat, and no unexplained address text after parsing.
3. Apply the existing competition rules, including `name_match_pct` and booth support, and rerun the resolver so dependent links require an eligible own-name voter attached to the same flat. A relation link must identify the actual supporting voter. The extra direct name candidates enter this resolver and can support existing address-only candidates at their flat.
4. Mark a mapped link Strong if its address names the apartment, it is part of a qualifying relation pair, or its flat parses uniquely, there are at least two other named flats in its section and polling part, and both its name and supporting voter scores are at least 75. Other kept links are Medium. Address-only voters and households whose connection cannot be established go to the existing second sheet under its usual rules.

## Results

The historical benchmark contains 727 Strong or Medium links and 1,286 Unlikely or No Match links from agent review. Concorde's No Match labels are inferred from rows omitted during its review. The results are first-sheet links from complete three-sheet workbooks. The first preliminary matcher run read the full constituency voter list and rosters, and the experiment reused its cached evidence to rerun the resolver under different rules.

| Apartment | Current supported | Current lower-rated | Revised supported | Revised lower-rated | Outside benchmark |
| --- | ---: | ---: | ---: | ---: | ---: |
| Concorde | 191 | 136 | 198 | 3 | 0 |
| Purnima | 3 | 52 | 0 | 0 | 0 |
| Silicon Oasis | 461 | 60 | 476 | 0 | 4 |
| Tirumala Vintage | 40 | 73 | 42 | 5 | 0 |
| Total | 695 | 321 | 716 | 8 | 4 |

The revised rule adds 27 supported links and three lower-rated links from the benchmark and removes six supported and 316 lower-rated links. Four additional links were outside the benchmark and looked plausible on manual review: three direct name links and a relation to one of those directly matched voters. All four have an explicitly named apartment and complete flat in the roll. They are counted separately above. One lost supported Tirumala link still appears as Unassigned on sheet 2 when the related voter is excluded. Purnima has one address-only row on sheet 2 and no mapped links under this rule.

| Trial and evidence used to select links | Supported | Lower-rated | Outside benchmark |
| --- | ---: | ---: | ---: |
| Current matcher | 695 | 321 | 0 |
| Two other preliminary candidate flats in the same section | 712 | 81 | 0 |
| Named section alone after resolver | 710 | 14 | 0 |
| Revised rules without the 80% requirement for ambiguous flats | 717 | 14 | 4 |
| Revised rules with the 80% requirement for ambiguous flats | 716 | 8 | 4 |

In the recommended output, Strong includes 617 supported and two lower-rated benchmark links, plus the four links outside the benchmark. Medium includes 99 supported and six lower-rated links. The eight remaining lower-rated links include candidates where the flat number also exists elsewhere or the voter address seems to name a different development, and members inherited through weak evidence from a common name word. A different development name may require address evidence beyond this rule. Added lower-rated links are all graded Medium.

All four workbooks were reopened and checked for the three expected sheets, the searched voter list, unique link keys, and agreement with the benchmark on voter ID and polling part where a comparison exists. For all 24 relation and 28 other household links in the workbooks, a compatible visible own-name voter shares the flat and roster connection. The existing resolver enforces the actual relation or household connection before writing; the workbook audit independently checks the visible evidence.

The benchmark was used to refine these rules. Its labels are judgments based on the records, including geographic evidence, rather than independently verified residences. Related voters share evidence, and the first-pass benchmark cannot label every person in the voter list. These results describe the four tested apartments.

## Reproduce

From `final/`, with the configured data and the local reviewer benchmarks available:

```sh
python3 experiments/refine_scores/capture.py
python3 experiments/refine_pipeline/finalists.py --expand --write --score-floor 0 80
```

The recommended results are in `experiments/refine_pipeline/generated/named_section_80_expanded/`. Local caches and row-level outputs contain private data and are Git ignored. Load experiment caches only if generated locally by the capture script.

## 95% name score follow-up

The follow-up reran the actual resolver from the same captures. It added each fallback to the recommended rule, kept the full-word expansion, and compared mapped link keys against the 716 supported, eight lower-rated, and four unreviewed links above. Every variant retained all those links. Each cutoff includes 95 exactly and requires both the displayed name score and the supporting voter's name score to reach it.

| Extra fallback | Supported added | Lower-rated added |
| --- | ---: | ---: |
| 95% alone | 4 | 86 |
| 95% and no leftover address text | 1 | 75 |
| Lower the isolated 100% rule to 95%, retaining a clear flat and multiword own name | 0 | 1 |
| 95% and another explicitly named, unambiguous flat in the same exact section text, including across polling parts | 3 | 7 |
| Same section rule, but require an own-name match with at least two name tokens when the flat is ambiguous | 3 | 0 |

The guarded section variant adds two Purnima own-name links and one Silicon Oasis relation link. Initials count as name tokens in this variant. Supporting addresses must name the apartment and uniquely parse to a different flat. All three additions are graded Medium. The Purnima name evidence is plausible; the abbreviated addresses leave their building uncertain. In the broad fallback, many lower-rated links came from exact matches to a single common name combined with a reused flat number. The stricter section rule is promising for a review list, with very few independent positive examples in this benchmark.

```sh
python3 experiments/refine_pipeline/finalists.py --expand --compare-95
```
