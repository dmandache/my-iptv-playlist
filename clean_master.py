import re
import sys
import os
import argparse
import unicodedata
from urllib.request import Request, urlopen

SOURCES = {
    "RO": "https://iptv-org.github.io/iptv/countries/ro.m3u",
    "FR": "https://iptv-org.github.io/iptv/countries/fr.m3u",
    "UK": "https://iptv-org.github.io/iptv/countries/uk.m3u",
    "US": "https://iptv-org.github.io/iptv/countries/us.m3u",
}
EPG_URL = "https://iptv-org.github.io/epg/guides.xml"
OUTFILE = "tv.m3u"
KEEP_DEFAULT_DIR = "keep"

# -----------------------------
# Selection rules
# -----------------------------

RULES = {
    "RO": {
        "keep": [
            r"\bTVR\b", r"\bTVR 1\b", r"\bTVR 2\b", r"\bTVR 3\b", r"\bTVR Info\b", r"\bTVR Cultural\b",
            r"\bTVR Craiova\b", r"\bTVR Cluj\b", r"\bTVR Iași\b", r"\bTVR Iasi\b",
            r"\bTVR Timișoara\b", r"\bTVR Timisoara\b", r"\bTVR Târgu Mureș\b", r"\bTVR Targu Mures\b",
            r"\bPro TV\b", r"\bPRO TV\b", r"\bAcasă\b", r"\bAcasa\b",
            r"\bAntena 1\b", r"\bAntena 3\b", r"\bAntena Stars\b",
            r"\bHappy Channel\b", r"\bPrima TV\b", r"\bKanal D\b",
            r"\bNațional TV\b", r"\bNational TV\b",
            r"\bDigi24\b", r"\bRomânia TV\b", r"\bRomania TV\b",
            r"\bRealitatea\b", r"\bB1\b", r"\bEuronews Romania\b",
            r"\bMetropola TV\b", r"\bAleph News\b", r"\bAleph Business\b",
            r"\bAtomic TV\b", r"\bRock TV\b", r"\bEtno TV\b",
            r"\bTaraf TV\b", r"\bFavorit TV\b", r"\bZU TV\b",
            r"\bKiss TV\b", r"\bMagic TV\b", r"\bTrinitas\b", r"\bCredo TV\b",
        ],
        "drop": [
            r"\bTeleshop\b", r"\bShop\b", r"\bPromo\b",
            r"\bLocal\b", r"\bRegional\b", r"\bComunal\b",
            r"\bOradea\b", r"\bArad\b", r"\bBotoșani\b", r"\bBotosani\b",
            r"\bBaia Mare\b", r"\bSuceava\b", r"\bNeamț\b", r"\bNeamt\b",
            r"\bTulcea\b", r"\bBrăila\b", r"\bBraila\b", r"\bGalați\b", r"\bGalati\b",
            r"\bPloiești\b", r"\bPloiesti\b", r"\bBucovina\b", r"\bMaramureș\b", r"\bMaramures\b",
        ],
    },
    "FR": {
        "keep": [
            r"\bTF1\b", r"\bFrance 2\b", r"\bFrance 3\b", r"\bFrance 4\b", r"\bFrance 5\b",
            r"\bM6\b", r"\bArte\b", r"\bC8\b", r"\bW9\b", r"\bTMC\b", r"\bTFX\b",
            r"\b6ter\b", r"\bGulli\b", r"\bLCI\b", r"\bBFM\b", r"\bBFM TV\b", r"\bBFM Business\b",
            r"\bCNews\b", r"\bfranceinfo\b", r"\bPublic Sénat\b", r"\bPublic Senat\b",
            r"\bLCP\b", r"\bTV5Monde\b", r"\bTV5 Monde\b", r"\bFrance 24\b",
            r"\bEuronews\b", r"\bRMC\b", r"\bRTL9\b", r"\bParis Première\b", r"\bParis Premiere\b",
        ],
        "drop": [
            r"\bAlsace\b", r"\bGrand-Est\b", r"\bNormandie\b", r"\bBretagne\b", r"\bOccitanie\b",
            r"\bProvence\b", r"\bMarseille\b", r"\bLyon\b", r"\bToulouse\b", r"\bMontpellier\b",
            r"\bBordeaux\b", r"\bNantes\b", r"\bNice\b", r"\bLille\b", r"\bLocal\b", r"\bRégion\b", r"\bRegion\b",
            r"\bTeleshopping\b", r"\bShopping\b", r"\bBFM (DICI|Grand|Toulon|Alpes|Littoral)\b",
        ],
    },
    "UK": {
        "keep": [
            r"\bBBC One\b", r"\bBBC Two\b", r"\bBBC Three\b", r"\bBBC Four\b", r"\bBBC News\b",
            r"\bITV1\b", r"\bITV2\b", r"\bChannel 4\b", r"\bChannel 5\b",
            r"\bSky News\b", r"\bGB News\b", r"\bTalkTV\b", r"\bCBBC\b", r"\bCBeebies\b",
            r"\bEuronews\b", r"\bBloomberg\b", r"\bReuters\b",
        ],
        "drop": [
            r"\bLocal\b", r"\bShopping\b", r"\bRed Button\b", r"\bBBC RB\b", r"\bUHD\b",
            r"\bParliament\b", r"\bPersian\b", r"\bPashto\b", r"\bAlba\b",
            r"\bEast\b", r"\bWest\b", r"\bNorth\b", r"\bSouth\b",
            r"\bMidlands\b", r"\bYorks\b", r"\bYorkshire\b", r"\bLondon\b",
            r"\bScotland\b", r"\bWales\b", r"\bNorthern Ireland\b", r"\bCumbria\b", r"\bLincolnshire\b",
            r"\bManchester\b", r"\bLiverpool\b", r"\bBristol\b", r"\bLeeds\b",
        ],
    },
    "US": {
        "keep": [
            r"\bCNN\b", r"\bCNN International\b", r"\bNBC News NOW\b",
            r"\bABC News Live\b", r"\bCBS News 24/7\b", r"\bFOX Weather\b",
            r"\bBloomberg TV\b", r"\bReuters TV\b", r"\bPBS National\b",
            r"\bNewsmax\b", r"\bCourt TV\b", r"\bCheddar News\b",
            r"\bScripps News\b", r"\bLiveNOW from FOX\b", r"\bNASA\b",
        ],
        "drop": [
            r"\bCalifornia\b", r"\bTexas\b", r"\bFlorida\b", r"\bArizona\b", r"\bOhio\b",
            r"\bSeattle\b", r"\bChicago\b", r"\bPhiladelphia\b", r"\bLos Angeles\b", r"\bNew York\b",
            r"\bPublic Access\b", r"\bCity\b", r"\bCounty\b", r"\bShopping\b", r"\bTeleshop\b",
            r"\bReligious\b", r"\bChurch\b",
            r"\bABC News Live [0-9]+\b", r"\bCBS News (Baltimore|Bay Area|Boston|Colorado|Detroit|Miami|Minnesota|Pittsburgh|Sacramento)\b",
            r"\bPluto\b", r"\bPlex\b", r"\bSamsung TV Plus\b", r"\bRoku\b", r"\bFilmRise\b",
            r"\bParamount\b", r"\bAMC\b", r"\bION\b", r"\bHallmark\b", r"\bMST3K\b",
        ],
    },
}

