# Cross-part family candidate screen

This is an offline exploratory analysis. It does not change or rerun the matcher. It starts with the actual `section2_score0_dominance1` changes in `pipeline_section/pipeline_changes.csv`, the current first sheets, and the historical reviewed candidate workbooks. It only evaluates candidates appearing in those historical workbooks; it cannot detect a candidate that the historical matcher never generated.

For a candidate omitted by the section ≥2 experiment, find an already selected own-name voter at the same apartment and flat in a different polling part. Either person's relationship field must exactly match the other's voter name after name normalization; that matched name must contain at least two space-separated tokens. A stricter version also checks that the complete flat text appears in the candidate's address after punctuation and spaces are stripped. This last check is a quick text approximation, not the matcher's unambiguous flat parser, and it can produce false positives when the string occurs inside another number.

| Additional filter | Apartment | Reviewer Strong / Medium recovered | Reviewer Unlikely / inferred No Match recovered |
| --- | --- | ---: | ---: |
| None | Concorde | 0 | 4 |
| None | Purnima | 1 | 0 |
| None | Silicon | 5 | 0 |
| None | Tirumala | 0 | 0 |
| Complete-flat text | Concorde | 0 | 0 |
| Complete-flat text | Purnima | 1 | 0 |
| Complete-flat text | Silicon | 5 | 0 |
| Complete-flat text | Tirumala | 0 | 0 |

All ten candidates were already on the current first sheet. Thus these are potential recoveries from the selective experiment, not gains over the current algorithm. The Purnima result is still uncertain: its exact relationship and flat text do not settle which building the address refers to. The four lower-rated Concorde rows all concern one flat and use only its numeric portion in the address. Concorde No Match labels were inferred from omissions in a partial review, rather than explicitly rated. The six retained candidates include one of three affected voters in one Silicon family; the other two lack the necessary cross-part exact relation link. Other lost candidates also remain unresolved.

The screen does not model final confidence pruning, changes in dominance, or cascading dependent links. In particular, an accepted relation must still identify its own actual name-matched anchor, and the anchor must itself survive the final rules. An end-to-end rerun would be needed to establish final output counts and whether sheet 2 contains affected voters.

An alternate apartment name already supported through the configuration could improve recognition when a voter address has an accurately supplied alternate name. This test did not assume an apartment-specific alias or automatically infer one. The evidence for and against any proposed alternate name would need to be checked independently.

Reproduce from the project root with `python3 final/experiments/pipeline_precision/inspect_family_exception.py`. The candidate-level CSV contains personal data and is ignored by Git.

## Earlier candidate simulation

`run.py` also explores selection and grading using the historical preliminary candidate snapshots. This reconstruction applies candidate dominance and attempts to reconstruct specific household anchors from available evidence, but cannot reproduce contextual provenance absent from the snapshots. Its section-five union suggested 26 reviewer-supported additions and four lower-rated additions, versus 25 and one in the subsequently verified guarded full-pipeline run. The full run is more reliable; see [the recovery report](../pipeline_recall/README.md).
