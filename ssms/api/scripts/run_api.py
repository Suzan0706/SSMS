"""Start the SSMS API on this computer, using the database settings in ssms/api/.env (see setup_database.py).

    python scripts/run_api.py            # http://127.0.0.1:8000/docs
    python scripts/run_api.py --port 8001

Works on Windows too: async psycopg cannot use Windows' default (Proactor) event loop, so the server runs on a
selector loop.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import uvicorn

API_DIR = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    os.chdir(API_DIR)  # .env and ./storage are read relative to ssms/api
    sys.path.insert(0, str(API_DIR))
    if not (API_DIR / ".env").is_file() and "SSMS_DATABASE_URL" not in os.environ:
        sys.exit("No ssms/api/.env yet: run  python scripts/setup_database.py  first.")
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.host, port=args.port, loop="none"))
    asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