# Hard caps keep UK/US from dominating the final playlist.
COUNTRY_LIMITS = {
    "RO": 80,
    "FR": 40,
    "UK": 22,
    "US": 22,
}

# Order matters: earlier patterns get higher score in `priority_score`.
PRIORITY_PATTERNS = {
    "RO": [
        r"\bTVR 1\b", r"\bTVR 2\b", r"\bTVR 3\b", r"\bTVR Info\b",
        r"\bPro TV\b", r"\bAntena 1\b", r"\bDigi24\b", r"\bRomânia TV\b", r"\bRomania TV\b",
    ],
    "FR": [
        r"\bTF1\b", r"\bFrance 2\b", r"\bFrance 3\b", r"\bM6\b", r"\bFrance 24\b", r"\bArte\b",
    ],
    "UK": [
        r"\bBBC News\b", r"\bBBC One\b", r"\bBBC Two\b", r"\bBBC Three\b", r"\bBBC Four\b",
        r"\bITV1\b", r"\bChannel 4\b", r"\bChannel 5\b", r"\bSky News\b", r"\bGB News\b",
        r"\bTalkTV\b", r"\bCBBC\b", r"\bCBeebies\b",
    ],
    "US": [
        r"\bCNN International\b", r"\bCNN\b", r"\bNBC News NOW\b", r"\bABC News Live\b", r"\bCBS News 24/7\b",
        r"\bFOX Weather\b", r"\bBloomberg TV\b", r"\bReuters TV\b", r"\bScripps News\b",
        r"\bLiveNOW from FOX\b", r"\bCourt TV\b", r"\bNewsmax\b",
    ],
}

# Optional display-name fixes applied after stripping quality tags.
CANONICAL_NAMES = {
    "TVR Iasi": "TVR Iași",
    "TVR Timisoara": "TVR Timișoara",
    "TVR Targu Mures": "TVR Târgu Mureș",
    "Romania TV": "România TV",
    "Public Senat": "Public Sénat",
    "BBC News HD": "BBC News",
    "CNN International HD": "CNN International",
}

