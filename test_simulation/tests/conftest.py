import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "test_simulation") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "test_simulation"))
if str(ROOT_DIR / "bridge") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "bridge"))

