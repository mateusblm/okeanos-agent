#!/usr/bin/env python3
"""Okeanos deterministic hooks: entry point.

  okeanos.py [--agent NAME] <hook>   read the agent's hook payload on stdin, answer in its format
  okeanos.py metrics [days]          event counts for the current repo

The rules live in okeanos_engine/rules.py and know nothing about agents; each agent's
payload and output format live in okeanos_engine/dialects/<agent>.py (default: claude).
Stdlib only. Every failure degrades to "allow": a broken hook must not block work.
"""

import os
import sys

sys.dont_write_bytecode = True  # keep the plugin directory clean
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    try:
        from okeanos_engine.cli import main
    except Exception:  # noqa: BLE001
        sys.exit(0)
    sys.exit(main())
