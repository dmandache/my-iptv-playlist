#!/usr/bin/env python3
"""
Build a local XMLTV EPG for channels found in an M3U playlist.

The script reads tvg-id + channel names from the playlist, matches them against
channel display names from a source XMLTV feed, then rewrites matching channel
and programme blocks so output channel ids exactly match the playlist tvg-id.
"""

from __future__ import annotations

import argparse
import gzip
import html
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple
from urllib.request import Request, urlopen


DEFAULT_SOURCE_URL = "https://epgshare01.online/epgshare01/epg_ripper_ALL_SOURCES1.xml.gz"

CHANNEL_START_RE = re.compile(r'<channel\s+id="([^"]+)"')
DISPLAY_NAME_RE = re.compile(r"<display-name[^>]*>(.*?)</display-name>")
PROGRAMME_START_RE = re.compile(r'<programme\s+[^>]*channel="([^"]+)"')
TVG_ID_RE = re.compile(r'tvg-id="([^"]+)"')
COUNTRY_RE = re.compile(r"\.([a-z]{2})(?:@|$)", re.IGNORECASE)


@dataclass(frozen=True)
class PlaylistEntry:
    tvg_id: str
    name: str
    name_norm: str
    country: str


def get_extinf_name(extinf_line: str) -> str:
    if not extinf_line:
        return ""

    in_quotes = False
    for idx, ch in enumerate(extinf_line):
        if ch == '"':
            in_quotes = not in_quotes
            continue
        if ch == "," and not in_quotes:
            return extinf_line[idx + 1 :].strip()

    return ""


def normalize_name(value: str) -> str:
    if not value:
        return ""

    lowered = value.lower()
    normalized = unicodedata.normalize("NFD", lowered)
    without_diacritics = "".join(
        ch for ch in normalized if unicodedata.category(ch) != "Mn"
    )
    without_entities = without_diacritics.replace("&amp;", "and")
    return re.sub(r"[^a-z0-9]+", "", without_entities)


def get_country_code_from_id(tvg_id: str) -> str:
    match = COUNTRY_RE.search(tvg_id or "")
    return match.group(1).lower() if match else ""


def parse_playlist_entries(path: Path) -> List[PlaylistEntry]:
    if not path.is_file():
        raise FileNotFoundError(f"Playlist file not found: {path}")

    entries: List[PlaylistEntry] = []
    seen_ids: Set[str] = set()

    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\r\n")
            if not line.startswith("#EXTINF"):
                continue

            name = get_extinf_name(line)
            if not name:
                continue

            match = TVG_ID_RE.search(line)
            if not match:
                continue

            tvg_id = match.group(1).strip()
            if not tvg_id or tvg_id in seen_ids:
                continue

            seen_ids.add(tvg_id)
            name_norm = normalize_name(name)
            if not name_norm:
                continue

            entries.append(
                PlaylistEntry(
                    tvg_id=tvg_id,
                    name=name.strip(),
                    name_norm=name_norm,
                    country=get_country_code_from_id(tvg_id),
                )
            )

    return entries


def open_gzip_text_reader(url: str):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    response = urlopen(req, timeout=120)
    gzip_stream = gzip.GzipFile(fileobj=response)
    reader = gzip_stream if hasattr(gzip_stream, "readline") else gzip_stream
    return response, gzip_stream, reader


def add_source_id_by_name(name_to_sources: Dict[str, List[str]], name_norm: str, source_id: str) -> None:
    if not name_norm or not source_id:
        return

    bucket = name_to_sources.setdefault(name_norm, [])
    if source_id not in bucket:
        bucket.append(source_id)


def build_source_index(url: str) -> Tuple[Dict[str, List[str]], int]:
    name_to_sources: Dict[str, List[str]] = {}
    channel_count = 0

    response, gzip_stream, reader = open_gzip_text_reader(url)
    text_reader = iter(lambda: reader.readline().decode("utf-8", "replace"), "")

    try:
        for line in text_reader:
            channel_match = CHANNEL_START_RE.search(line)
            if not channel_match:
                continue

            source_id = channel_match.group(1)
            channel_count += 1
            block: List[str] = [line]

            if "</channel>" not in line:
                for next_line in text_reader:
                    block.append(next_line)
                    if "</channel>" in next_line:
                        break

            added_by_display_name = False
            for row in block:
                for display_match in DISPLAY_NAME_RE.finditer(row):
                    display_name = html.unescape(display_match.group(1)).strip()
                    norm = normalize_name(display_name)
                    if norm:
                        add_source_id_by_name(name_to_sources, norm, source_id)
                        added_by_display_name = True

            if not added_by_display_name:
                fallback = re.sub(r"\.[a-z]{2}$", "", source_id, flags=re.IGNORECASE)
                fallback = fallback.replace(".", " ")
                add_source_id_by_name(name_to_sources, normalize_name(fallback), source_id)
    finally:
        gzip_stream.close()
        response.close()

    return name_to_sources, channel_count


