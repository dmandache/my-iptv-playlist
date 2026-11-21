"""Build tv.m3u from the curated list in channels.txt.

For every channel in channels.txt we collect all matching streams from the
sources below, keep only those served from official broadcaster / FAST-service
CDNs, rank them (UK feeds first, HLS over DASH, higher resolution first) and
then probe them in that order. The first stream that actually plays wins.

Streams flagged as geo-blocked (or coming from a UK-only feed) that answer
401/403/451 are kept: the check usually runs outside the UK (GitHub Actions),
where those answers are expected, but they play fine from a UK connection.

A report of what was chosen and what failed is written to STATUS.md.
"""

import argparse
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

IPTV_ORG = "https://raw.githubusercontent.com/iptv-org/iptv/master/streams"

# (label, url, region, group-filter). Order is a tie-breaker: earlier wins.
SOURCES = [
    ("iptv-org uk_bbc", f"{IPTV_ORG}/uk_bbc.m3u", "UK", None),
    ("Free-TV", "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlist.m3u8", "UK", "UK"),
    ("iptv-org uk", f"{IPTV_ORG}/uk.m3u", "UK", None),
    ("iptv-org uk_samsung", f"{IPTV_ORG}/uk_samsung.m3u", "UK", None),
    ("iptv-org uk_rakuten", f"{IPTV_ORG}/uk_rakuten.m3u", "UK", None),
    ("iptv-org uk_pluto", f"{IPTV_ORG}/uk_pluto.m3u", "UK", None),
    ("iptv-org us_xumo", f"{IPTV_ORG}/us_xumo.m3u", "US", None),
    ("iptv-org us_samsung", f"{IPTV_ORG}/us_samsung.m3u", "US", None),
    ("iptv-org us_vizio", f"{IPTV_ORG}/us_vizio.m3u", "US", None),
    ("iptv-org us_tubi", f"{IPTV_ORG}/us_tubi.m3u", "US", None),
    ("iptv-org us", f"{IPTV_ORG}/us.m3u", "US", None),
    ("iptv-org us_pluto", f"{IPTV_ORG}/us_pluto.m3u", "US", None),
]

# Official broadcaster / FAST-platform CDNs. Anything else (bare IPs, random
# restream boxes) is ignored: those are unauthorised and die constantly.
TRUSTED_HOSTS = (
    "akamaized.net", "bbci.co.uk", "skycdp.com", "amagi.tv", "cloudfront.net",
    "jmp2.uk", "nbcuni.com", "tubi.video", "tubi.io", "wurl.com",
    "amazonaws.com", "frequency.stream", "transmit.live", "simplestreamcdn.com",
    "its-newid.net", "bloomberg.com", "brightcove.com", "s4c-cdn.co.uk", "rakuten.tv",
)

CHANNELS_FILE = "channels.txt"
OUTFILE = "tv.m3u"
STATUS_FILE = "STATUS.md"
EPG_URL = "https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 12
GEO_STATUSES = {401, 403, 451}


# -----------------------------------------------------------------------------
# Parsing
# -----------------------------------------------------------------------------

@dataclass
class Stream:
    raw_name: str
    name: str
    url: str
    attrs: Dict[str, str]
    source: str
    source_idx: int
    region: str
    geo: bool
    quality: int
    is_dash: bool
    is_hevc: bool


@dataclass
class Channel:
    section: str
    display: str
    aliases: List[str]
    candidates: List[Stream] = field(default_factory=list)
    chosen: Optional[Stream] = None
    note: str = ""
    tried: List[Tuple[Stream, str]] = field(default_factory=list)


def download_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


def split_extinf(extinf: str) -> Tuple[str, str]:
    in_quotes = False
    for idx, ch in enumerate(extinf):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            return extinf[:idx], extinf[idx + 1:].strip()
    return extinf, ""


def parse_m3u(text: str):
    """Yield (attrs, name, url) for every entry; attrs['_extra'] keeps player hints."""
    lines = [l.strip() for l in text.splitlines()]
    i = 0
    while i < len(lines):
        if lines[i].startswith("#EXTINF"):
            head, name = split_extinf(lines[i])
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', head))
            extra = []
            j = i + 1
            while j < len(lines) and (not lines[j] or lines[j].startswith("#")):
                if lines[j].startswith(("#EXTVLCOPT", "#KODIPROP")):
                    extra.append(lines[j])
                if lines[j].startswith("#EXTINF"):
                    break
                j += 1
            if j < len(lines) and not lines[j].startswith("#"):
                attrs["_extra"] = "\n".join(extra)
                yield attrs, name, lines[j]
                i = j
        i += 1


