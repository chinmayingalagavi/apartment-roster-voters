# Section evidence from addresses naming the apartment

Use other flats whose voter addresses explicitly name the apartment, instead of counting every preliminary candidate flat as equivalent evidence. The same rules apply to every apartment. This experiment changes which voter–flat links survive from the first resolved candidate pool, then calls the current resolver with the selected links so the existing household anchor and competition rules still apply.

The base selection keeps a candidate if its own address names the apartment, or if there is **one other flat** with an address that both names the apartment and parses to exactly that flat. The other flat must be in the same polling part and the same nonblank `section_raw`. A named voter who is unassigned by roster name can supply location evidence. A flat never counts as evidence for itself.

The family option also retains a pair of independently name-matched voters who match distinct roster people at the same flat. The current matcher must find the pairing unambiguous and one voter's recorded relation must identify the other voter. The guarded version requires both voters' addresses to parse to that flat. The exact-name option adds a fallback for a direct match with `name_match_pct == 100`, a name of at least two words, a uniquely parsed matching flat and no long unexplained address text.

| Selection after the resolver | Reviewer Strong or Medium | Reviewer Unlikely or No Match |
| --- | ---: | ---: |
| Current first sheet | 695 | 321 |
| Own named apartment or another named flat in section | 710 | 14 |
| Add corroborated relation pair | 715 | 15 |
| Require a complete parsed flat for each voter in a rescued pair | 715 | 14 |
| Add complete flat and exact full-name fallback | 717 | 15 |
| Require a complete flat or `name_match_pct >= 95` for section-only candidates | 713 | 9 |
| Require a complete flat for all section-only candidates | 701 | 9 |
| Require a complete flat and no long unexplained address for section-only candidates | 662 | 8 |
| Instead allow a complete-flat dependent with an eligible own-name anchor to remain even without section support | 718 | 20 |
| Allow another named seed flat across polling parts when section text matches and the candidate has a complete flat | 718 | 17 |
| Rescue a unique complete-flat own-name anchor identified by a complete-flat voter with a named apartment address | 718 | 16 |

The 717/15 variant has 27 supported links gained and five lost versus the current first sheet. Its gains by apartment are eight Concorde, zero Purnima, sixteen Silicon Oasis, and three Tirumala. The five losses are one Silicon Oasis, one Tirumala, and three Purnima. All 27 gains parse to the proposed complete flat, although some have a name score below 50. The stricter 713/9 variant retains all 27 gains and removes four more supported links from the current output. Its six fewer lower-rated links include five Silicon links whose addresses lack a complete unit designation. The permissive complete-flat dependent rule recovers only one extra supported link and adds five lower-rated links.

For the 717/15 variant, grade a retained link Strong when its address explicitly names the apartment, it belongs to a guarded corroborated relation pair, or it parses to the complete flat and shares its part and section with two other named-address flats. This gives 688 supported and 6 lower-rated Strong links, and 29 supported and 9 lower-rated Medium links. Adding `name_match_pct >= 75` only to the last Strong path gives 617 supported and 2 lower-rated Strong links, and 100 supported and 13 lower-rated Medium links. These are grades evaluated on the resolved sets.

From `final/`, run `python3 experiments/refine_scores/capture.py` to capture fresh preliminary evidence from the input files, then `python3 experiments/refine_seeds/live_rule.py` and `python3 experiments/refine_seeds/grade_audit.py`. `seed_sweep.py` runs a quicker approximation using older spreadsheet snapshots. It reconstructs anchor and competition rules, so its counts may differ slightly from the fresh resolver. The local CSV results and capture files are ignored by Git. The resolver trials measure mapped links before workbook formatting, and review labels cover historical preliminary links only. The reviewers used location evidence and the rules were chosen on these same apartments.
