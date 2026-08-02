"""Launcher for OathWatch.

Keeps the documented ``python bot.py`` entry point working; the real bot
lives in the ``oathwatch`` package (``oathwatch.bot.main``).
"""
import sys

from oathwatch.bot import main

if __name__ == "__main__":
    sys.exit(main())
