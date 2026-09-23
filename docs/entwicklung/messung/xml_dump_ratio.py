"""Estimate the unpacked size of the German Wikipedia XML dump without downloading 8 GB.

The multistream dump is a chain of independent bz2 streams (100 pages each). At evenly spread offsets the
script reads 4 MB, decompresses every complete stream inside the window and extrapolates the ratio
unpacked/packed to the whole file.
"""

import bz2
import urllib.request

URL = "https://dumps.wikimedia.org/dewiki/latest/dewiki-latest-pages-articles-multistream.xml.bz2"
UA = "compendium-docs-check/1.0 (documentation research; https://github.com/janschachtschabel)"
WINDOW = 4 * 1024 * 1024
SAMPLES = 16
MAGIC = b"BZh91AY&SY"

head = urllib.request.Request(URL, method="HEAD", headers={"User-Agent": UA})
with urllib.request.urlopen(head, timeout=30) as response:
    total = int(response.headers["Content-Length"])

packed = unpacked = streams = 0
ratios = []
for i in range(SAMPLES):
    offset = int(total * (i + 0.5) / SAMPLES)
    request = urllib.request.Request(
        URL, headers={"User-Agent": UA, "Range": f"bytes={offset}-{offset + WINDOW - 1}"}
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()
    start = data.find(MAGIC)
    sample_packed = sample_unpacked = 0
    while start != -1:
        decompressor = bz2.BZ2Decompressor()
        try:
            out = decompressor.decompress(data[start:])
        except OSError:
            break
        if not decompressor.eof:  # the stream runs past the window: not complete, not counted
            break
        used = len(data) - start - len(decompressor.unused_data)
        sample_packed += used
        sample_unpacked += len(out)
        streams += 1
        nxt = start + used
        start = nxt if data[nxt : nxt + len(MAGIC)] == MAGIC else data.find(MAGIC, nxt)
    packed += sample_packed
    unpacked += sample_unpacked
    ratio = sample_unpacked / sample_packed if sample_packed else float("nan")
    ratios.append(ratio)
    print(f"sample {i + 1:2d} at {offset / 1e9:5.2f} GB: {sample_packed / 1e6:5.2f} MB -> {sample_unpacked / 1e6:6.2f} MB"
          f"  ratio {ratio:4.2f}")

ratio = unpacked / packed
print(f"\nfile size (packed): {total / 1e9:.2f} GB, streams decompressed: {streams}")
print(f"ratio unpacked/packed: {ratio:.2f} (min {min(ratios):.2f}, max {max(ratios):.2f})")
print(f"estimated unpacked XML: {total * ratio / 1e9:.1f} GB ({total * ratio / 2**30:.1f} GiB)")
