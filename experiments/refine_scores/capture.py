# Capture the first resolved candidate pool once per apartment for repeatable selection trials.
# Inputs are the configured voter list and apartment rosters, plus the current matcher.
# AUTHOR: Chinmay and AI

import pickle
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipeline_section"))
from run_pipeline import load_apartment, matcher, run_baseline


def main():
    destination = HERE / "generated"
    destination.mkdir(exist_ok=True)
    configs, voter_file, list_name = matcher._load_apartment_run_config(matcher.DEFAULT_APARTMENTS_CSV)
    selected = sys.argv[1:] or configs
    for key in selected:
        print(f"Capturing {key}", flush=True)
        config = configs[key]
        roster_rows, roster, voters = load_apartment(config, voter_file)
        captured, baseline = run_baseline(config, roster_rows, roster, voters)
        # The snapshot contains private voter data and is trusted local input only.
        staged = destination / f"{key}.tmp"
        with staged.open("wb") as handle:
            pickle.dump((captured, baseline, list_name), handle, protocol=pickle.HIGHEST_PROTOCOL)
        staged.replace(destination / f"{key}.pickle")
        print(f"Captured {key}: {len(captured['initial'])} candidates, {len(baseline)} current first-sheet links", flush=True)


if __name__ == "__main__":
    main()
