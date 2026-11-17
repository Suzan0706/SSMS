"""Small local load runner (no k6 needed) for the same scenarios as ssms/loadtest/*.js, to compare builds on one
machine. Numbers from a laptop are indicative only; the acceptance run is k6 against staging (NFR-03/04).

    python scripts/loadtest.py reads     --base http://127.0.0.1:8765 --users mfano-sec:mf-2025-0014:Mfano@2026 ...
    python scripts/loadtest.py results-day --base http://localhost:8080 --term <term id> --users ...   (Phase 12)
    python scripts/loadtest.py callbacks --base http://127.0.0.1:8765 --secret <webhook secret> --ref
        mfano-sec.MF-2025-0014

Prints requests per second, p50/p95/p99 latency, and every status code seen.
"""

import argparse
import asyncio
import hashlib
import hmac
import json
import statistics
import time
import uuid
from collections import Counter

import httpx


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))] if ordered else 0.0


async def run(args) -> None:
    latencies: list[float] = []
    statuses: Counter = Counter()
    stop = time.monotonic() + args.seconds

    async with httpx.AsyncClient(base_url=args.base, timeout=30) as client:
        tokens: list[tuple[str, str | None]] = []
        if args.scenario in ("reads", "results-day"):
            for spec in args.users:
                school, username, password = spec.split(":", 2)
                r = await client.post(
                    "/api/v1/auth/login", json={"school_code": school, "username": username, "password": password}
                )
                r.raise_for_status()
                token = r.json()["access_token"]
                me = await client.get("/api/v1/me/student", headers={"Authorization": f"Bearer {token}"})
                tokens.append((token, me.json().get("student_id") if me.status_code == 200 else None))

        async def timed(method: str, url: str, **kw) -> httpx.Response:
            start = time.perf_counter()
            r = await client.request(method, url, **kw)
            latencies.append((time.perf_counter() - start) * 1000)
            statuses[r.status_code] += 1
            return r

        async def reader(i: int) -> None:
            token, student = tokens[i % len(tokens)]
            headers = {"Authorization": f"Bearer {token}"}
            while time.monotonic() < stop:
                await timed("GET", "/api/v1/me/student", headers=headers)
                if student and args.term:
                    await timed("GET", f"/api/v1/students/{student}/results?term_id={args.term}", headers=headers)
                await timed("GET", "/api/v1/announcements", headers=headers)

        async def results_day(i: int) -> None:
            """What a student does when results come out: home, results, progress, and now and then the PDF."""
            token, student = tokens[i % len(tokens)]
            headers = {"Authorization": f"Bearer {token}"}
            n = 0
            while time.monotonic() < stop:
                n += 1
                await timed("GET", "/api/v1/me/student", headers=headers)
                await timed("GET", f"/api/v1/students/{student}/results?term_id={args.term}", headers=headers)
                await timed("GET", f"/api/v1/students/{student}/progress", headers=headers)
                await timed("GET", "/api/v1/announcements", headers=headers)
                if n % 5 == 0:
                    await timed("GET", f"/api/v1/students/{student}/report-card?term_id={args.term}", headers=headers)

        async def payer(i: int) -> None:
            n = 0
            while time.monotonic() < stop:
                n += 1
                tx = f"LT-{i}-{n - 1 if n % 10 == 0 else n}"  # every 10th repeats the previous transaction
                body = json.dumps(
                    {
                        "transaction_id": tx,
                        "reference": args.ref,
                        "amount": "1000",
                        "msisdn": "255700000001",
                        "payer_name": "LOAD",
                        "timestamp": "2026-10-21T10:00:00+03:00",
                    }
                ).encode()
                sig = hmac.new(args.secret.encode(), body, hashlib.sha256).hexdigest()
                await timed(
                    "POST",
                    "/api/v1/webhooks/mpesa",
                    content=body,
                    headers={"Content-Type": "application/json", "X-SSMS-Signature": f"sha256={sig}"},
                )

        worker = {"reads": reader, "results-day": results_day}.get(args.scenario, payer)
        started = time.monotonic()
        await asyncio.gather(*(worker(i) for i in range(args.concurrency)))
        elapsed = time.monotonic() - started

    print(
        json.dumps(
            {
                "scenario": args.scenario,
                "concurrency": args.concurrency,
                "requests": len(latencies),
                "rps": round(len(latencies) / elapsed, 1),
                "p50_ms": round(statistics.median(latencies), 1) if latencies else None,
                "p95_ms": round(percentile(latencies, 95), 1),
                "p99_ms": round(percentile(latencies, 99), 1),
                "statuses": dict(statuses),
                "run": str(uuid.uuid4())[:8],
            },
            indent=1,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=["reads", "results-day", "callbacks"])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--users", nargs="*", default=[])
    parser.add_argument("--term")
    parser.add_argument("--secret", default="")
    parser.add_argument("--ref", default="")
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--seconds", type=int, default=30)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
