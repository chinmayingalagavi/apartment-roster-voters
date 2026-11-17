# Candidate name scores and address support

These trials reuse the current preliminary candidate generator and test uniform candidate-selection rules. The snapshots contain private voter records and must stay local. Do not load snapshots from anyone else. The current matcher is imported and is not edited.

From `final/`:

```sh
python3 experiments/refine_scores/capture.py
python3 experiments/refine_scores/features.py
python3 experiments/refine_scores/sweep.py
python3 experiments/refine_scores/sweep.py --resolve 'exact_flats:5/3+70/pair'
```

The initial sweep screens candidates before resolver decisions. `--resolve` runs the existing dominance and own-name anchor checks and compares the resulting mapped links against the current first sheets. These results are candidate counts after resolving, before a specific new grading policy. Strong/Medium reviewer ratings count as supported and Unlikely/No Match count as lower-rated. The 727 supported and 1,286 lower-rated reviewed links come from earlier preliminary candidate workbooks. This is the same dataset used to compare variants; these counts do not estimate performance on a new development.

The four types of section support count distinct other flats in the same polling part and nonblank exact section. The pools are all candidate flats, uniquely parsed candidate flats, candidate flats with explicitly named addresses, or candidate flats whose address names the apartment or that have a uniquely parsed flat and a direct multiword name score of at least 90. Counts are computed before filtering. An exact-address link is independently eligible.

| Candidate rule after resolution | Supported | Lower-rated |
| --- | ---: | ---: |
| Current first sheet | 695 | 321 |
| Two other candidate flats | 712 | 81 |
| Five other candidate flats, or two with both name and linked voter score at least 90 | 707 | 24 |
| Three other uniquely parsed candidate flats, or an unambiguous corroborated pair | 714 | 13 |
| Five other uniquely parsed candidate flats, or three with both scores at least 70, or a corroborated pair | 714 | 11 |
| Previous rule plus an exact multiword own-name hit at an unambiguously parsed flat | 716 | 12 |

The five-or-three rule gained 26 supported links and lost 7, while gaining one lower-rated link and losing 311. The 70 score floor removed two lower-rated links without changing the supported count relative to the simpler three-flat rule, but adding a 90 floor to the original broad section rule lost some good candidates. The address parser can resolve a bare number to one unit even if several nearby developments use the same number, so unique parsing is supporting evidence whose value varies with the actual address.

`audit_named.py` re-runs a separate named-section trial in `../refine_seeds/`. Its local CSV records which eligibility route each final link used. `--guards` checks how tentative fixes change the mapped sheet after the resolver runs again.

That trial originally returned 717 supported and 15 lower-rated links. Fourteen of the lower-rated links entered solely through a neighboring flat whose address names the apartment. Six had an ambiguous candidate flat number, including an address of only one digit. One other lower-rated link entered through a 100% full-name fallback; the parser assigned its number to a roster flat while leaving an unexplained block letter.

| Named-section trial | Supported | Lower-rated |
| --- | ---: | ---: |
| Initial named-section, pair and exact full-name trial | 717 | 15 |
| Require no unexplained address text on the exact full-name fallback | 717 | 14 |
| Also require both scores ≥80 when a section-supported candidate's flat is ambiguous | 716 | 8 |
| Also require clearer relation evidence for same-address household links | 702 | 6 |

The tighter household test replaced a shared word as the only link with a voter-relative name match or an exact match of the two voters' listed relative names. It removed two flagged links linked through a common word, but lost many reviewer-supported household links.
