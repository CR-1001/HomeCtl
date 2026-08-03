# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
Spotify Connect service. Low-level API access, token management, data classes.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import services.fileaccess as fa
import services.state as state

log = logging.getLogger(__name__)

_config: dict = {}
_tokens_path: str | None = None

# Playlist cache: playlist_id -> frozenset of track URIs
_playlist_cache: dict[str, frozenset] = {}
_cache_lock     = threading.Lock()
_cache_valid    = False
_cache_building = False

_user_id: str = ""
_user_id_lock = threading.Lock()

# Liked-track write-through cache: track_id -> bool
_liked_cache: dict[str, bool] = {}
_liked_lock = threading.Lock()

# Hot cache: live playback data refreshed by background thread
_hot_cache: dict = {
    "player":          None,
    "queue":           None,
    "devices":         None,
    "recently_played": None,
    "player_ts":       0.0,    # timestamp when player state was last fetched
    "seek_pos":        None,   # optimistic seek override position (ms), cleared after 3s
    "seek_ts":         0.0,    # when the seek was issued
}
_hot_cache_lock  = threading.Lock()
_hot_cache_event = threading.Event()    # set to wake the refresh thread early

# Browse cache: per-ID/query data with configurable TTL
_browse_cache: dict[str, tuple] = {}    # key -> (data, timestamp)
_browse_cache_lock = threading.Lock()

SPOTIFY_API      = "https://api.spotify.com/v1"
SPOTIFY_ACCOUNTS = "https://accounts.spotify.com"
SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing "
    "user-library-read "
    "user-library-modify "
    "user-read-recently-played "
    "playlist-read-private "
    "playlist-modify-public "
    "playlist-modify-private"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Artist:
    id:   str
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass
class Track:
    id:           str
    uri:          str
    name:         str
    duration_ms:  int
    artists:      list[Artist]
    album_name:   str = ""
    album_id:     str = ""
    track_number: int = 0

    def __str__(self) -> str:
        return self.name


@dataclass
class Episode:
    id:           str
    uri:          str
    name:         str
    duration_ms:  int
    release_date: str = ""
    show_name:    str = ""
    show_id:      str = ""

    def __str__(self) -> str:
        return self.name


@dataclass
class Album:
    id:           str
    uri:          str
    name:         str
    total_tracks: int
    artists:      list[Artist]
    release_date: str = ""
    album_type:   str = ""

    def __str__(self) -> str:
        return self.name


@dataclass
class Playlist:
    id:           str
    uri:          str
    name:         str
    total_tracks: int

    def __str__(self) -> str:
        return self.name


@dataclass
class Show:
    id:             str
    uri:            str
    name:           str
    total_episodes: int

    def __str__(self) -> str:
        return self.name


@dataclass
class Device:
    id:             str
    name:           str
    is_active:      bool
    volume_percent: int | None = None

    def __str__(self) -> str:
        return self.name


@dataclass
class PlayerState:
    item:         Track | Episode | None
    is_playing:   bool
    is_episode:   bool
    progress_ms:  int
    device:       Device | None
    shuffle:      bool
    repeat:       str           # "off" | "track" | "context"
    context_type: str = ""
    context_uri:  str = ""

    # convenience: raw dict so the viewmodel can still read arbitrary fields
    _raw: dict = field(default_factory=dict, repr=False, compare=False)

    def __str__(self) -> str:
        name = str(self.item) if self.item else "nothing"
        status = "playing" if self.is_playing else "paused"
        return f"{name} ({status})"


@dataclass
class SearchResults:
    artists:   list[Artist]   = field(default_factory=list)
    albums:    list[Album]    = field(default_factory=list)
    playlists: list[Playlist] = field(default_factory=list)
    shows:     list[Show]     = field(default_factory=list)
    tracks:    list[Track]    = field(default_factory=list)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

def init(config: dict) -> None:
    global _config, _tokens_path
    _config = config
    _tokens_path = fa.share_path(["sound", "tokens.json"])
    os.makedirs(os.path.dirname(_tokens_path), exist_ok=True)
    warm_cache()
    _start_hot_cache_thread()


# ---------------------------------------------------------------------------
# OAuth / token management
# ---------------------------------------------------------------------------

def login_url() -> str:
    """Return Spotify authorization URL for the OAuth redirect."""
    params = {
        "client_id":     _config["client_id"],
        "response_type": "code",
        "redirect_uri":  _config["redirect_uri"],
        "scope":         SCOPES,
    }
    return f"{SPOTIFY_ACCOUNTS}/authorize?{urllib.parse.urlencode(params)}"


