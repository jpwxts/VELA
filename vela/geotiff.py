"""Read one numeric value from a small uncompressed GeoTIFF."""

from __future__ import annotations

import struct


def read_center_value(payload: bytes) -> float | None:
    """Return the center sample of a one-band float or integer TIFF.

    GWIS publishes the Fire Weather Index as a numeric raster. This reader
    accepts the small uncompressed tiles that WMS returns for one point.
    Any other encoding is left unread instead of being guessed.
    """

    if len(payload) < 16 or payload[:2] not in (b"II", b"MM"):
        return None
    endian = "<" if payload[:2] == b"II" else ">"
    if struct.unpack(endian + "H", payload[2:4])[0] != 42:
        return None
    offset = struct.unpack(endian + "I", payload[4:8])[0]
    if offset + 2 > len(payload):
        return None
    count = struct.unpack(endian + "H", payload[offset : offset + 2])[0]
    tags = {}
    cursor = offset + 2
    for _ in range(count):
        if cursor + 12 > len(payload):
            return None
        tag, kind, number, raw = struct.unpack(endian + "HHII", payload[cursor : cursor + 12])
        tags[tag] = (kind, number, raw)
        cursor += 12
    width = _short(tags.get(256), endian, payload)
    height = _short(tags.get(257), endian, payload)
    bits = _short(tags.get(258), endian, payload)
    compression = _short(tags.get(259), endian, payload)
    samples = _short(tags.get(277), endian, payload) or 1
    sample_format = _short(tags.get(339), endian, payload) or 1
    strip = _long(tags.get(273), endian, payload)
    nbytes = _long(tags.get(279), endian, payload)
    if None in (width, height, bits, compression, strip, nbytes):
        return None
    if compression != 1 or samples != 1 or bits not in (16, 32) or width < 1 or height < 1:
        return None
    if strip + nbytes > len(payload):
        return None
    expected = width * height * (bits // 8)
    if nbytes != expected:
        return None
    blob = payload[strip : strip + nbytes]
    if bits == 32 and sample_format == 3:
        values = struct.unpack(endian + f"{width * height}f", blob)
    elif bits == 16 and sample_format in (1, 2):
        kind = "H" if sample_format == 1 else "h"
        values = struct.unpack(endian + f"{width * height}{kind}", blob)
    elif bits == 32 and sample_format in (1, 2):
        kind = "I" if sample_format == 1 else "i"
        values = struct.unpack(endian + f"{width * height}{kind}", blob)
    else:
        return None
    center = values[(height // 2) * width + (width // 2)]
    if isinstance(center, float) and center != center:
        return None
    return float(center)


def _short(tag, endian: str, payload: bytes) -> int | None:
    if tag is None:
        return None
    kind, number, raw = tag
    if kind == 3 and number == 1:
        return raw & 0xFFFF
    return None


def _long(tag, endian: str, payload: bytes) -> int | None:
    if tag is None:
        return None
    kind, number, raw = tag
    if kind in (3, 4) and number == 1:
        return int(raw)
    return None
