"""Identifier generation.

Primary keys are UUIDv7 (RFC 9562): the 48 most significant bits carry a Unix
timestamp in milliseconds, so new rows land at the end of B-tree indexes (good
insert locality), while the remaining 74 random bits keep identifiers
unguessable enough to avoid enumeration.
"""

import os
import time
import uuid

_TIMESTAMP_MASK = (1 << 48) - 1
_RAND_B_MASK = (1 << 62) - 1


def uuid7() -> uuid.UUID:
    unix_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")  # 80 random bits, 74 are used
    rand_a = rand >> 68  # 12 bits
    rand_b = rand & _RAND_B_MASK  # 62 bits
    value = (
        (unix_ms & _TIMESTAMP_MASK) << 80
        | 0x7 << 76  # version
        | rand_a << 64
        | 0b10 << 62  # RFC 4122 variant
        | rand_b
    )
    return uuid.UUID(int=value)
