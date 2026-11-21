# IPTV playlist: lean UK highlight reel

A short, curated playlist of English-language channels, built for watching from the UK:
BBC, UKTV's free U& channels, UK entertainment favourites, show-specific channels, movies
and a few news channels.

## Playlist URL

```
https://raw.githubusercontent.com/maxmacgregor/iptv/master/tv.m3u
```

TV guide (optional, already referenced inside the playlist):

```
https://raw.githubusercontent.com/maxmacgregor/iptv/master/epg.xml
```

Works with TiviMate, OTT Navigator, VLC, Kodi, Jellyfin, etc.

## How it works

- `channels.txt` is the channel list. Add or remove lines to change the playlist.
  `all/available.txt` lists every name you can use.
- `generate_playlist.py` collects streams for each channel from
  [iptv-org](https://github.com/iptv-org/iptv) (BBC, Samsung TV Plus, Rakuten, Pluto, Xumo, Vizio, Tubi feeds)
  and [Free-TV](https://github.com/Free-TV/IPTV). It only uses official broadcaster and
  free-streaming-service CDNs and ignores restream servers.
- Each candidate stream is played (playlist → variant → segment). The first one that works goes in
  the playlist, preferring UK feeds, then HLS, then higher resolution.
- `STATUS.md` shows what was picked for each channel and what was dropped.
- GitHub Actions rebuilds everything daily and whenever `channels.txt` changes.

Run it locally:

```
python generate_playlist.py            # with stream checks
python generate_playlist.py --no-check # fast, no checks
python list_available_channels.py      # refresh all/available.txt
```

## Legal notice

This repository does not host any video. It only links to streams published by broadcasters and
free ad-supported TV services.