def build_channel_mapping(
    playlist_entries: List[PlaylistEntry], name_to_sources: Dict[str, List[str]]
) -> Tuple[Dict[str, List[str]], List[PlaylistEntry]]:
    source_to_targets: Dict[str, List[str]] = {}
    unmatched: List[PlaylistEntry] = []

    for entry in playlist_entries:
        candidates = name_to_sources.get(entry.name_norm, [])
        if not candidates:
            unmatched.append(entry)
            continue

        selected = None
        if entry.country:
            suffix = f".{entry.country}"
            for candidate in candidates:
                if candidate.lower().endswith(suffix):
                    selected = candidate
                    break

        if selected is None:
            selected = candidates[0]

        targets = source_to_targets.setdefault(selected, [])
        if entry.tvg_id not in targets:
            targets.append(entry.tvg_id)

    return source_to_targets, unmatched


def write_filtered_epg(url: str, source_to_targets: Dict[str, List[str]], out_path: Path) -> Tuple[int, int]:
    channel_blocks_written = 0
    programme_blocks_written = 0

    response, gzip_stream, reader = open_gzip_text_reader(url)
    text_reader = iter(lambda: reader.readline().decode("utf-8", "replace"), "")

    with out_path.open("w", encoding="utf-8", newline="") as writer:
        try:
            for line in text_reader:
                channel_match = CHANNEL_START_RE.search(line)
                if channel_match:
                    source_id = channel_match.group(1)
                    block: List[str] = [line]

                    if "</channel>" not in line:
                        for next_line in text_reader:
                            block.append(next_line)
                            if "</channel>" in next_line:
                                break

                    targets = source_to_targets.get(source_id)
                    if targets:
                        for target_id in targets:
                            first = re.sub(r'id="[^"]+"', f'id="{target_id}"', block[0], count=1)
                            writer.write(first)
                            for row in block[1:]:
                                writer.write(row)
                            channel_blocks_written += 1
                    continue

                programme_match = PROGRAMME_START_RE.search(line)
                if programme_match:
                    source_id = programme_match.group(1)
                    block = [line]

                    if "</programme>" not in line:
                        for next_line in text_reader:
                            block.append(next_line)
                            if "</programme>" in next_line:
                                break

                    targets = source_to_targets.get(source_id)
                    if targets:
                        for target_id in targets:
                            first = re.sub(
                                r'channel="[^"]+"',
                                f'channel="{target_id}"',
                                block[0],
                                count=1,
                            )
                            writer.write(first)
                            for row in block[1:]:
                                writer.write(row)
                            programme_blocks_written += 1
                    continue

                writer.write(line)
        finally:
            gzip_stream.close()
            response.close()

    return channel_blocks_written, programme_blocks_written


def set_playlist_epg_url(path: Path, epg_url: str) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    if not lines:
        path.write_text(f'#EXTM3U url-tvg="{epg_url}"\n', encoding="utf-8")
        return

    if not lines[0].startswith("#EXTM3U"):
        lines.insert(0, f'#EXTM3U url-tvg="{epg_url}"')
    elif re.search(r'url-tvg="[^"]*"', lines[0]):
        lines[0] = re.sub(r'url-tvg="[^"]*"', f'url-tvg="{epg_url}"', lines[0], count=1)
    else:
        lines[0] = f'{lines[0]} url-tvg="{epg_url}"'

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate local XMLTV EPG mapped to tvg-id values from a playlist."
    )
    parser.add_argument("--playlist-path", default="tv.m3u", help="Path to M3U playlist file.")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL, help="Source XMLTV .xml.gz URL.")
    parser.add_argument("--output-path", default="epg.xml", help="Output XMLTV file path.")
    parser.add_argument(
        "--update-playlist-header",
        action="store_true",
        help="Replace or add url-tvg on playlist header with output filename.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    playlist_path = Path(args.playlist_path)
    output_path = Path(args.output_path)

    entries = parse_playlist_entries(playlist_path)
    if not entries:
        print(f"No channels with tvg-id were found in {playlist_path}", file=sys.stderr)
        return 1

    print(f"Playlist channels with tvg-id: {len(entries)}")
    print(f"Building source channel index from: {args.source_url}")
    name_to_sources, source_channels_count = build_source_index(args.source_url)
    print(f"Source channels indexed: {source_channels_count}")

    source_to_targets, unmatched = build_channel_mapping(entries, name_to_sources)
    matched_targets = sum(len(v) for v in source_to_targets.values())
    print(f"Matched playlist channels: {matched_targets} / {len(entries)}")
    print(f"Unique source channels used: {len(source_to_targets)}")

    if unmatched:
        print("Unmatched channels (first 20):")
        for item in unmatched[:20]:
            print(f" - {item.name} [{item.tvg_id}]")

    print(f"Writing filtered EPG to: {output_path}")
    channels_written, programmes_written = write_filtered_epg(
        args.source_url, source_to_targets, output_path
    )
    print(f"Channel blocks written: {channels_written}")
    print(f"Programme blocks written: {programmes_written}")

    if args.update_playlist_header:
        set_playlist_epg_url(playlist_path, output_path.name)
        print(f"Updated playlist header url-tvg to: {output_path.name}")

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