def fold(text: str) -> str:
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip().lower()


def clean_name(name: str) -> str:
    n = re.sub(r"[ⒼⓈⓎⒷ]", "", name).strip()
    while True:
        u = re.sub(r"\s+\[[^\]]+\]\s*$", "", n)
        u = re.sub(r"\s+\((SD|HD|FHD|UHD|HEVC|\d{3,4}[pi])\)\s*$", "", u, flags=re.I)
        u = re.sub(r"\s+[–-]\s+Pluto TV\s*$", "", u, flags=re.I)
        if u == n:
            break
        n = u.strip()
    return re.sub(r"\s{2,}", " ", n).strip()


def quality_of(raw: str) -> int:
    m = re.search(r"\((\d{3,4})[pi]\)", raw)
    if m:
        return int(m.group(1))
    if re.search(r"\b(FHD|1080)\b", raw, re.I):
        return 1080
    if re.search(r"\bHD\b", raw):
        return 720
    return 480  # unknown: assume SD-ish


def is_trusted(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if not host or re.fullmatch(r"[\d.]+", host):
        return False
    return any(host == h or host.endswith("." + h) for h in TRUSTED_HOSTS)


def load_channels(path: str) -> List[Channel]:
    channels, section = [], "Other"
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1].strip()
                continue
            if "=" in line:
                display, rest = line.split("=", 1)
                aliases = [a.strip() for a in rest.split("|") if a.strip()]
            else:
                display, aliases = line, [line]
            channels.append(Channel(section, display.strip(), aliases))
    return channels


def load_streams() -> List[Stream]:
    streams = []
    for idx, (label, url, region, group) in enumerate(SOURCES):
        try:
            text = download_text(url)
        except Exception as exc:  # one dead source should not kill the build
            print(f"! could not fetch {label}: {exc}")
            continue
        for attrs, raw, surl in parse_m3u(text):
            if group and attrs.get("group-title") != group:
                continue
            streams.append(Stream(
                raw_name=raw,
                name=clean_name(raw),
                url=surl,
                attrs=attrs,
                source=label,
                source_idx=idx,
                region=region,
                geo=("Geo-blocked" in raw or "Ⓖ" in raw or region == "UK"),
                quality=quality_of(raw),
                is_dash=".mpd" in surl.lower(),
                is_hevc="HEVC" in raw.upper(),
            ))
    return streams


def rank(s: Stream):
    # UK feeds first (you're in the UK), then broad-compat HLS over DASH/HEVC,
    # then resolution, then source order.
    return (s.region != "UK", s.is_dash or s.is_hevc, -s.quality, s.source_idx)


# -----------------------------------------------------------------------------
# Health check
# -----------------------------------------------------------------------------

def fetch(url: str, max_bytes: int = 256_000, rng: bool = False):
    headers = {"User-Agent": UA}
    if rng:
        headers["Range"] = "bytes=0-2047"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.geturl(), r.read(max_bytes)


def first_uri(body: str) -> Optional[str]:
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return line
    return None


def probe(url: str) -> Tuple[bool, str, int]:
    """Return (ok, reason, http_status). Follows master -> media -> segment."""
    try:
        status, final, data = fetch(url)
        body = data.decode("utf-8", errors="replace")
        if "<MPD" in body:
            return True, "plays (DASH manifest)", status
        if "#EXTM3U" not in body:
            return False, "not a playlist", status
        for _ in range(3):  # master -> variant -> (rarely) another level
            if "#EXT-X-STREAM-INF" not in body:
                break
            nxt = first_uri(body.split("#EXT-X-STREAM-INF", 1)[1])
            if not nxt:
                return False, "empty master playlist", status
            status, final, data = fetch(urljoin(final, nxt))
            body = data.decode("utf-8", errors="replace")
        if "#EXTINF" not in body:
            return False, "no segments", status
        seg = first_uri(body)
        if seg:
            s_status, _, _ = fetch(urljoin(final, seg), max_bytes=2048, rng=True)
            if s_status not in (200, 206):
                return False, f"segment HTTP {s_status}", s_status
        return True, "plays", 200
    except HTTPError as e:
        return False, f"HTTP {e.code}", e.code
    except (URLError, TimeoutError, OSError) as e:
        return False, f"network: {getattr(e, 'reason', e)}", 0
    except Exception as e:  # malformed responses etc.
        return False, f"error: {e}", 0