def exchange_code(code: str) -> bool:
    """Exchange authorization code for access + refresh tokens."""
    data = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  _config["redirect_uri"],
        "client_id":     _config["client_id"],
        "client_secret": _config["client_secret"],
    }).encode()
    req = urllib.request.Request(
        f"{SPOTIFY_ACCOUNTS}/api/token", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            _save_tokens(json.loads(resp.read()))
            return True
    except Exception as e:
        log.error(f"Spotify token exchange failed: {e}")
        return False


def is_authenticated() -> bool:
    return bool(_load_tokens().get("refresh_token"))


def _save_tokens(data: dict) -> None:
    data["expiry"] = time.time() + data.get("expires_in", 3600) - 60
    existing = _load_tokens()
    existing.update(data)
    with open(_tokens_path, "w") as f:
        json.dump(existing, f)


def _load_tokens() -> dict:
    try:
        with open(_tokens_path) as f:
            return json.load(f)
    except Exception:
        return {}


def _refresh_token() -> str | None:
    tokens  = _load_tokens()
    refresh = tokens.get("refresh_token")
    if not refresh:
        return None
    data = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": refresh,
        "client_id":     _config["client_id"],
        "client_secret": _config["client_secret"],
    }).encode()
    req = urllib.request.Request(
        f"{SPOTIFY_ACCOUNTS}/api/token", data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            if "refresh_token" not in result:
                result["refresh_token"] = refresh
            _save_tokens(result)
            return result["access_token"]
    except Exception as e:
        log.error(f"Spotify token refresh failed: {e}")
        return None


def _get_token() -> str | None:
    tokens = _load_tokens()
    if tokens.get("access_token") and time.time() < tokens.get("expiry", 0):
        return tokens["access_token"]
    return _refresh_token()


# ---------------------------------------------------------------------------
# Raw HTTP helper
# ---------------------------------------------------------------------------

def _api(method: str, path: str, body: dict = None, _retry: bool = True,
         _silent: frozenset = frozenset()) -> dict | None:
    token = _get_token()
    if not token:
        return None
    url  = f"{SPOTIFY_API}{path}"
    data = json.dumps(body).encode() if body is not None else b""
    req  = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            content = resp.read()
            if not (content and content.strip()):
                return {}
            try:
                return json.loads(content)
            except ValueError:
                return {}
    except urllib.error.HTTPError as e:
        if e.code == 204:
            return {}
        if e.code in _silent:
            return None
        if e.code == 429 and _retry:
            retry_after = int(e.headers.get("Retry-After", "2"))
            if retry_after > 60:
                log.warning(f"Spotify rate-limited ({method} {path}), Retry-After={retry_after}s — skipping retry")
                return None
            log.warning(f"Spotify rate-limited ({method} {path}), retrying in {retry_after}s")
            time.sleep(retry_after + 0.5)
            return _api(method, path, body, _retry=False)
        log.error(f"Spotify API {method} {path}: {e.code} {e.read().decode(errors='replace')}")
        return None
    except (ValueError, urllib.error.URLError) as e:
        log.error(f"Spotify API {method} {path}: {e}")
        return None


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_artists(raw: list) -> list[Artist]:
    return [Artist(id=a.get("id", ""), name=a.get("name", ""))
            for a in (raw or []) if a.get("name")]


def _parse_track(raw: dict) -> Track | None:
    if not raw or not raw.get("uri"):
        return None
    album = raw.get("album") or {}
    return Track(
        id           = raw.get("id", ""),
        uri          = raw.get("uri", ""),
        name         = raw.get("name", ""),
        duration_ms  = raw.get("duration_ms", 0),
        artists      = _parse_artists(raw.get("artists")),
        album_name   = album.get("name", ""),
        album_id     = album.get("id", ""),
        track_number = raw.get("track_number", 0),
    )


def _parse_episode(raw: dict) -> Episode | None:
    if not raw or not raw.get("uri"):
        return None
    show = raw.get("show") or {}
    return Episode(
        id           = raw.get("id", ""),
        uri          = raw.get("uri", ""),
        name         = raw.get("name", ""),
        duration_ms  = raw.get("duration_ms", 0),
        release_date = raw.get("release_date", ""),
        show_name    = show.get("name", ""),
        show_id      = show.get("id", ""),
    )


def _parse_album(raw: dict) -> Album | None:
    if not raw or not raw.get("id"):
        return None
    return Album(
        id           = raw.get("id", ""),
        uri          = raw.get("uri", ""),
        name         = raw.get("name", ""),
        total_tracks = raw.get("total_tracks", 0),
        artists      = _parse_artists(raw.get("artists")),
        release_date = raw.get("release_date", ""),
        album_type   = raw.get("album_type", ""),
    )


def _parse_playlist(raw: dict) -> Playlist | None:
    if not raw or not raw.get("id"):
        return None
    return Playlist(
        id           = raw.get("id", ""),
        uri          = raw.get("uri", ""),
        name         = raw.get("name", ""),
        total_tracks = (raw.get("tracks") or {}).get("total", 0),
    )


def _parse_show(raw: dict) -> Show | None:
    if not raw or not raw.get("id"):
        return None
    return Show(
        id             = raw.get("id", ""),
        uri            = raw.get("uri", ""),
        name           = raw.get("name", ""),
        total_episodes = raw.get("total_episodes", 0),
    )


def _parse_device(raw: dict) -> Device | None:
    if not raw or not raw.get("id"):
        return None
    return Device(
        id             = raw.get("id", ""),
        name           = raw.get("name", ""),
        is_active      = raw.get("is_active", False),
        volume_percent = raw.get("volume_percent"),
    )


# ---------------------------------------------------------------------------
# Player state
# ---------------------------------------------------------------------------

def get_player() -> PlayerState:
    with _hot_cache_lock:
        cached = _hot_cache["player"]
    if cached is not None:
        return cached
    player = _fetch_player()
    with _hot_cache_lock:
        _hot_cache["player"]    = player
        _hot_cache["player_ts"] = time.time()
    return player


def get_devices() -> list[Device]:
    with _hot_cache_lock:
        cached = _hot_cache["devices"]
    if cached is not None:
        return cached
    devices = _fetch_devices()
    with _hot_cache_lock:
        _hot_cache["devices"] = devices
    return devices


def get_player_cache_ts() -> float:
    """Return the timestamp (time.time()) when the player state was last fetched."""
    with _hot_cache_lock:
        return _hot_cache["player_ts"]


# ---------------------------------------------------------------------------
# Playback control
# ---------------------------------------------------------------------------

def pause() -> None:
    _api("PUT", "/me/player/pause")
    _invalidate_hot_cache()


def resume() -> None:
    _api("PUT", "/me/player/play")
    _invalidate_hot_cache()


def next_track() -> None:
    _api("POST", "/me/player/next")
    time.sleep(0.5)
    _invalidate_hot_cache()


def prev_track() -> None:
    _api("POST", "/me/player/previous")
    time.sleep(0.5)
    _invalidate_hot_cache()


def seek(pos_ms: int) -> None:
    _api("PUT", f"/me/player/seek?position_ms={max(0, pos_ms)}")
    # Record the expected position rather than invalidating the cache.
    # Invalidation causes a sync-fetch that races with the background thread;
    # the background thread can overwrite the cache with the pre-seek Spotify
    # state before the autoupdate fires.  The override below is applied by
    # _refresh_hot_fast() for 3 s, by which time Spotify always catches up.
    with _hot_cache_lock:
        t = time.time()
        _hot_cache["seek_pos"]  = pos_ms
        _hot_cache["seek_ts"]   = t
        _hot_cache["player_ts"] = t  # anchor server-side interpolation to seek time


def set_volume(vol: int) -> None:
    v = max(0, min(100, vol))
    _api("PUT", f"/me/player/volume?volume_percent={v}")
    _invalidate_hot_cache()


def set_shuffle(on: bool) -> None:
    _api("PUT", f"/me/player/shuffle?state={'true' if on else 'false'}")
    _invalidate_hot_cache()


def set_repeat(mode: str) -> None:
    if mode not in ("track", "context", "off"):
        mode = "off"
    _api("PUT", f"/me/player/repeat?state={mode}")
    _invalidate_hot_cache()


def transfer(device_id: str, keep_playing: bool = True) -> None:
    state.set("sound.device_id", device_id)
    _api("PUT", "/me/player", {"device_ids": [device_id], "play": keep_playing})
    _invalidate_hot_cache()


def play(uri: str = "", device_id: str = "", shuffle: str = "", offset: int = -1) -> None:
    """Start playback of a URI (track, album, artist, playlist, show)."""
    body: dict = {}
    if uri:
        if uri.startswith("spotify:track:") or uri.startswith("spotify:episode:"):
            body["uris"] = [uri]
        else:
            body["context_uri"] = uri
    if offset >= 0 and body.get("context_uri"):
        body["offset"] = {"position": offset}

    # Resolve device: provided -> active -> last-used -> first available
    if not device_id:
        devices = get_devices()
        active  = next((d for d in devices if d.is_active), None)
        if active:
            device_id = active.id
        else:
            last_id   = state.get("sound.device_id")
            preferred = next((d for d in devices if d.id == last_id), None) if last_id else None
            chosen    = preferred or (devices[0] if devices else None)
            if chosen:
                device_id = chosen.id
                _api("PUT", "/me/player", {"device_ids": [device_id], "play": False})
                time.sleep(0.3)

    if device_id:
        state.set("sound.device_id", device_id)

    if body.get("context_uri"):
        dev_param = f"&device_id={device_id}" if device_id else ""
        _api("PUT", f"/me/player/repeat?state=context{dev_param}")

    # Turn shuffle ON before play so Spotify starts at a random position
    if shuffle == "on":
        dev_param = f"&device_id={device_id}" if device_id else ""
        _api("PUT", f"/me/player/shuffle?state=true{dev_param}")
        time.sleep(0.15)

    if device_id:
        _api("PUT", f"/me/player/play?device_id={device_id}", body)
    else:
        _api("PUT", "/me/player/play", body)

    if shuffle == "on":
        # Toggle off->on after play to reseed the upcoming queue order
        dev_param = f"&device_id={device_id}" if device_id else ""
        time.sleep(0.15)
        _api("PUT", f"/me/player/shuffle?state=false{dev_param}")
        time.sleep(0.15)
        _api("PUT", f"/me/player/shuffle?state=true{dev_param}")
    elif shuffle == "off":
        dev_param = f"&device_id={device_id}" if device_id else ""
        _api("PUT", f"/me/player/shuffle?state=false{dev_param}")

    time.sleep(0.3)
    _invalidate_hot_cache()


def add_to_queue(uri: str) -> None:
    _api("POST", f"/me/player/queue?uri={urllib.parse.quote(uri)}")
    _invalidate_hot_cache()


def flush_queue() -> None:
    """Skip through every track in the user queue to effectively clear it.

    The Spotify API has no delete-queue endpoint, and GET /me/player/queue
    returns at most 20 items per call.  This loop keeps skipping and
    re-fetching until the queue is empty.

    A small per-skip delay avoids triggering Spotify rate-limiting on rapid
    successive next-track calls.  A hard iteration cap guards against an
    infinite loop if rate-limits still cause skips to fail silently.
    """
    _MAX_ROUNDS = 10  # safety cap: handles up to 10 × 20 = 200 queued tracks
    for _ in range(_MAX_ROUNDS):
        tracks = _fetch_queue()
        if not tracks:
            break
        for _ in tracks:
            _api("POST", "/me/player/next")
            time.sleep(0.1)  # pace requests to avoid 429 rate-limiting
        time.sleep(0.8)  # let the player settle before re-fetching
    _invalidate_hot_cache()


def get_queue() -> list[Track]:
    with _hot_cache_lock:
        cached = _hot_cache["queue"]
    if cached is not None:
        return cached
    queue = _fetch_queue()
    with _hot_cache_lock:
        _hot_cache["queue"] = queue
    return queue


def get_recently_played(limit: int = 5) -> list[tuple[Track, str]]:
    """Return list of (Track, played_at_iso) newest first."""
    with _hot_cache_lock:
        cached = _hot_cache["recently_played"]
    if cached is not None:
        return cached
    result = _fetch_recently_played(limit)
    with _hot_cache_lock:
        _hot_cache["recently_played"] = result
    return result


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

def _track_id(uri: str) -> str:
    """Extract Spotify track ID from a URI (spotify:track:ID) or return as-is."""
    return uri.split(":")[-1] if ":" in uri else uri


def _get_user_id() -> str:
    global _user_id
    with _user_id_lock:
        if _user_id:
            return _user_id
    data = _api("GET", "/me") or {}
    uid = data.get("id", "")
    with _user_id_lock:
        _user_id = uid
    return uid


def _fetch_my_playlists() -> list[Playlist]:
    data  = _api("GET", "/me/playlists?limit=50") or {}
    items = [_parse_playlist(r) for r in (data.get("items") or []) if r]
    return sorted([p for p in items if p], key=lambda p: p.name.lower())


def get_my_playlists() -> list[Playlist]:
    return _browse_get("my_playlists", _fetch_my_playlists, _config.get("cache_ttl_s", 300))


def is_track_liked(track_uri: str) -> bool:
    tid = _track_id(track_uri)
    if not tid:
        return False
    with _liked_lock:
        if tid in _liked_cache:
            return _liked_cache[tid]
    result = _api("GET", f"/me/tracks/contains?ids={tid}") or []
    liked = bool(result[0]) if result else False
    with _liked_lock:
        _liked_cache[tid] = liked
    return liked


def like_track(track_uri: str) -> None:
    tid = _track_id(track_uri)
    if tid:
        result = _api("PUT", "/me/tracks", body={"ids": [tid]})
        if result is not None:
            with _liked_lock:
                _liked_cache[tid] = True


def unlike_track(track_uri: str) -> None:
    tid = _track_id(track_uri)
    if tid:
        result = _api("DELETE", "/me/tracks", body={"ids": [tid]})
        if result is not None:
            with _liked_lock:
                _liked_cache[tid] = False


def create_playlist(name: str) -> Playlist | None:
    user_id = _get_user_id()
    if not user_id:
        return None
    data = _api("POST", f"/users/{user_id}/playlists",
                body={"name": name, "public": False}) or {}
    pl = _parse_playlist(data)
    if pl:
        with _cache_lock:
            _playlist_cache[pl.id] = frozenset()
        with _browse_cache_lock:
            _browse_cache.pop("my_playlists", None)
    return pl


def delete_playlist(playlist_id: str) -> None:
    _api("DELETE", f"/playlists/{playlist_id}/followers")
    with _cache_lock:
        _playlist_cache.pop(playlist_id, None)
    with _browse_cache_lock:
        _browse_cache.pop("my_playlists", None)
        _browse_cache.pop(f"playlist:{playlist_id}", None)


def _fetch_my_shows() -> list[Show]:
    data  = _api("GET", "/me/shows?limit=50") or {}
    items = [_parse_show((e or {}).get("show") or {}) for e in (data.get("items") or [])]
    return sorted([s for s in items if s], key=lambda s: s.name.lower())


def get_my_shows() -> list[Show]:
    return _browse_get("my_shows", _fetch_my_shows, _config.get("cache_ttl_s", 300))


def _build_playlist_cache() -> None:
    """Fetch all track URIs for every user playlist and store in the cache."""
    global _cache_valid, _cache_building
    with _cache_lock:
        if _cache_building:
            return
        _cache_building = True
    try:
        playlists = get_my_playlists()
        new_cache: dict[str, frozenset] = {}
        for pl in playlists:
            uris: set[str] = set()
            offset = 0
            while True:
                time.sleep(0.15)  # pace requests to avoid 429 rate limiting
                raw   = _api("GET",
                    f"/playlists/{pl.id}/tracks"
                    f"?fields=items(track(uri)),next&limit=50&offset={offset}") or {}
                for item in (raw.get("items") or []):
                    uri = ((item.get("track") or {}).get("uri") or "")
                    if uri:
                        uris.add(uri)
                if not raw.get("next"):
                    break
                offset += 50
            new_cache[pl.id] = frozenset(uris)
        with _cache_lock:
            _playlist_cache.clear()
            _playlist_cache.update(new_cache)
            _cache_valid = True
    except Exception as e:
        log.error(f"Playlist cache build failed: {e}")
    finally:
        with _cache_lock:
            _cache_building = False


def _ensure_cache() -> None:
    """Wait until cache is valid, building synchronously if not already started."""
    if _cache_valid:
        return
    with _cache_lock:
        already_building = _cache_building
    if not already_building:
        _build_playlist_cache()
        return
    # Background build in progress — poll until done (up to 30 s)
    for _ in range(150):
        time.sleep(0.2)
        if _cache_valid:
            return


def warm_cache() -> None:
    """Start a background cache build if the cache is not already valid or building."""
    with _cache_lock:
        if _cache_valid or _cache_building:
            return
    threading.Thread(target=_build_playlist_cache, daemon=True).start()


# ---------------------------------------------------------------------------
# Hot cache: background refresh thread
# ---------------------------------------------------------------------------

def _fetch_player() -> PlayerState:
    raw = _api("GET", "/me/player?additional_types=episode") or {}
    item_raw   = raw.get("item") or {}
    is_episode = raw.get("currently_playing_type", "") == "episode"
    item: Track | Episode | None
    if is_episode:
        item = _parse_episode(item_raw)
    else:
        item = _parse_track(item_raw)
    dev_raw = raw.get("device") or {}
    device  = _parse_device(dev_raw) if dev_raw else None
    context = raw.get("context") or {}
    return PlayerState(
        item         = item,
        is_playing   = raw.get("is_playing", False),
        is_episode   = is_episode,
        progress_ms  = raw.get("progress_ms") or 0,
        device       = device,
        shuffle      = raw.get("shuffle_state", False),
        repeat       = raw.get("repeat_state", "off"),
        context_type = context.get("type", ""),
        context_uri  = context.get("uri", ""),
        _raw         = raw,
    )


def _fetch_devices() -> list[Device]:
    data = _api("GET", "/me/player/devices") or {}
    return [d for d in (_parse_device(r) for r in (data.get("devices") or [])) if d]


def _fetch_queue() -> list[Track]:
    data = _api("GET", "/me/player/queue") or {}
    return [t for t in (_parse_track(r) for r in (data.get("queue") or [])) if t]


def _fetch_recently_played(limit: int = 5) -> list[tuple[Track, str]]:
    data   = _api("GET", f"/me/player/recently-played?limit={limit}") or {}
    result = []
    for e in (data.get("items") or []):
        track = _parse_track((e or {}).get("track") or {})
        if track:
            result.append((track, (e or {}).get("played_at", "")))
    return result


def _start_hot_cache_thread() -> None:
    threading.Thread(target=_hot_cache_loop, daemon=True).start()


def _hot_cache_loop() -> None:
    interval_fast = _config.get("cache_interval_s", 5)
    interval_slow = _config.get("cache_interval_slow_s", 30)
    slow_elapsed  = float(interval_slow)   # trigger slow refresh on first pass
    while True:
        _hot_cache_event.clear()
        _refresh_hot_fast()
        slow_elapsed += interval_fast
        if slow_elapsed >= interval_slow:
            _refresh_hot_slow()
            slow_elapsed = 0.0
        _hot_cache_event.wait(timeout=interval_fast)


def _refresh_hot_fast() -> None:
    player = _fetch_player()
    ts     = time.time()
    queue  = _fetch_queue()
    with _hot_cache_lock:
        seek_pos = _hot_cache["seek_pos"]
        seek_ts  = _hot_cache["seek_ts"]
        if seek_pos is not None:
            age = ts - seek_ts
            if age <= 3.0:
                if player is not None:
                    # Spotify hasn't reflected the seek yet — apply expected position
                    player.progress_ms = (
                        seek_pos + int(age * 1000) if player.is_playing else seek_pos
                    )
            else:
                _hot_cache["seek_pos"] = None   # Spotify has caught up; stop overriding
        _hot_cache["player"]    = player
        _hot_cache["player_ts"] = ts
        _hot_cache["queue"]     = queue


def _refresh_hot_slow() -> None:
    devices         = _fetch_devices()
    recently_played = _fetch_recently_played()
    with _hot_cache_lock:
        _hot_cache["devices"]         = devices
        _hot_cache["recently_played"] = recently_played


def _invalidate_hot_cache() -> None:
    """Clear hot cache entries and wake the background thread for a prompt refresh.
    Note: seek() does NOT call this — it uses a seek_pos override instead, to avoid
    a race where the thread re-fetches before Spotify reflects the new position.
    player_ts is preserved so JS interpolation keeps working during the re-fetch window.
    """
    with _hot_cache_lock:
        _hot_cache["player"]          = None
        _hot_cache["queue"]           = None
        _hot_cache["devices"]         = None
        _hot_cache["recently_played"] = None
    _hot_cache_event.set()  # wake the background thread for a prompt refresh


def get_track_playlists(track_uri: str) -> set[str]:
    """Returns the set of playlist IDs containing the track (uses cache)."""
    _ensure_cache()
    with _cache_lock:
        return {pl_id for pl_id, uris in _playlist_cache.items() if track_uri in uris}


def add_track_to_playlist(playlist_id: str, track_uri: str) -> None:
    _api("POST", f"/playlists/{playlist_id}/tracks", body={"uris": [track_uri]})
    with _cache_lock:
        if playlist_id in _playlist_cache:
            _playlist_cache[playlist_id] = _playlist_cache[playlist_id] | {track_uri}


def remove_track_from_playlist(playlist_id: str, track_uri: str) -> None:
    _api("DELETE", f"/playlists/{playlist_id}/tracks",
         body={"tracks": [{"uri": track_uri}]})
    with _cache_lock:
        if playlist_id in _playlist_cache:
            _playlist_cache[playlist_id] = _playlist_cache[playlist_id] - {track_uri}


def get_all_album_tracks(album_id: str) -> list[Track]:
    """Fetch every track for an album, paginating until complete."""
    tracks = []
    offset = 0
    while True:
        page, has_more = get_album_tracks(album_id, offset=offset, limit=50)
        tracks.extend(page)
        if not has_more:
            break
        offset += 50
    return tracks


def get_album_track_playlists(track_uris: list[str]) -> set[str]:
    """Returns playlist IDs where ALL of the given track URIs are present (uses cache)."""
    if not track_uris:
        return set()
    uri_set = frozenset(track_uris)
    _ensure_cache()
    with _cache_lock:
        return {pl_id for pl_id, uris in _playlist_cache.items() if uri_set <= uris}


def add_tracks_to_playlist(playlist_id: str, track_uris: list[str]) -> None:
    """Add multiple tracks to a playlist, batching in groups of 100."""
    for i in range(0, len(track_uris), 100):
        _api("POST", f"/playlists/{playlist_id}/tracks",
             body={"uris": track_uris[i:i + 100]})
    with _cache_lock:
        if playlist_id in _playlist_cache:
            _playlist_cache[playlist_id] = _playlist_cache[playlist_id] | frozenset(track_uris)


def remove_tracks_from_playlist(playlist_id: str, track_uris: list[str]) -> None:
    """Remove multiple tracks from a playlist, batching in groups of 100."""
    for i in range(0, len(track_uris), 100):
        batch = [{"uri": u} for u in track_uris[i:i + 100]]
        _api("DELETE", f"/playlists/{playlist_id}/tracks", body={"tracks": batch})
    with _cache_lock:
        if playlist_id in _playlist_cache:
            _playlist_cache[playlist_id] = _playlist_cache[playlist_id] - frozenset(track_uris)


# ---------------------------------------------------------------------------
# Browse cache helper
# ---------------------------------------------------------------------------

def _browse_get(key: str, fetch_fn, ttl: float):
    """Return cached browse data if fresh, otherwise call fetch_fn() and cache the result."""
    now = time.time()
    with _browse_cache_lock:
        entry = _browse_cache.get(key)
        if entry is not None:
            data, ts = entry
            if now - ts < ttl:
                return data
    result = fetch_fn()
    with _browse_cache_lock:
        _browse_cache[key] = (result, time.time())
    return result


# ---------------------------------------------------------------------------
# Search & browse
# ---------------------------------------------------------------------------

def search(q: str) -> SearchResults:
    raw     = _api("GET", f"/search?q={urllib.parse.quote(q)}&type=track,album,artist,playlist,show&limit=20") or {}
    artists = [Artist(id=a.get("id", ""), name=a.get("name", ""))
               for a in ((raw.get("artists") or {}).get("items") or [])
               if a and a.get("id")]
    albums  = [a for a in (_parse_album(r)    for r in ((raw.get("albums")    or {}).get("items") or [])
                           if r and r.get("type") == "album") if a]
    pls     = [p for p in (_parse_playlist(r) for r in ((raw.get("playlists") or {}).get("items") or [])
                           if r and r.get("type") == "playlist") if p]
    shows   = [s for s in (_parse_show(r)     for r in ((raw.get("shows")     or {}).get("items") or [])) if s]
    tracks  = [t for t in (_parse_track(r)    for r in ((raw.get("tracks")    or {}).get("items") or [])) if t]
    return SearchResults(artists=artists, albums=albums, playlists=pls, shows=shows, tracks=tracks)


def _fetch_artist(artist_id: str) -> Artist | None:
    raw = _api("GET", f"/artists/{artist_id}") or {}
    if not raw.get("id"):
        return None
    return Artist(id=raw["id"], name=raw.get("name", ""))


def get_artist(artist_id: str) -> Artist | None:
    return _browse_get(f"artist:{artist_id}", lambda: _fetch_artist(artist_id),
                       _config.get("cache_ttl_s", 300))


def _fetch_artist_albums(artist_id: str) -> list[Album]:
    data  = _api("GET", f"/artists/{artist_id}/albums?include_groups=album,single&limit=20") or {}
    items = [_parse_album(r) for r in (data.get("items") or []) if r]
    return sorted([a for a in items if a],
                  key=lambda a: a.release_date, reverse=True)


def get_artist_albums(artist_id: str) -> list[Album]:
    return _browse_get(f"artist_albums:{artist_id}", lambda: _fetch_artist_albums(artist_id),
                       _config.get("cache_ttl_s", 300))


def _fetch_album(album_id: str) -> Album | None:
    return _parse_album(_api("GET", f"/albums/{album_id}") or {})


def get_album(album_id: str) -> Album | None:
    return _browse_get(f"album:{album_id}", lambda: _fetch_album(album_id),
                       _config.get("cache_ttl_s", 300))


def _fetch_album_tracks(album_id: str, offset: int, limit: int) -> tuple[list[Track], bool]:
    data     = _api("GET", f"/albums/{album_id}/tracks?offset={offset}&limit={limit}") or {}
    tracks   = [t for t in (_parse_track(r) for r in (data.get("items") or [])) if t]
    has_more = bool(data.get("next"))
    return tracks, has_more


def get_album_tracks(album_id: str, offset: int = 0, limit: int = 20) -> tuple[list[Track], bool]:
    return _browse_get(f"album_tracks:{album_id}:{offset}:{limit}",
                       lambda: _fetch_album_tracks(album_id, offset, limit),
                       _config.get("cache_ttl_s", 300))


def _fetch_playlist(playlist_id: str) -> Playlist | None:
    raw = _api("GET", f"/playlists/{playlist_id}?fields=id,name,uri,tracks(total)") or {}
    return _parse_playlist(raw)


def get_playlist(playlist_id: str) -> Playlist | None:
    return _browse_get(f"playlist:{playlist_id}", lambda: _fetch_playlist(playlist_id),
                       _config.get("cache_ttl_s", 300))


def _fetch_playlist_tracks(playlist_id: str, offset: int, limit: int) -> tuple[list[Track], bool]:
    data  = _api("GET", f"/playlists/{playlist_id}/tracks"
                        f"?offset={offset}&limit={limit}"
                        f"&fields=items(track(id,uri,name,duration_ms,artists)),next") or {}
    tracks = []
    for entry in (data.get("items") or []):
        if not entry:
            continue
        t = _parse_track((entry or {}).get("track") or {})
        if t:
            tracks.append(t)
    has_more = bool(data.get("next"))
    return tracks, has_more


def get_playlist_tracks(playlist_id: str, offset: int = 0, limit: int = 20) -> tuple[list[Track], bool]:
    return _browse_get(f"playlist_tracks:{playlist_id}:{offset}:{limit}",
                       lambda: _fetch_playlist_tracks(playlist_id, offset, limit),
                       _config.get("cache_ttl_s", 300))


def _fetch_show(show_id: str) -> Show | None:
    return _parse_show(_api("GET", f"/shows/{show_id}?additional_types=episode") or {})


def get_show(show_id: str) -> Show | None:
    return _browse_get(f"show:{show_id}", lambda: _fetch_show(show_id),
                       _config.get("cache_ttl_s", 300))


def _fetch_show_episodes(show_id: str, offset: int, limit: int) -> tuple[list[Episode], bool]:
    data     = _api("GET", f"/shows/{show_id}/episodes?offset={offset}&limit={limit}") or {}
    episodes = [e for e in (_parse_episode(r) for r in (data.get("items") or [])) if e]
    has_more = bool(data.get("next"))
    return episodes, has_more


def get_show_episodes(show_id: str, offset: int = 0, limit: int = 20) -> tuple[list[Episode], bool]:
    return _browse_get(f"show_episodes:{show_id}:{offset}:{limit}",
                       lambda: _fetch_show_episodes(show_id, offset, limit),
                       _config.get("cache_ttl_s", 300))


def _fetch_context_name(ctx_type: str, ctx_id: str) -> str:
    raw = _api("GET", f"/{ctx_type}s/{ctx_id}") or {}
    return raw.get("name", "")


def get_context_name(ctx_type: str, ctx_id: str) -> str:
    """Fetch display name for a playback context (playlist or artist)."""
    return _browse_get(f"context:{ctx_type}:{ctx_id}",
                       lambda: _fetch_context_name(ctx_type, ctx_id),
                       _config.get("cache_ttl_s", 300))


def find_radio_playlist(album_id: str = "", playlist_id: str = "") -> str | None:
    """Return URI of a radio playlist for the primary artist, or None."""
    artist_name = ""
    if album_id:
        album = get_album(album_id)
        if album and album.artists:
            artist_name = album.artists[0].name
    elif playlist_id:
        data = _api("GET", f"/playlists/{playlist_id}/tracks?limit=5&fields=items(track(artists))") or {}
        for entry in (data.get("items") or []):
            t       = (entry or {}).get("track") or {}
            artists = _parse_artists(t.get("artists"))
            if artists:
                artist_name = artists[0].name
                break
    if not artist_name:
        return None
    q       = urllib.parse.quote(f"{artist_name} radio")
    results = _api("GET", f"/search?q={q}&type=playlist&limit=5") or {}
    pls     = (results.get("playlists") or {}).get("items") or []
    return next((p["uri"] for p in pls if p and p.get("uri")), None)


def get_track(track_id: str) -> Track | None:
    """Fetch a single track by ID (full object, includes album info)."""
    return _parse_track(_api("GET", f"/tracks/{track_id}") or {})


def get_related_artists(artist_id: str) -> list[Artist]:
    """Return up to 20 artists that Spotify considers related to the given artist.

    NOTE: The /artists/{id}/related-artists endpoint was removed by Spotify in
    late 2024.  Calls return 404; this function silences that error and returns
    an empty list so callers degrade gracefully.
    """
    data = _api("GET", f"/artists/{artist_id}/related-artists",
                _silent=frozenset({404})) or {}
    return [Artist(id=a.get("id", ""), name=a.get("name", ""))
            for a in (data.get("artists") or [])
            if a and a.get("id")]


def get_artist_top_tracks(artist_id: str) -> list[Track]:
    """Return up to 10 top tracks for an artist (uses the user's market via OAuth token)."""
    data = _api("GET", f"/artists/{artist_id}/top-tracks?market=from_token") or {}
    return [t for t in (_parse_track(r) for r in (data.get("tracks") or [])) if t]