# -----------------------------
# Helpers
# -----------------------------

def download_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_m3u(text: str):
    lines = [line.rstrip("\n") for line in text.splitlines()]
    entries = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            # A logical entry is #EXTINF metadata followed by the next non-comment URL line.
            extinf = line
            url = ""
            j = i + 1
            while j < len(lines):
                nxt = lines[j].strip()
                if nxt and not nxt.startswith("#"):
                    url = nxt
                    break
                j += 1
            if url:
                _, name, has_name = split_extinf(extinf)
                if not has_name or not name:
                    name = "Unknown"
                entries.append((extinf, name, url))
                i = j
        i += 1
    return entries


def split_extinf(extinf: str):
    # Channel title starts after the first comma that is outside quoted attributes.
    in_quotes = False
    for idx, ch in enumerate(extinf):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            return extinf[:idx], extinf[idx + 1 :].strip(), True
    return extinf, "", False


def matches_any(text: str, patterns):
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def quality_rank(name: str, extinf: str = ""):
    # Use both display name and EXTINF metadata: many feeds expose quality in tvg-id (@HD/@SD).
    text = f"{name} {extinf}".upper()

    if re.search(r"\b(UHD|2160P)\b", text):
        return 5
    if re.search(r"\b(FHD|1080P)\b", text):
        return 4
    if re.search(r"\b(HD|720P)\b", text):
        return 3
    if re.search(r"\b(SD|576P|540P|480P|360P|240P)\b", text):
        return 1
    return 2


def clean_name(name: str) -> str:
    cleaned = name.strip()

    # Remove repeated trailing tags like [Geo-blocked], (1080p), (HD), etc.
    # Keep looping because some sources append multiple suffix blocks.
    while True:
        updated = re.sub(r"\s+\[[^\]]+\]\s*$", "", cleaned)
        updated = re.sub(r"\s+\((SD|HD|FHD|UHD|HEVC|\d{3,4}p)\)\s*$", "", updated, flags=re.I)
        updated = re.sub(r"\s+\b(SD|HD|FHD|UHD|HEVC)\b\s*$", "", updated, flags=re.I)
        if updated == cleaned:
            break
        cleaned = updated.strip()

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return CANONICAL_NAMES.get(cleaned, cleaned)


def fold_diacritics(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def normalize_key(country: str, name: str) -> str:
    # Normalize accents/case/spacing first so matching is stable across sources.
    n = fold_diacritics(clean_name(name)).lower()
    n = re.sub(r"\s+", " ", n).strip()

    if country == "UK":
        # Collapse UK regional/variant naming into one canonical channel key.
        n = re.sub(r"\bbbc one\b.*", "bbc one", n)
        n = re.sub(r"\bbbc two\b.*", "bbc two", n)
        n = re.sub(r"\bbbc three\b.*", "bbc three", n)
        n = re.sub(r"\bbbc four\b.*", "bbc four", n)
        n = re.sub(r"\bitv\s*1?\b.*", "itv1", n)
        n = re.sub(r"\bchannel 4\b.*", "channel 4", n)
        n = re.sub(r"\bchannel 5\b.*", "channel 5", n)

    if country == "US":
        # Collapse numbered/localized US variants into one canonical key.
        n = re.sub(r"\babc news live(?:\s+\d+)?\b.*", "abc news live", n)
        n = re.sub(r"\bcbs news 24/7\b.*", "cbs news 24/7", n)
        n = re.sub(r"\bbloomberg tv\b.*", "bloomberg tv", n)
        n = re.sub(r"\breuters tv\b.*", "reuters tv", n)
        n = re.sub(r"\bpbs national\b.*", "pbs national", n)

    n = re.sub(r"[^a-z0-9]+", "", n)
    return f"{country}:{n}"


def normalize_keep_key(name: str) -> str:
    n = fold_diacritics(clean_name(name)).lower()
    n = re.sub(r"\s+", " ", n).strip()
    return n


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build cleaned RO/FR/UK/US playlist."
    )
    parser.add_argument(
        "--keep-dir",
        nargs="?",
        const=KEEP_DEFAULT_DIR,
        help="Use keep files from DIR (default when flag is set without value: keep).",
    )
    return parser.parse_args()


def load_keep_entries(keep_dir: str, country_code: str):
    path = os.path.join(keep_dir, f"{country_code}.txt")
    if not os.path.isfile(path):
        return None

    requested = []
    seen = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            raw = line.strip()
            if not raw or raw.startswith("#"):
                continue
            key = normalize_keep_key(raw)
            if not key or key in seen:
                continue
            seen.add(key)
            requested.append((raw, key))
    return requested


