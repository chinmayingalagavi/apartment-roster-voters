# Suggest polling booths from apartment-label evidence; inputs are voter DataFrames and an apartment configuration.
# AUTHOR: Chinmay and AI
"""Conservative, apartment-specific polling-booth suggestions for AC searches."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd


# Public report schema and terms that cannot independently identify an apartment.
SUGGESTION_COLUMNS = [
    "station_key", "polling_names", "polling_addresses", "parts", "total_rows", "total_voters",
    "label_voters", "label_addresses", "suggested", "reason",
]
LABEL_FILLER_WORDS = {
    "APT", "APARTMENT", "APARTMENTS", "BLOCK", "FLAT", "NO", "NUMBER",
    "THE", "CITY", "PHASE", "TOWER", "WING",
}
MISSING_VALUES = {"", "NA", "N/A", "NAN", "NONE", "NULL", "-"}


# Normalize repeated text once per distinct value to keep the AC pass inexpensive.
def _text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().upper()
    return "" if text in MISSING_VALUES else text


def _words(value: object) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", _text(value)).split())


def _normalized(series: pd.Series, *, compact: bool = False) -> pd.Series:
    clean = series.fillna("").astype(str)
    cache = {value: _words(value) for value in clean.unique()}
    result = clean.map(cache)
    return result.str.replace(" ", "", regex=False) if compact else result


def _column(voters: pd.DataFrame, name: str) -> pd.Series:
    return voters[name] if name in voters else pd.Series("", index=voters.index, dtype=str)


def station_keys(voters: pd.DataFrame) -> pd.Series:
    """Identify an exact polling-name/address pair, preserving booth and room ids.

    Both fields are used whenever present. A missing field has an explicit prefix;
    rows missing both receive an empty key and can never be suggested. Case,
    punctuation and spacing are normalized, but stations are never fuzzy-merged.
    The caller should compute keys before restricting the voter DataFrame.
    """
    names = _normalized(_column(voters, "pollingname"), compact=True)
    addresses = _normalized(_column(voters, "pollingaddress"), compact=True)
    keys = pd.Series("", index=voters.index, dtype=str, name="station_key")
    both = names.ne("") & addresses.ne("")
    keys.loc[both] = "N:" + names.loc[both] + "|A:" + addresses.loc[both]
    name_only = names.ne("") & addresses.eq("")
    keys.loc[name_only] = "N:" + names.loc[name_only]
    address_only = names.eq("") & addresses.ne("")
    keys.loc[address_only] = "A:" + addresses.loc[address_only]
    return keys


# Strong apartment labels require a compound name, avoiding generic single words.
def strong_apartment_label_mask(
    addresses: pd.Series,
    config: Any,
    *,
    station_keywords: tuple[str, ...] | None = None,
) -> pd.Series:
    """Match compound apartment names/aliases, allowing punctuation and spacing.

    By default the configuration supplies ``apartment_name`` and ``keywords``;
    single-word aliases such as ``classic`` and ``oasis`` are not seed evidence.
    Explicitly curated ``station_keywords`` override that default and may contain
    distinctive single words. This changes booth discovery, not legacy name rules.
    """
    phrases = set()
    inputs = station_keywords if station_keywords is not None else (config.apartment_name, *config.keywords)
    for phrase in inputs:
        normalized = _words(phrase)
        words = normalized.split()
        meaningful = [word for word in words if word not in LABEL_FILLER_WORDS and len(word) >= 2]
        if normalized and (station_keywords is not None or len(meaningful) >= 2):
            phrases.add(normalized)
    if not phrases:
        return pd.Series(False, index=addresses.index, dtype=bool)
    alternatives = [r"\s*".join(re.escape(word) for word in phrase.split()) for phrase in sorted(phrases)]
    pattern = r"(?<!\w)(?:" + "|".join(alternatives) + r")(?!\w)"
    return _normalized(addresses).str.contains(pattern, regex=True, na=False)


# Count independent people and addresses; a duplicated voter must not seed a booth.
def person_keys(voters: pd.DataFrame) -> pd.Series:
    epic = _normalized(_column(voters, "epic_number"), compact=True)
    fallback = pd.Series("", index=voters.index, dtype=str)
    for field in ("part", "serial_number", "name", "house_number"):
        fallback = fallback + "|" + _normalized(_column(voters, field))
    # Completely empty records remain separate rather than counting as one person.
    empty = fallback.eq("||||")
    if empty.any():
        positions = pd.Series(range(len(voters)), index=voters.index).astype(str)
        fallback.loc[empty] = "ROW:" + positions.loc[empty]
    result = "ROW:" + fallback
    result.loc[epic.ne("")] = "EPIC:" + epic.loc[epic.ne("")]
    return result


def _display_values(values: pd.Series) -> str:
    """Retain readable original values while sorting them deterministically."""
    cleaned = {str(value).strip() for value in values.drop_duplicates() if _text(value)}
    return "; ".join(sorted(cleaned, key=lambda value: (value.casefold(), value)))


def suggest_polling_stations(
    voters: pd.DataFrame,
    config: Any,
    *,
    min_voters: int = 3,
    min_addresses: int = 2,
    station_keywords: tuple[str, ...] | None = None,
) -> pd.DataFrame:
    """Report every booth and suggest those with independent label support.

    A suggested booth needs at least ``min_voters`` distinct people explicitly
    naming the apartment, across ``min_addresses`` normalized address strings.
    EPIC ids deduplicate people; part/serial/name/address identify rows without
    EPIC ids. Address counts are a household proxy, not proven unique units.
    No match-count fallback or global-search fallback is performed here.
    """
    if min_voters < 1 or min_addresses < 1:
        raise ValueError("Polling-station evidence thresholds must be positive")
    if voters.empty:
        return pd.DataFrame(columns=SUGGESTION_COLUMNS)

    # Use a fresh internal index so repeated caller index labels cannot affect grouping.
    work = pd.DataFrame({
        "station_key": station_keys(voters).to_numpy(),
        "person_key": person_keys(voters).to_numpy(),
        "house_key": _normalized(_column(voters, "house_number"), compact=True).to_numpy(),
        "label": strong_apartment_label_mask(
            _column(voters, "house_number"), config, station_keywords=station_keywords,
        ).to_numpy(),
        "pollingname": _column(voters, "pollingname").to_numpy(),
        "pollingaddress": _column(voters, "pollingaddress").to_numpy(),
        "part": _column(voters, "part").to_numpy(),
    })
    # Conflicting copies of one voter across booths are not independent station
    # evidence. Preserve the input rows, but abstain from using them as seeds.
    conflicts = work.loc[work["station_key"].ne("")].groupby("person_key")["station_key"].nunique().gt(1)
    ambiguous_people = set(conflicts.index[conflicts])
    work["label"] &= ~work["person_key"].isin(ambiguous_people)
    records = []
    for key, group in work.groupby("station_key", sort=True, dropna=False):
        labeled = group.loc[group["label"]].sort_values(
            ["person_key", "house_key"],
        ).drop_duplicates("person_key")
        label_voters = int(labeled["person_key"].nunique())
        label_addresses = int(labeled.loc[labeled["house_key"].ne(""), "house_key"].nunique())
        suggested = bool(key and label_voters >= min_voters and label_addresses >= min_addresses)
        reasons = []
        if not key:
            reasons.append("missing_station_metadata")
        if label_voters < min_voters:
            reasons.append("insufficient_label_voters")
        if label_addresses < min_addresses:
            reasons.append("insufficient_label_addresses")
        records.append({
            "station_key": key,
            "polling_names": _display_values(group["pollingname"]),
            "polling_addresses": _display_values(group["pollingaddress"]),
            "parts": _display_values(group["part"]),
            "total_rows": int(len(group)),
            "total_voters": int(group["person_key"].nunique()),
            "label_voters": label_voters,
            "label_addresses": label_addresses,
            "suggested": suggested,
            "reason": "apartment_label_evidence" if suggested else ";".join(reasons),
        })
    return pd.DataFrame.from_records(records, columns=SUGGESTION_COLUMNS).sort_values(
        ["suggested", "label_voters", "label_addresses", "station_key"],
        ascending=[False, False, False, True],
    ).reset_index(drop=True)
