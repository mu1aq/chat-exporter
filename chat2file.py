"""Run the unified exporter directly from this folder."""

import sys

if sys.version_info < (3, 10):
    current = ".".join(map(str, sys.version_info[:3]))
    raise SystemExit(
        f"Shared Chat Exporter requires Python 3.10 or newer; current version is {current}."
    )

from shared_chat_exporter.router import main


if __name__ == "__main__":
    raise SystemExit(main())
