"""Virus scanning of uploads with ClamAV's clamd over TCP (INSTREAM), without extra libraries.

scan() answers CLEAN or INFECTED; anything else (clamd down, a timeout, a clamd error such as a file over its
StreamMaxLength) raises ScannerUnavailable, and the upload is refused rather than stored unscanned.
"""

import asyncio
import struct

from app.core.config import get_settings

CHUNK = 64 * 1024
TIMEOUT_S = 30


class ScannerUnavailable(Exception):
    pass


def configured() -> bool:
    return bool(get_settings().clamav_address)


async def scan(data: bytes) -> tuple[str, str | None]:
    """(CLEAN, None) or (INFECTED, signature name)."""
    host, _, port = get_settings().clamav_address.rpartition(":")
    try:
        return await asyncio.wait_for(_instream(host, int(port), data), TIMEOUT_S)
    except (OSError, TimeoutError, ValueError) as exc:
        raise ScannerUnavailable(type(exc).__name__) from exc


async def _instream(host: str, port: int, data: bytes) -> tuple[str, str | None]:
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(b"zINSTREAM\0")
        for start in range(0, len(data), CHUNK):
            chunk = data[start : start + CHUNK]
            writer.write(struct.pack(">I", len(chunk)) + chunk)
            await writer.drain()
        writer.write(struct.pack(">I", 0))
        await writer.drain()
        reply = (await reader.read(4096)).rstrip(b"\0\n").decode(errors="replace")
    finally:
        writer.close()
    # "stream: OK" | "stream: Eicar-Test-Signature FOUND" | "INSTREAM size limit exceeded. ERROR"
    if reply.endswith(" OK"):
        return "CLEAN", None
    if reply.endswith(" FOUND"):
        return "INFECTED", reply.removeprefix("stream: ").removesuffix(" FOUND")
    raise ScannerUnavailable(reply[:120] or "empty reply")