def priority_score(country: str, name: str) -> int:
    # Higher score means earlier in that country's priority list.
    patterns = PRIORITY_PATTERNS.get(country, [])
    for idx, pattern in enumerate(patterns):
        if re.search(pattern, name, flags=re.IGNORECASE):
            return len(patterns) - idx
    return 0


def rewrite_group(extinf: str, new_group: str):
    if 'group-title="' in extinf:
        return re.sub(r'group-title="[^"]*"', f'group-title="{new_group}"', extinf)
    return extinf.replace("#EXTINF:-1 ", f'#EXTINF:-1 group-title="{new_group}" ', 1)


def rewrite_name(extinf: str, new_name: str):
    prefix, _, has_name = split_extinf(extinf)
    if has_name:
        return prefix + "," + new_name
    return extinf


def choose_entries(country_code: str, entries):
    rules = RULES[country_code]
    best = {}

    for extinf, name, url in entries:
        cname = clean_name(name)
        # Keep if it matches include rules, unless explicitly excluded.
        if not matches_any(cname, rules["keep"]):
            continue
        if matches_any(cname, rules["drop"]):
            continue

        key = normalize_key(country_code, cname)
        item = (
            priority_score(country_code, cname),
            quality_rank(name, extinf),
            extinf,
            cname,
            url,
        )
        # Deduplicate by normalized key; prefer higher priority, then better quality.
        if key not in best or item[:2] > best[key][:2]:
            best[key] = item

    out = []
    # Stable ordering: priority first, then quality, then alphabetic name.
    ordered = sorted(best.values(), key=lambda x: (-x[0], -x[1], x[3].lower()))
    for _, _, extinf, cname, url in ordered:
        extinf = rewrite_group(extinf, country_code)
        extinf = rewrite_name(extinf, cname)
        out.append((extinf, url))

    limit = COUNTRY_LIMITS.get(country_code)
    # Final guard rail so one country cannot dominate the merged playlist.
    if limit and len(out) > limit:
        out = out[:limit]
    return out


def choose_entries_from_keep(country_code: str, entries, requested):
    best = {}

    for extinf, name, url in entries:
        cname = clean_name(name)
        key = normalize_keep_key(cname)
        item = (quality_rank(name, extinf), extinf, cname, url)
        if key not in best or item[0] > best[key][0]:
            best[key] = item

    selected = []
    missing = []
    for raw_name, keep_key in requested:
        item = best.get(keep_key)
        if not item:
            missing.append(raw_name)
            continue

        _, extinf, cname, url = item
        extinf = rewrite_group(extinf, country_code)
        extinf = rewrite_name(extinf, cname)
        selected.append((extinf, url))

    summary = {
        "requested": len(requested),
        "matched": len(selected),
        "missing": missing,
    }
    return selected, summary


# -----------------------------
# Build master playlist
# -----------------------------

def main():
    args = parse_args()
    final_entries = []
    counts = {}
    keep_stats = {}

    if args.keep_dir and not os.path.isdir(args.keep_dir):
        print(f"Warning: keep directory '{args.keep_dir}' not found. Using regex rules for all countries.")

    for country_code, url in SOURCES.items():
        text = download_text(url)
        entries = parse_m3u(text)

        keep_entries = None
        if args.keep_dir and os.path.isdir(args.keep_dir):
            keep_entries = load_keep_entries(args.keep_dir, country_code)

        if keep_entries is not None:
            cleaned, summary = choose_entries_from_keep(country_code, entries, keep_entries)
            keep_stats[country_code] = summary
        else:
            cleaned = choose_entries(country_code, entries)

        counts[country_code] = len(cleaned)
        final_entries.extend(cleaned)

    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write(f'#EXTM3U url-tvg="{EPG_URL}"\n')
        for extinf, url in final_entries:
            f.write(extinf + "\n")
            f.write(url + "\n")

    total = sum(counts.values())
    print(f"Wrote {OUTFILE}")
    print(f"RO: {counts.get('RO', 0)}")
    print(f"FR: {counts.get('FR', 0)}")
    print(f"UK: {counts.get('UK', 0)}")
    print(f"US: {counts.get('US', 0)}")
    print(f"Total: {total}")

    if keep_stats:
        print("Keep-file summary:")
        for country_code in SOURCES:
            stats = keep_stats.get(country_code)
            if not stats:
                continue
            print(
                f"{country_code}: requested={stats['requested']}, "
                f"matched={stats['matched']}, missing={len(stats['missing'])}"
            )
            if stats["missing"]:
                print(f"  Missing: {', '.join(stats['missing'])}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error:", e)
        sys.exit(1)
