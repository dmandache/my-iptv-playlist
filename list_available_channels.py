import argparse
import os
import re
import sys
import unicodedata
from urllib.request import Request, urlopen

SOURCES = {
    "RO": "https://iptv-org.github.io/iptv/countries/ro.m3u",
    "FR": "https://iptv-org.github.io/iptv/countries/fr.m3u",
    "UK": "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "US": "https://iptv-org.github.io/iptv/countries/us.m3u",
}
ALL_DEFAULT_DIR = "all"


def download_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_m3u(text: str):
    lines = [line.rstrip("\n") for line in text.splitlines()]
    entries = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            info = line
            url = ""
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith("#"):
                    url = nxt
                    break
                j += 1
            if url:
                _, name = split_extinf(info)
                entries.append((name, url))
                i = j
        i += 1

    return entries


def split_extinf(extinf: str):
    # EXTINF channel title starts after the first comma that is not inside quotes.
    in_quotes = False
    for idx, ch in enumerate(extinf):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            return extinf[:idx], extinf[idx + 1 :].strip()
    return extinf, "Unknown"


def clean_name(name: str) -> str:
    cleaned = name.strip()
    while True:
        updated = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        updated = re.sub(r"\s+\((SD|HD|FHD|UHD|HEVC|\d{3,4}p)\)\s*$", "", updated, flags=re.I)
        updated = re.sub(r"\s+\b(SD|HD|FHD|UHD|HEVC)\b\s*$", "", updated, flags=re.I)
        if updated == cleaned:
            break
        cleaned = updated.strip()

    return re.sub(r"\s{2,}", " ", cleaned).strip()


def fold_diacritics(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def normalize_keep_key(name: str) -> str:
    n = fold_diacritics(clean_name(name)).lower()
    return re.sub(r"\s+", " ", n).strip()


def build_template_names(channels):
    deduped = {}
    for name, _ in channels:
        cleaned = clean_name(name)
        key = normalize_keep_key(cleaned)
        if key and key not in deduped:
            deduped[key] = cleaned
    return sorted(deduped.values(), key=lambda x: x.lower())


def write_keep_template(output_dir: str, country: str, names):
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, f"{country}.txt")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f"# Keep list for {country}\n")
        fh.write("# One channel name per line. Lines starting with # are ignored.\n")
        fh.write("# Remove channels you do not want to keep.\n")
        for name in names:
            fh.write(name + "\n")
    print(f"Wrote {path} ({len(names)} channels)")


def print_country(country: str, channels, with_urls: bool):
    print(f"\n=== {country} ({len(channels)} channels) ===")
    if not channels:
        print("No channels found.")
        return

    idx_width = len(str(len(channels)))
    for idx, (name, url) in enumerate(channels, start=1):
        print(f"{idx:>{idx_width}}. {name}")
        if with_urls:
            print(f"{' ' * (idx_width + 3)}{url}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Display all available channels grouped by country."
    )
    parser.add_argument(
        "--country",
        nargs="+",
        choices=sorted(SOURCES.keys()),
        help="Only print selected countries (example: --country RO FR).",
    )
    parser.add_argument(
        "--with-urls",
        action="store_true",
        help="Print stream URLs under each channel name.",
    )
    parser.add_argument(
        "--export-keep-template",
        nargs="?",
        const=ALL_DEFAULT_DIR,
        metavar="DIR",
        help="Export one keep template file per country into DIR (default: keep).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    countries = args.country if args.country else list(SOURCES.keys())

    for country in countries:
        text = download_text(SOURCES[country])
        channels = parse_m3u(text)

        if args.export_keep_template:
            template_names = build_template_names(channels)
            write_keep_template(args.export_keep_template, country, template_names)
        else:
            printable = [(clean_name(name), url) for name, url in channels]
            printable.sort(key=lambda x: x[0].lower())
            print_country(country, printable, args.with_urls)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Error:", exc)
        sys.exit(1)
