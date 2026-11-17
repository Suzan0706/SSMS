"""Time-ordered UUIDv7 (RFC 9562) so ids can be created offline and still index well."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits
    value = (
        (ms & ((1 << 48) - 1)) << 80  # 48-bit Unix ms timestamp
        | 0x7 << 76  # version 7
        | ((rand >> 68) & 0xFFF) << 64  # 12 bits rand_a
        | 0b10 << 62  # RFC variant
        | (rand & ((1 << 62) - 1))
    )  # 62 bits rand_b
    return uuid.UUID(int=value)
