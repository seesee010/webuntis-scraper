"""Allow `python -m untis` to invoke the CLI."""
from .main import main

if __name__ == "__main__":
    raise SystemExit(main())