def resolve(ch: Channel, check: bool) -> Channel:
    if not ch.candidates:
        ch.note = "no official stream in sources"
        return ch
    if not check:
        ch.chosen, ch.note = ch.candidates[0], "not checked"
        return ch
    geo_fallback = None
    for s in ch.candidates[:6]:
        ok, reason, status = probe(s.url)
        ch.tried.append((s, reason))
        if ok:
            ch.chosen, ch.note = s, reason
            return ch
        if s.geo and status in GEO_STATUSES and geo_fallback is None:
            geo_fallback = s
    if geo_fallback:
        ch.chosen, ch.note = geo_fallback, "UK-only (refused outside UK, expected)"
    else:
        ch.note = "all streams failed"
    return ch


# -----------------------------------------------------------------------------
# Output
# -----------------------------------------------------------------------------

def tvg_id_for(ch: Channel) -> str:
    tid = ch.chosen.attrs.get("tvg-id", "").strip()
    if tid:
        return tid
    slug = re.sub(r"[^A-Za-z0-9]+", "", ch.display)
    return f"{slug}.{'uk' if ch.chosen.region == 'UK' else 'us'}"


def write_playlist(channels: List[Channel]):
    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write(f'#EXTM3U url-tvg="{EPG_URL}"\n')
        for ch in channels:
            s = ch.chosen
            if not s:
                continue
            parts = [f'tvg-id="{tvg_id_for(ch)}"', f'tvg-name="{ch.display}"']
            if s.attrs.get("tvg-logo"):
                parts.append(f'tvg-logo="{s.attrs["tvg-logo"]}"')
            parts.append(f'group-title="{ch.section}"')
            f.write(f'#EXTINF:-1 {" ".join(parts)},{ch.display}\n')
            if s.attrs.get("_extra"):
                f.write(s.attrs["_extra"] + "\n")
            f.write(s.url + "\n")


def write_status(channels: List[Channel], checked: bool):
    bad = [c for c in channels if not c.chosen]
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        f.write("# Playlist status\n\n")
        f.write(f"{len(channels) - len(bad)} of {len(channels)} channels in the playlist"
                f"{'' if checked else ' (streams not checked this run)'}.\n\n")
        f.write("| Group | Channel | Result | Quality | Source |\n|---|---|---|---|---|\n")
        for c in channels:
            if c.chosen:
                s = c.chosen
                fmt = "DASH" if s.is_dash else "HLS"
                f.write(f"| {c.section} | {c.display} | {c.note} | {s.quality}p {fmt} | {s.source} |\n")
            else:
                f.write(f"| {c.section} | {c.display} | **dropped: {c.note}** | | |\n")
        if bad:
            f.write("\n## Dropped channels\n\n")
            for c in bad:
                f.write(f"- **{c.display}**: {c.note}\n")
                for s, reason in c.tried:
                    f.write(f"  - {s.source} `{s.raw_name}`: {reason}\n")


def main():
    ap = argparse.ArgumentParser(description="Build tv.m3u from channels.txt.")
    ap.add_argument("--no-check", action="store_true", help="Skip live stream checks.")
    args = ap.parse_args()

    channels = load_channels(CHANNELS_FILE)
    streams = [s for s in load_streams() if is_trusted(s.url)]
    by_name: Dict[str, List[Stream]] = {}
    for s in streams:
        by_name.setdefault(fold(s.name), []).append(s)

    for ch in channels:
        seen, cands = set(), []
        for alias in ch.aliases:
            for s in by_name.get(fold(alias), []):
                if s.url not in seen:
                    seen.add(s.url)
                    cands.append(s)
        ch.candidates = sorted(cands, key=rank)

    with ThreadPoolExecutor(max_workers=12) as pool:
        channels = list(pool.map(lambda c: resolve(c, not args.no_check), channels))

    write_playlist(channels)
    write_status(channels, not args.no_check)

    kept = sum(1 for c in channels if c.chosen)
    print(f"Wrote {OUTFILE}: {kept}/{len(channels)} channels")
    for c in channels:
        mark = "OK " if c.chosen else "-- "
        extra = f" [{c.chosen.source}, {c.chosen.quality}p]" if c.chosen else ""
        print(f"  {mark}{c.section:14} {c.display:28} {c.note}{extra}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error:", e)
        sys.exit(1)
