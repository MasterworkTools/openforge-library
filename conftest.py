"""Puts the repository root on the path so `openforge_library` imports.

There is no install step: the scanner is run from a checkout, by the
tools in bin/, so the tests import it the same way they do.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
