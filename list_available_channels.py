"""List every channel name the playlist sources offer (official CDNs only).

Writes all/available.txt. Copy any name from there into channels.txt to add it.
"""

import os
from collections import defaultdict

import generate_playlist as gp

OUT = os.path.join("all", "available.txt")


def main():
    best = defaultdict(lambda: [0, set()])
    for s in gp.load_streams():
        if not gp.is_trusted(s.url):
            continue
        entry = best[s.name]
        entry[0] = max(entry[0], s.quality)
        entry[1].add(s.source.replace("iptv-org ", ""))

    os.makedirs("all", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("# Channels available from official sources: name | best quality | sources\n")
        for name in sorted(best, key=str.lower):
            q, srcs = best[name]
            fh.write(f"{name} | {q}p | {', '.join(sorted(srcs))}\n")
    print(f"Wrote {OUT} ({len(best)} channels)")


if __name__ == "__main__":
    main()
