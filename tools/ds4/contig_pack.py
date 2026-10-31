#!/usr/bin/env python3
"""Write the RAM store's contig file: every covered expert as one slot image, so the store reads an expert with one
unbuffered read instead of three scattered ones (ds4_store.hpp, DS4_STORE_CONTIG).

  1. maya-ds4 started once with DS4_STORE_CONTIG_DUMP=PREFIX (and --ssd-cache) writes PREFIX.hdr and PREFIX.json
  2. contig_pack.py PREFIX OUT            writes OUT: the header, then each layer's experts in order
  3. contig_pack.py PREFIX OUT --verify N  re-reads N random experts from OUT (unbuffered) against the model's files

A block (slot_bytes) holds matrix r's aligned span at tr[r] - exactly what the three reads put in a slot - so the
engine's view of a slot is the same either way.  The model's files are only read.
"""
import json
import mmap
import os
import random
import sys


def load(prefix):
    g = json.load(open(prefix + ".json"))
    hdr = open(prefix + ".hdr", "rb").read()
    assert len(hdr) == g["hdr"], "header size"
    return g, hdr


def spans(g, li, e):
    """matrix r of expert e of layer li: (file, aligned start, span, region start in the block)"""
    A, L = g["align"], g["layers"][li]
    out = []
    for r in range(3):
        off = L["off"][r] + e * L["stride"][r]
        a0 = off - off % A
        a1 = (off + L["bytes"][r] + A - 1) // A * A
        out.append((L["file"][r], a0, a1 - a0, g["tr"][r]))
    return out


def write(prefix, out):
    g, hdr = load(prefix)
    sb, A = g["slot_bytes"], g["align"]
    fds = [os.open(p, os.O_RDONLY) for p in g["files"]]
    n_all = sum(max(0, L["n_exp"]) for L in g["layers"])
    print(f"{n_all} experts, blocks of {sb / 1e6:.2f} MB -> {(g['hdr'] + n_all * sb) / 1e9:.1f} GB at {out}", flush=True)
    with open(out + ".part", "wb") as fo:
        fo.write(hdr)
        done = 0
        for li, L in enumerate(g["layers"]):
            n = L["n_exp"]
            if n <= 0:
                continue
            bufs = []
            for r in range(3):   # the layer's matrix r for every expert: one sequential read
                f = L["file"][r]
                lo = L["off"][r] - L["off"][r] % A
                hi = (L["off"][r] + (n - 1) * L["stride"][r] + L["bytes"][r] + 2 * A - 1) // A * A
                b = os.pread(fds[f], hi - lo, lo)
                bufs.append((lo, b))
                os.posix_fadvise(fds[f], lo, hi - lo, os.POSIX_FADV_DONTNEED)
            blk = bytearray(sb)
            for e in range(n):
                blk[:] = bytes(sb)
                for r, (f, a0, span, at) in enumerate(spans(g, li, e)):
                    lo, b = bufs[r]
                    piece = b[a0 - lo:a0 - lo + span]
                    blk[at:at + len(piece)] = piece   # (a span past the file's end: zeros, as a short read leaves)
                fo.write(blk)
            done += n
            fo.flush()
            os.posix_fadvise(fo.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            print(f"layer {li}: {n} experts ({done}/{n_all})", flush=True)
        os.fsync(fo.fileno())
    os.rename(out + ".part", out)
    print("written", out)


def verify(prefix, out, count):
    g, hdr = load(prefix)
    sb = g["slot_bytes"]
    fds = [os.open(p, os.O_RDONLY) for p in g["files"]]
    fo = os.open(out, os.O_RDONLY | os.O_DIRECT)
    assert os.pread(os.open(out, os.O_RDONLY), len(hdr), 0) == hdr, "header differs"
    base, idx = [], 0
    for L in g["layers"]:
        base.append(idx)
        idx += max(0, L["n_exp"])
    buf = mmap.mmap(-1, sb)
    picks = [(li, random.randrange(L["n_exp"])) for li, L in enumerate(g["layers"]) if L["n_exp"] > 0]
    picks = [random.choice(picks) for _ in range(count)]
    bad = 0
    for li, _ in picks:
        e = random.randrange(g["layers"][li]["n_exp"])
        os.preadv(fo, [buf], g["hdr"] + (base[li] + e) * sb)
        for f, a0, span, at in spans(g, li, e):
            want = os.pread(fds[f], span, a0)
            if buf[at:at + len(want)] != want:
                bad += 1
                print(f"MISMATCH layer {li} expert {e}")
                break
    print(f"verify: {count} random experts, {bad} mismatched")
    return bad == 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) == 2:
        write(a[0], a[1])
    elif len(a) == 4 and a[2] == "--verify":
        sys.exit(0 if verify(a[0], a[1], int(a[3])) else 1)
    else:
        sys.exit(__doc__)
