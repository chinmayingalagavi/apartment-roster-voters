# Test AC relative-name preparation, booth discovery, and matching using synthetic voters and temporary apartment roster/configuration CSVs.
# AUTHOR: Chinmay and AI
"""Behavioral regressions for station discovery, overrides and collision filtering."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd


# Import the implementation from this repository, regardless of its folder name.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import ac_matching as ac
import build_apartment_matches as runner
import polling_stations as stations
import prepare_voters
import ward


class PollingStationSafetyTests(unittest.TestCase):
    def test_explicit_ac_relationship_prefixes_are_split_without_guessing(self) -> None:
        for label, expected in [("Fathers Name", "Father"), ("Husband's Name", "Husband"), ("Mothers Name", "Mother"), ("Others", "Other")]:
            with self.subTest(label=label):
                self.assertEqual(prepare_voters.parse_relative_label(f"{label}: Carlos Mendes"), (expected, "Carlos Mendes"))

    def test_unknown_and_plain_relative_names_are_preserved(self) -> None:
        self.assertEqual(prepare_voters.parse_relative_label("Carlos Mendes"), ("", "Carlos Mendes"))
        self.assertEqual(prepare_voters.parse_relative_label("Unknown: Carlos Mendes"), ("", "Unknown: Carlos Mendes"))
        self.assertEqual(prepare_voters.parse_relative_label(None), ("", ""))
        self.assertEqual(prepare_voters.parse_relative_label("Fathers Name: "), ("Father", ""))

    def test_parsed_ac_relative_field_restores_relation_matching(self) -> None:
        self.write_roster([("103", "Carlos")])
        raw = "Fathers Name: Carlos Mendes"
        voters = self.voters([self.voter("Unlisted Person", "103", "RELATIVE", relation=raw)])
        self.assertTrue(ac.match_rows(voters, self.roster, self.config).empty)
        kind, relative = prepare_voters.parse_relative_label(raw)
        voters.loc[:, "relation_type"], voters.loc[:, "relation_name"] = kind, relative
        matched = ac.match_rows(voters, self.roster, self.config)
        self.assertEqual(len(matched), 1)
        self.assertIn("relation_name_match", matched.loc[0, "voter_link_type"])

    def test_multiple_unit_review_handles_missing_nullable_scores(self) -> None:
        rows = pd.DataFrame({
            "epic_number": ["CONFLICT", "CONFLICT", "DUP", "DUP", "UNMAPPED"],
            "apartment_unit": ["101", "102", "101", "101", ""],
            "part_name_match": pd.array([pd.NA, 100, 90, 90, pd.NA], dtype="Int64"),
        })
        reviewed = ac.multiple_unit_rows(rows)
        self.assertEqual(reviewed["epic_number"].tolist(), ["CONFLICT", "CONFLICT"])
        self.assertEqual(str(reviewed["part_name_match"].dtype), "Int64")
        self.assertTrue(pd.isna(rows.loc[0, "part_name_match"]))

    # Synthetic files exercise the real roster/configuration loading path.
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="apartments_v6_test_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.roster_path = self.root / "roster.csv"
        self.config_path = self.root / "apartments.csv"
        self.config = ward.ApartmentConfig(
            key="sample", apartment_name="Cedar Heights", roster_path=self.roster_path,
            keywords=("cedar heights", "cedar", "heights", "classic", "oasis"),
        )
        pd.DataFrame([{
            "key": self.config.key, "apartment_name": self.config.apartment_name,
            "roster_path": str(self.roster_path), "keywords": ";".join(self.config.keywords),
            "extra_filler_terms": "",
        }]).to_csv(self.config_path, index=False)
        self.write_roster([("101", "Alice Smith"), ("102", "Bhavana Rao"), ("103", "Carlos Mendes")])
        self.args = argparse.Namespace(
            min_label_voters=3, min_label_addresses=2, min_match_units=3,
            station_evidence="labels-first", apartments_csv=self.config_path,
        )

    def write_roster(self, pairs: list[tuple[str, str]]) -> None:
        pd.DataFrame([{
            "apartment_key": "sample", "unit": unit, "block": "", "unit_part": unit,
            "name": name, "status": "Owner",
        } for unit, name in pairs]).to_csv(self.roster_path, index=False)
        self.roster = ward.load_roster(self.config)

    def voter(
        self, name: str, house: str, epic: str, *, serial: int = 1, part: int = 1,
        pollingname: str = "1 - North School Room No 1",
        pollingaddress: str = "North School Main Road", relation: str = "",
    ) -> dict[str, object]:
        return {
            "serial_number": serial, "epic_number": epic, "name": name,
            "relation_type": "FTHR", "relation_name": relation, "house_number": house,
            "age": 40, "gender": "F", "section_raw": "Test section", "part": part,
            "ward": "Test ward", "corporation": "Test corporation", "pincode": "560001",
            "pollingname": pollingname, "pollingaddress": pollingaddress,
        }

    def voters(self, rows: list[dict[str, object]]) -> pd.DataFrame:
        result = pd.DataFrame(rows)
        result["_row_id"] = range(len(result))
        return result

    def choose(self, voters: pd.DataFrame, overrides: pd.DataFrame | None = None):
        return runner.station_selection(voters, self.roster, self.config, self.args, overrides)

    def override(self, rows: list[dict[str, object]]) -> pd.DataFrame:
        path = self.root / "stations.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return runner.read_station_override(path, {"sample"})

    # Discovery must not turn common apartment words or duplicate records into evidence.
    def test_generic_single_keywords_cannot_bootstrap_a_station(self) -> None:
        voters = self.voters([
            self.voter("Unlisted Person", f"{unit} Classic Oasis", f"GEN{unit}", serial=index)
            for index, unit in enumerate([101, 102, 103], 1)
        ])
        report, mask = self.choose(voters)
        self.assertEqual(int(report["label_voters"].sum()), 0)
        self.assertFalse(report["selected"].any())
        self.assertFalse(mask.any())

    def test_duplicate_epic_cannot_inflate_label_voters_or_addresses(self) -> None:
        voters = self.voters([
            self.voter("Unlisted Person", f"{unit} Cedar Heights", "DUPLICATE", serial=index)
            for index, unit in enumerate([101, 102, 103], 1)
        ])
        report = stations.suggest_polling_stations(voters, self.config)
        self.assertEqual(report.loc[0, "label_voters"], 1)
        self.assertEqual(report.loc[0, "label_addresses"], 1)
        self.assertFalse(report.loc[0, "suggested"])

    def test_room_pairs_stay_separate_and_missing_metadata_never_selects(self) -> None:
        rows = [self.voter("Unlisted Person", f"{unit} Cedar Heights", f"A{unit}", serial=i)
                for i, unit in enumerate([101, 102, 103], 1)]
        rows.append(self.voter("Unlisted Person", "101", "B101", serial=4, part=2,
                               pollingname="2 - North School Room No 2"))
        rows.extend(self.voter("Unlisted Person", f"{unit} Cedar Heights", f"M{unit}", serial=i,
                               pollingname="", pollingaddress="")
                    for i, unit in enumerate([101, 102, 103], 5))
        voters = self.voters(rows)
        keys = stations.station_keys(voters)
        self.assertNotEqual(keys.iloc[0], keys.iloc[3])
        self.assertEqual(keys.iloc[-1], "")
        report, mask = self.choose(voters)
        self.assertEqual(int(report["selected"].sum()), 1)
        self.assertEqual(int(mask.sum()), 3)
        self.assertFalse(report.loc[report["station_key"].eq(""), "selected"].any())

    def test_conflicting_duplicate_epic_cannot_bootstrap_label_stations(self) -> None:
        rows = []
        for booth in [1, 2]:
            for index, unit in enumerate([101, 102, 103], 1):
                epic = "CONFLICT" if unit == 101 else f"BOOTH{booth}UNIT{unit}"
                rows.append(self.voter("Unlisted Person", f"{unit} Cedar Heights", epic,
                                       serial=index, part=booth,
                                       pollingname=f"{booth} - North School Room No {booth}"))
        report, mask = self.choose(self.voters(rows))
        self.assertEqual(report["label_voters"].tolist(), [2, 2])
        self.assertFalse(mask.any())

    # Match clusters need independent exact full names at multiple globally unique units.
    def test_exact_cluster_needs_three_distinct_units(self) -> None:
        rows = [self.voter(name, unit, f"EX{unit}", serial=i)
                for i, (unit, name) in enumerate([("101", "Alice Smith"), ("102", "Bhavana Rao")], 1)]
        report, mask = self.choose(self.voters(rows))
        self.assertEqual(int(report["exact_match_units"].sum()), 2)
        self.assertFalse(mask.any())
        rows.append(self.voter("Carlos Mendes", "103", "EX103", serial=3))
        report, mask = self.choose(self.voters(rows))
        self.assertEqual(int(report["exact_match_units"].sum()), 3)
        self.assertEqual(int(report["label_voters"].sum()), 0)
        self.assertTrue(mask.all())

    def test_mononym_relation_and_fuzzy_names_cannot_seed_matches(self) -> None:
        voters = self.voters([
            self.voter("Alicia Smith", "101", "FUZZY", serial=1),
            self.voter("Bhavana", "102", "MONONYM", serial=2, relation="Bhavana Rao"),
            self.voter("Unknown Person", "103", "RELATION", serial=3, relation="Carlos Mendes"),
        ])
        report, mask = self.choose(voters)
        self.assertEqual(int(report["exact_match_voters"].sum()), 0)
        self.assertFalse(mask.any())

    def test_duplicate_epic_cannot_claim_several_exact_units(self) -> None:
        voters = self.voters([
            self.voter(name, unit, "SAMEEPIC", serial=i)
            for i, (unit, name) in enumerate([("101", "Alice Smith"), ("102", "Bhavana Rao"), ("103", "Carlos Mendes")], 1)
        ])
        report, mask = self.choose(voters)
        self.assertEqual(int(report["exact_match_units"].sum()), 0)
        self.assertFalse(mask.any())

    def test_exact_roster_name_shared_across_units_cannot_seed_station(self) -> None:
        self.write_roster([("101", "Ravi Kumar"), ("102", "Ravi Kumar"), ("103", "Ravi Kumar")])
        voters = self.voters([
            self.voter("Ravi Kumar", str(unit), f"COMMON{unit}", serial=i)
            for i, unit in enumerate([101, 102, 103], 1)
        ])
        report, mask = self.choose(voters)
        self.assertEqual(int(report["exact_match_units"].sum()), 0)
        self.assertFalse(mask.any())

    def test_conflicting_duplicate_epic_does_not_seed_either_station(self) -> None:
        rows = []
        for booth in [1, 2]:
            for index, (unit, name) in enumerate([("101", "Alice Smith"), ("102", "Bhavana Rao"), ("103", "Carlos Mendes")], 1):
                epic = "CONFLICT" if unit == "101" else f"BOOTH{booth}UNIT{unit}"
                rows.append(self.voter(name, unit, epic, serial=index, part=booth,
                                       pollingname=f"{booth} - North School Room No {booth}"))
        report, mask = self.choose(self.voters(rows))
        self.assertEqual(report["exact_match_units"].tolist(), [2, 2])
        self.assertFalse(mask.any())

    def test_label_priority_does_not_expand_into_exact_only_station(self) -> None:
        rows = [self.voter("Unlisted Person", f"{unit} Cedar Heights", f"LABEL{unit}", serial=i)
                for i, unit in enumerate([101, 102, 103], 1)]
        rows.extend(self.voter(name, unit, f"EXACT{unit}", serial=i, part=2,
                               pollingname="2 - South School Room No 1", pollingaddress="South School Far Road")
                    for i, (unit, name) in enumerate([("101", "Alice Smith"), ("102", "Bhavana Rao"), ("103", "Carlos Mendes")], 1))
        voters = self.voters(rows)
        report, mask = self.choose(voters)
        self.assertTrue(report["match_suggested"].any())
        self.assertEqual(int(mask.sum()), 3)
        self.args.station_evidence = "either"
        _, expanded = self.choose(voters)
        self.assertEqual(int(expanded.sum()), 6)

    # End-to-end behavior isolates geographic filtering from the unchanged ward rules.
    def test_unsupported_ac_search_abstains_even_when_ward_would_match(self) -> None:
        voters = self.voters([self.voter("Alice Smith", "101", "ONLY_MATCH")])
        _, mask = self.choose(voters)
        self.assertFalse(mask.any())
        self.assertTrue(ac.match_rows(voters.loc[mask], self.roster, self.config).empty)
        original = ac.match_rows(voters, self.roster, self.config)
        self.assertIn("ONLY_MATCH", set(original["epic_number"]))

    def test_station_restriction_excludes_unrelated_name_and_unit_collision(self) -> None:
        rows = [self.voter("Unlisted Person", f"{unit} Cedar Heights", f"SEED{unit}", serial=i)
                for i, unit in enumerate([101, 102, 103], 1)]
        rows.extend([
            self.voter("Alice Smith", "101", "IN_APARTMENT_AREA", serial=4),
            self.voter("Alice Smith", "101", "ELSEWHERE_COLLISION", serial=1, part=2,
                       pollingname="2 - South School Room No 1", pollingaddress="South School Far Road"),
        ])
        voters = self.voters(rows)
        _, mask = self.choose(voters)
        restricted = ac.match_rows(voters.loc[mask], self.roster, self.config)
        original = ac.match_rows(voters, self.roster, self.config)
        self.assertIn("ELSEWHERE_COLLISION", set(original["epic_number"]))
        self.assertNotIn("ELSEWHERE_COLLISION", set(restricted["epic_number"]))
        self.assertIn("IN_APARTMENT_AREA", set(restricted["epic_number"]))

    def test_indexed_candidates_preserve_original_outputs_across_match_paths(self) -> None:
        self.write_roster([
            ("101", "Alice Smith"), ("102", "Bhavana Rao"),
            ("103", "Carlos Mendes"), ("10191", "Farah Siddiqui"),
        ])
        # Conflicting status groups exercise collapse behavior after row selection.
        conflict = self.roster.loc[self.roster["unit"].eq("101")].copy()
        conflict["_roster_row_id"] = len(self.roster)
        for column in ["status", "group_value", "group_label"]:
            conflict[column] = "Tenant"
        self.roster = pd.concat([self.roster, conflict], ignore_index=True)
        voters = self.voters([
            self.voter("Alice Smith", "101", "DIRECT", serial=1),
            self.voter("Emily Smith", "101", "HOUSEHOLD", serial=2),
            self.voter("Unknown Person", "102", "RELATION", serial=3, relation="Bhavana Rao"),
            self.voter("Unlisted Resident", "103 Cedar Heights", "ADDRESS_ONLY", serial=4),
            self.voter("Lost Resident", "Cedar Heights", "UNMAPPED", serial=5),
            self.voter("Farah Siddiqui", "10 19 1 Cedar Heights", "LONG_NUMBER", serial=6),
            self.voter("Unrelated Resident", "999", "NO_MATCH", serial=7),
        ])
        prepared = ward.matcher.assign_households(ward.build_address_fields(voters, self.roster, self.config))
        # Membership scans tolerate a repeated unit; the index must not duplicate its row.
        for index in prepared.index:
            units = prepared.at[index, "identity_candidate_units"]
            prepared.at[index, "identity_candidate_units"] = units + units
        prepared.index = range(100, 100 + 2 * len(prepared), 2)
        roster_groups = ward.roster_by_unit_group(self.roster)
        original = ward.build_apartment_voter_rows(prepared, self.roster, roster_groups, self.config)
        indexed = ward.build_apartment_voter_rows(
            prepared, self.roster, roster_groups, self.config, indexed_candidates=True,
        )
        self.assertIn("Unmapped", set(original["apartment_status"]))
        self.assertIn("ADDRESS_ONLY", set(original["epic_number"]))
        self.assertIn("LONG_NUMBER", set(original["epic_number"]))
        self.assertEqual(original.loc[original["epic_number"].eq("DIRECT"), "apartment_status"].iloc[0], "Unassigned")
        pd.testing.assert_frame_equal(original, indexed)

    # Reviewed overrides are explicit inputs and must reject contradictory selections.
    def test_override_rejects_invalid_flags_and_duplicate_entries(self) -> None:
        for rows in [
            [{"apartment_key": "sample", "station_key": "some-key", "selected": "perhaps"}],
            [{"apartment_key": "sample", "station_key": "some-key", "selected": True},
             {"apartment_key": "sample", "station_key": "some-key", "selected": False}],
            [{"apartment_key": "not-configured", "station_key": "some-key", "selected": True}],
        ]:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.override(rows)

    def test_override_rejects_blank_or_unknown_selected_stations(self) -> None:
        voters = self.voters([self.voter("Alice Smith", "101", "ONE")])
        for key in ["", "NOT_A_STATION_IN_THIS_ROLL"]:
            overrides = self.override([{"apartment_key": "sample", "station_key": key, "selected": True}])
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.choose(voters, overrides)


if __name__ == "__main__":
    unittest.main()
