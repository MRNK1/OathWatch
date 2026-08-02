"""Entry point for ``python -m oathwatch``."""
import sys

from .bot import main

if __name__ == "__main__":
    sys.exit(main())
