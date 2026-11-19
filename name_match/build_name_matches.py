#!/usr/bin/env python3
# Export preliminary apartment name matches using the standard apartment list and voter files.
# Accepts the same arguments as code/build_apartment_matches.py and skips final scoring.
# AUTHOR: Chinmay and AI

import sys
from pathlib import Path

# Reuse the installed repository's matcher and its existing input and output handling.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from build_apartment_matches import main


if __name__ == "__main__":
    main(["--preliminary-only", *sys.argv[1:]])
