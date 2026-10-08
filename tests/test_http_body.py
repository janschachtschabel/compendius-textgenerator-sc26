"""Reading an upstream answer within its bound, also compressed (audit 2026-10-03, F12; review of 2026-10-08)."""

from __future__ import annotations

import gzip
import tracemalloc
import zlib
from collections.abc import Iterator

import httpx
import pytest

from app.http_body import AnswerTooLargeError, UnreadableAnswerError, read_bounded

BOMB = gzip.compress(bytes(50_000_000))  # 50 MB of zeros in some 50 KB


class Pieces(httpx.SyncByteStream):
    """A body that arrives in pieces and counts the pieces taken."""

    def __init__(self, pieces: list[bytes] | Iterator[bytes]) -> None:
        self.pieces = pieces
        self.taken = 0

    def __iter__(self) -> Iterator[bytes]:
        for piece in self.pieces:
            self.taken += 1
            yield piece


def answer(stream: httpx.SyncByteStream, coding: str | None = None) -> httpx.Response:
    headers = {"Content-Encoding": coding} if coding else {}
    return httpx.Response(200, headers=headers, stream=stream)


def test_a_compressed_answer_is_unpacked_no_further_than_the_bound() -> None:
    """httpx unpacked each network read whole: 590 bytes of stacked gzip reached 558 MiB before the bound was
    checked."""
    tracemalloc.start()
    try:
        with pytest.raises(AnswerTooLargeError):
            read_bounded(answer(Pieces([BOMB]), "gzip"), 1_000_000)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak < 8_000_000


@pytest.mark.parametrize("coding", ["gzip, gzip", "br", "zstd", "compress", "gzip, br"])
def test_a_coding_asked_for_by_no_one_is_not_unpacked(coding: str) -> None:
    with pytest.raises(UnreadableAnswerError, match="Inhaltskodierung"):
        read_bounded(answer(Pieces([b"x" * 100]), coding), 1_000_000)


@pytest.mark.parametrize(
    ("coding", "packed"),
    [
        ("gzip", gzip.compress(b'{"a": 1}' * 1000)),
        ("x-gzip", gzip.compress(b'{"a": 1}' * 1000)),
        ("deflate", zlib.compress(b'{"a": 1}' * 1000)),
        ("deflate", zlib.compress(b'{"a": 1}' * 1000)[2:-4]),  # raw deflate, as some servers send it
        ("identity", b'{"a": 1}' * 1000),
        (None, b'{"a": 1}' * 1000),
    ],
    ids=["gzip", "x-gzip", "deflate", "raw deflate", "identity", "none"],
)
def test_an_answer_within_the_bound_is_read_whole(coding: str | None, packed: bytes) -> None:
    pieces = [packed[i : i + 700] for i in range(0, len(packed), 700)]

    assert read_bounded(answer(Pieces(pieces), coding), 1_000_000) == b'{"a": 1}' * 1000


def test_a_broken_compressed_answer_is_unreadable_not_a_crash() -> None:
    """A corrupt gzip body raised httpx.DecodingError, which no caller caught: one material failed a knowledge
    request (review of 2026-10-08)."""
    with pytest.raises(UnreadableAnswerError):
        read_bounded(answer(Pieces([b"\x1f\x8b\x08\x00" + b"garbage" * 10]), "gzip"), 1_000_000)


def test_reading_stops_at_the_bound() -> None:
    endless = Pieces(iter(lambda: b"x" * 1000, None))

    with pytest.raises(AnswerTooLargeError):
        read_bounded(answer(endless), 10_000)

    assert endless.taken == 11
