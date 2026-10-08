"""Reading the answer of an upstream service within a bound (audit 2026-10-03, F12).

The clients of edu-sharing and the b-api read every answer whole before parsing it; an answer of a faulty or
compromised upstream - an allowlisted repository or the gateway - could fill the memory of a worker that way. The body
is read as a stream and counted after decoding, so a compressed answer counts by what it unpacks to.

The service unpacks it itself, never past the bound: httpx unpacks each network read whole, and an answer of 590 bytes
in stacked gzip reached 558 MiB before the bound was checked (review of 2026-10-08). The clients ask for gzip and
deflate only (``ACCEPT_ENCODING``) and read nothing else, and a coding applied twice no server sends unasked.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable

import httpx

ACCEPT_ENCODING = "gzip, deflate"
_GZIP = 16 + zlib.MAX_WBITS
_CODINGS = {"gzip": _GZIP, "x-gzip": _GZIP, "deflate": zlib.MAX_WBITS}

Unpack = Callable[[bytes, int], bytes]


class UnreadableAnswerError(ValueError):
    """The answer cannot be read within its bound: too large, in a coding the service does not unpack, or broken."""


class AnswerTooLargeError(UnreadableAnswerError):
    """The answer runs past the bound; reading stopped there."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"mehr als {limit:,} Byte".replace(",", "."))
        self.limit = limit


def read_bounded(response: httpx.Response, limit: int) -> bytes:
    """The decoded body of a streamed ``response``; ``AnswerTooLargeError`` once it runs past ``limit`` bytes,
    ``UnreadableAnswerError`` for a coding the service does not unpack and for compressed data that is broken."""
    if response.is_stream_consumed:  # read already, as a test transport hands it over: decoded, counted as it is
        if len(response.content) > limit:
            raise AnswerTooLargeError(limit)
        return response.content
    unpack = _unpacker(response.headers.get("content-encoding", ""))
    body = bytearray()
    try:
        for raw in response.iter_raw():
            body.extend(unpack(raw, limit + 1 - len(body)))
            if len(body) > limit:
                raise AnswerTooLargeError(limit)
    except zlib.error as exc:
        raise UnreadableAnswerError(f"beschädigten komprimierten Daten ({exc})") from exc
    return bytes(body)


def _unpacker(header: str) -> Unpack:
    """What unpacks a body sent in ``header``'s coding, a piece at a time, never more than asked for."""
    codings = [coding.strip().lower() for coding in header.split(",") if coding.strip().lower() not in ("", "identity")]
    if not codings:
        return lambda raw, _wanted: raw
    if len(codings) > 1 or codings[0] not in _CODINGS:
        raise UnreadableAnswerError(f"einer Inhaltskodierung, die der Dienst nicht entpackt ({header.strip()})")
    return _Inflater(_CODINGS[codings[0]])


class _Inflater:
    """zlib's decompressor with a bound per call: what it holds back stays in ``unconsumed_tail`` for the next one.
    A deflate body without its zlib header, as some servers send it, is read raw, as httpx does."""

    def __init__(self, wbits: int) -> None:
        self._wbits = wbits
        self._decompressor = zlib.decompressobj(wbits)
        self._started = False

    def __call__(self, raw: bytes, wanted: int) -> bytes:
        try:
            out = self._decompressor.decompress(raw, max(wanted, 1))
        except zlib.error:
            if self._started or self._wbits != zlib.MAX_WBITS:
                raise
            self._wbits = -zlib.MAX_WBITS
            self._decompressor = zlib.decompressobj(self._wbits)
            out = self._decompressor.decompress(raw, max(wanted, 1))
        self._started = True
        unpacked = bytearray(out)
        while self._decompressor.unconsumed_tail and len(unpacked) < wanted:
            unpacked.extend(self._decompressor.decompress(self._decompressor.unconsumed_tail, wanted - len(unpacked)))
        return bytes(unpacked)
