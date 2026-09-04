"""Repository-root wrapper for the TASK-05 handoff validator."""

from __future__ import annotations

from pathlib import Path

from glyph_features.workbench.handoff import HANDOFF_RELATIVE_PATH, validate_handoff


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors = validate_handoff(ROOT / HANDOFF_RELATIVE_PATH, ROOT)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("TASK-05 handoff valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())