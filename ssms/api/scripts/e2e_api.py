"""Start the API for the Playwright tests on a fixed school day, so they give the same result on any day of the year.

Test tool only: never use it to run a real school. web/e2e/phase4.spec.ts pins the browser to the same day.
"""

import asyncio
import os
import sys
from datetime import date
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services import calendar  # noqa: E402

E2E_TODAY = date(2026, 10, 21)  # a Wednesday in Term Two of the seed calendar

if get_settings().environment == "production":
    sys.exit("e2e_api.py fixes the date and must not run in production")

calendar.today = lambda: E2E_TODAY

server = uvicorn.Server(
    uvicorn.Config(
        "app.main:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), loop="none", log_level="info"
    )
)
asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)  # psycopg async needs a selector loop on Windows
