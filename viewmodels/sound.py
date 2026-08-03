# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
View-model for the Sound module. Spotify playback UI via the Connect API.
"""

from __future__ import annotations

from datetime import datetime, timezone
import random
import time

import services.meta as m
import services.soundctl as sctl
import services.soundrec as srec

_PAGE_SIZE = 20


def init(config: dict) -> None:
    sctl.init(config)


# ---------------------------------------------------------------------------
# Presentation helpers
# ---------------------------------------------------------------------------

def _fmt_ms(ms: int) -> str:
    s = ms // 1000
    return f"{s // 60}:{s % 60:02d}"


def _fmt_duration(ms: int) -> str:
    s = ms // 1000
    m_, s = divmod(s, 60)
    h, m_ = divmod(m_, 60)
    if h:
        return f"{h}:{m_:02d}:{s:02d}"
    return f"{m_}:{s:02d}"


# ---------------------------------------------------------------------------
# Form builders
# ---------------------------------------------------------------------------

def _now_form(player: sctl.PlayerState = None, devices: list = None) -> m.form:
    if player is None:
        player = sctl.get_player()
    if devices is None:
        devices = sctl.get_devices()
    item        = player.item
    is_playing  = player.is_playing
    is_episode  = player.is_episode
    device      = player.device
    vol         = device.volume_percent if device else None
    shuffle     = player.shuffle
    repeat      = player.repeat
    progress_ms = player.progress_ms
    _cache_ts   = sctl.get_player_cache_ts()
    if player.is_playing and _cache_ts > 0:
        progress_ms = player.progress_ms + int((time.time() - _cache_ts) * 1000)

    if item is not None or (is_episode and is_playing):
        track_name = item.name if item else "podcast"
        if is_episode:
            show_name   = item.show_name if item else ""
            show_id     = item.show_id   if item else ""
            artist_list = []
            album_name  = show_name
            album_id    = ""
        else:
            artist_list = item.artists    if item else []
            album_name  = item.album_name if item else ""
            album_id    = item.album_id   if item else ""

        fields = []
        if artist_list:
            by_row = [m.label("\u00a0by\u00a0", style="small inactive")]
            for a in artist_list:
                if a.id:
                    by_row.append(m.execute_params("sound/browse_artist", a.name, params={"artist_id": a.id}))
                elif a.name:
                    by_row.append(m.label(a.name))
            fields.append(m.actions(by_row))
        if is_episode:
            if show_name:
                on_row = [m.label("\u00a0on\u00a0", style="small inactive")]
                if show_id:
                    on_row.append(m.execute_params("sound/browse_show", show_name, params={"show_id": show_id}))
                else:
                    on_row.append(m.label(show_name))
                fields.append(m.actions(on_row))
        elif album_name:
            on_row = [m.label("\u00a0on\u00a0", style="small inactive")]
            if album_id:
                on_row.append(m.execute_params("sound/browse_album", album_name, params={"album_id": album_id}))
            else:
                on_row.append(m.label(album_name))
            fields.append(m.actions(on_row))

        ctx_type = player.context_type
        ctx_uri  = player.context_uri
        _ctx_browse = {
            "playlist": ("sound/browse_playlist", "playlist_id"),
            "artist":   ("sound/browse_artist",   "artist_id"),
        }
        if ctx_type in _ctx_browse and ctx_uri:
            ctx_id      = ctx_uri.split(":")[-1]
            func, param = _ctx_browse[ctx_type]
            ctx_name    = sctl.get_context_name(ctx_type, ctx_id)
            if ctx_name:
                fields.append(m.actions([
                    m.label("\u00a0context\u00a0", style="small inactive"),
                    m.execute_params(func, ctx_name, params={param: ctx_id}),
                ]))

        duration_ms = item.duration_ms if item else 0
        if duration_ms or is_episode:
            seek_row = [
                m.execute_params("sound/seek", "start", params={"pos_ms": 0}),
                m.execute_params("sound/seek", "\u221215s",  params={"pos_ms": max(0, progress_ms - 15000)}),
            ]
            if not duration_ms or duration_ms > 300000:
                seek_row.append(m.execute_params("sound/seek", "\u22121m", params={"pos_ms": max(0, progress_ms - 60000)}))
            if not duration_ms or duration_ms > 1500000:
                seek_row.append(m.execute_params("sound/seek", "\u22125m", params={"pos_ms": max(0, progress_ms - 300000)}))
            seek_row.append(m.space(1))
            _render_ts = time.time()
            _interp = f"{progress_ms},{duration_ms},{int(player.is_playing)},{_render_ts:.3f}"
            if duration_ms:
                seek_row.append(m.label(f"{_fmt_ms(progress_ms)} / {_fmt_ms(duration_ms)}", key="sound_progress_time", data=_interp))
            else:
                seek_row.append(m.label(_fmt_ms(progress_ms), key="sound_progress_time", data=_interp))
            seek_row.append(m.space(1))
            if not duration_ms or duration_ms > 1500000:
                seek_row.append(m.execute_params("sound/seek", "+5m", params={"pos_ms": progress_ms + 300000}))
            if not duration_ms or duration_ms > 300000:
                seek_row.append(m.execute_params("sound/seek", "+1m", params={"pos_ms": progress_ms + 60000}))
            seek_row.append(m.execute_params("sound/seek", "+15s", params={"pos_ms": progress_ms + 15000}))
            fields += [m.space(1), m.actions(seek_row)]

        device_name  = device.name if device else ""
        shuffle_text = "shuffled" if shuffle else "ordered"
        repeat_text  = {"context": "repeat", "track": "repeat one", "off": "no repeat"}.get(repeat, "no repeat")
        if device_name:
            device_row = [
                m.label("device\u00a0", style="small inactive"),
                m.label(device_name, style="glow-a"),
                m.label("\u00a0mode\u00a0", style="small inactive"),
                m.label(f"{shuffle_text}\u00a0\u00b7\u00a0{repeat_text}"),
                m.label("\u00a0"),
                m.execute("sound/devices_form", "change"),
            ]
            fields.append(m.actions(device_row))
        if not is_episode and item and item.uri:
            _by = ", ".join(a.name for a in artist_list if a.name)
            save_row = [
                m.execute_params("sound/save_form", "save",
                                 params={"track_uri": item.uri, "track_name": track_name, "by": _by}),
            ]
            if sctl.is_track_liked(item.uri):
                save_row.append(m.label("liked", style="small inactive"))
            save_row.append(m.execute_params("sound/queue_similar", "queue 10 related tracks",
                                             params={"track_id": item.id}))
            fields.append(m.actions(save_row))
        fields.append(m.autoupdate("sound/live_form", delay=2000))
        return m.form("sound_now", track_name, fields, open=True, table=False, style="back-3 container-1")
    else:
        idle_fields = [m.label("nothing playing")]
        idle_fields.append(m.autoupdate("sound/live_form", delay=2000))
        return m.form("sound_now", "playing", idle_fields, open=True, table=False, style="back-3 container-1")


def devices_form(player: sctl.PlayerState = None, devices: list = None) -> m.form:
    if player is None:
        player = sctl.get_player()
    if devices is None:
        devices = sctl.get_devices()
    sorted_devs = sorted(devices, key=lambda d: (not d.is_active, d.name.lower())) if devices else []
    fields = [
        *[
            m.execute_params("sound/transfer", d.name, params={"device_id": d.id})
            for d in sorted_devs
        ],
        m.space(1),
        m.actions([
            m.execute_params("sound/set_shuffle", "shuffled", params={"shuffle": "on"}),
            m.execute_params("sound/set_shuffle", "ordered",  params={"shuffle": "off"}),
        ]),
        m.space(1),
        m.actions([
            m.execute_params("sound/set_repeat", "repeat",     params={"repeat": "context"}),
            m.execute_params("sound/set_repeat", "repeat one", params={"repeat": "track"}),
            m.execute_params("sound/set_repeat", "no repeat",  params={"repeat": "off"}),
        ]),
    ]
    return m.form("_popup", "devices", fields, open=True, table=False)


def _header_form(player: sctl.PlayerState = None) -> m.header:
    if player is None:
        player = sctl.get_player()
    item       = player.item
    is_playing = player.is_playing
    if not item:
        return m.header([m.autoupdate("sound/header_form", delay=2000)])
    vol = player.device.volume_percent if player.device else None
    row = [
        m.execute("sound/prev_track", "<"),
        m.execute("sound/pause" if is_playing else "sound/resume",
                  "stop" if is_playing else "play", important=True),
        m.execute("sound/next_track", ">"),
        m.label("\u00a0"),
    ]
    if vol is not None:
        row += [
            m.execute_params("sound/set_volume", "\u2212", params={"vol": max(0, vol - 5)}),
            m.label(f"{vol}%", style="action"),
            m.execute_params("sound/set_volume", "+", params={"vol": min(100, vol + 5)}),
        ]
    fields = [
        m.actions(row),
        m.autoupdate("sound/header_form", delay=2000),
    ]
    return m.header(fields)


def favorites_form() -> m.form:
    rows = []
    for pl in sctl.get_my_playlists():
        count = f"{pl.total_tracks} tracks" if pl.total_tracks else ""
        rows.append([
            m.label("playlist", style="small inactive"),
            m.label(count, style="small inactive"),
            m.execute_params("sound/play_playlist", "play",
                             params={"playlist_id": pl.id, "uri": pl.uri, "shuffle": "on"}),
            m.execute_params("sound/browse_playlist", "open", params={"playlist_id": pl.id}),
            m.label("\u00a0" + pl.name, style="glow-a"),
        ])
    for show in sctl.get_my_shows():
        count = f"{show.total_episodes} episodes" if show.total_episodes else ""
        rows.append([
            m.label("show", style="small inactive"),
            m.label(count, style="small inactive"),
            m.execute_params("sound/play_show", "play",
                             params={"show_id": show.id, "uri": show.uri, "shuffle": "off"}),
            m.execute_params("sound/browse_show", "open", params={"show_id": show.id}),
            m.label("\u00a0" + show.name, style="glow-a"),
        ])
    manage_btn = m.actions([m.execute("sound/manage_playlists_form", "manage")])
    if not rows:
        return m.form("_popup", "favorites", [manage_btn], open=True, table=False)
    return m.form("_popup", "favorites",
                  [m.table(rows=rows, style="table-2"), m.space(1), manage_btn],
                  open=True, table=False)


def manage_playlists_form():
    playlists = sctl.get_my_playlists()
    playlist_choices = ([m.choice("", text="\u2014 select \u2014")]
                        + [m.choice(pl.id, text=pl.name) for pl in playlists])
    create_fields = [
        m.text("name", "", "playlist name"),
        m.execute("sound/create_playlist", "create"),
        m.space(2),
    ]
    delete_fields = [
        m.select("playlist_id", playlist_choices),
        m.execute("sound/delete_playlist", "delete",
                  confirm="Delete this playlist? This cannot be undone."),
    ]
    fields = [
        m.collapsible("create", create_fields),
        m.collapsible("delete", delete_fields),
    ]
    return [m.form("_popup", "manage playlists", fields, open=True, table=False)]


def create_playlist(name: str = ""):
    name = name.strip()
    if name:
        sctl.create_playlist(name)
    return manage_playlists_form()


def delete_playlist(playlist_id: str = ""):
    if playlist_id:
        sctl.delete_playlist(playlist_id)
    return manage_playlists_form()


def _track_row(item: sctl.Track | sctl.Episode, first_col) -> list:
    artists = item.artists if isinstance(item, sctl.Track) else []
    btns = [
        m.execute_params("sound/browse_artist", a.name, params={"artist_id": a.id}, style="small inactive")
        if a.id else m.label(a.name, style="small inactive")
        for a in artists if a.name
    ]
    _by      = ", ".join(a.name for a in artists if a.name)
    save_btn = m.execute_params("sound/save_form", "save",
                                params={"track_uri": item.uri, "track_name": item.name, "by": _by},
                                style="small")
    if isinstance(item, sctl.Track) and item.id:
        similar_btn = m.execute_params("sound/queue_similar", "queue 10 related tracks",
                                       params={"track_id": item.id}, style="small")
        action_col = m.actions([save_btn, similar_btn])
    else:
        action_col = save_btn
    return [first_col, m.label(item.name, style="small"), m.actions(btns) if btns else m.label(""), m.label(""), action_col]


def _queue_form(player: sctl.PlayerState = None) -> m.form:
    if player is None:
        player = sctl.get_player()
    current_uri = player.item.uri if player.item else ""

    recent_entries = [(t, p) for t, p in sctl.get_recently_played(limit=5)
                      if t.uri != current_uri]
    now_utc      = datetime.now(timezone.utc)
    queue_tracks = sctl.get_queue()
    _cache_ts    = sctl.get_player_cache_ts()
    progress_ms  = (player.progress_ms + int((time.time() - _cache_ts) * 1000)
                    if player.is_playing and _cache_ts > 0 else player.progress_ms)
    remaining_ms = max(0, (player.item.duration_ms if player.item else 0) - progress_ms)

    rows = []
    if player.item:
        rows.append(_track_row(player.item, m.label("now", style="glow-a inactive small")))

    if queue_tracks:
        rows.append([m.label("upcoming", style="small inactive"), m.label(""), m.label(""), m.label(""), m.label("")])
        cumulative_ms = remaining_ms
        for track in queue_tracks:
            mins = cumulative_ms // 60000
            rows.append(_track_row(track, m.label(f"+{mins}m", style="small inactive")))
            cumulative_ms += track.duration_ms or 0

    if recent_entries:
        rows.append([m.label("history", style="small inactive"), m.label(""), m.label(""), m.label(""), m.label("")])
        for track, played_at in recent_entries:
            try:
                dt   = datetime.fromisoformat(played_at.replace("Z", "+00:00"))
                mins = max(0, int((now_utc - dt).total_seconds() // 60))
                lbl  = f"-{mins}m"
            except Exception:
                lbl  = ""
            rows.append(_track_row(track, m.label(lbl, style="small inactive")))

    if rows:
        fields = [m.table(rows=rows)]
    else:
        fields = [m.label("empty queue", style="small inactive")]
    if player.is_playing and queue_tracks:
        fields.insert(0, m.execute("sound/skip_next_tracks", "skip next 10 tracks", style="small"))
    fields.append(m.autoupdate("sound/queue_form", delay=5000))
    return m.form("sound_queue", "queue", fields, table=False)


# ---------------------------------------------------------------------------
# Public autoupdate targets
# ---------------------------------------------------------------------------

def now_form():
    return [_now_form()]


def header_form():
    return [_header_form()]


def live_form():
    player = sctl.get_player()
    return [_now_form(player), _header_form(player)]


def queue_form():
    return [_queue_form()]


# ---------------------------------------------------------------------------
# Page controller
# ---------------------------------------------------------------------------

def ctl():
    if not sctl.is_authenticated():
        return [m.view("_body", "sound", [
            m.form("sound_login", "spotify", [
                m.applink(sctl.login_url(), "log in with spotify", prefix=""),
            ])
        ])]
    sctl.warm_cache()
    player  = sctl.get_player()
    devices = sctl.get_devices()
    forms   = [_now_form(player, devices)]
    forms.append(m.form("sound_search", "", [
        m.actions([m.execute("sound/favorites_form", "favorites"), m.execute("sound/search_popup_form", "search")]),
    ], open=True, table=False))
    forms.append(_queue_form(player))
    return [m.view("_body", "sound", forms), _header_form(player)]


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def _search_form(q: str = "", result_fields: list = None) -> list:
    search_fields = [
        m.text("q", q, "song, artist, album, ..."),
        m.execute("sound/search", "query"),
        m.space(1),
    ]
    if result_fields is None:
        return [m.form("_popup", "search", search_fields, open=True, table=False)]
    return [m.form("_popup", "search", search_fields + [m.space(1)] + result_fields,
                   open=True, table=False)]


def search_popup_form():
    return _search_form()


def search(q: str = "", page: int = 0):
    if not q.strip():
        return _search_form()
    results = sctl.search(q)
    groups  = []

    # Artists
    artist_rows = []
    for a in results.artists:
        artist_rows.append([
            m.label("artist", style="small inactive"),
            m.execute_params("sound/browse_artist", a.name, params={"artist_id": a.id, "q": q}),
        ])
    if artist_rows:
        groups.append(m.table(rows=artist_rows))

    # Albums
    album_rows = []
    for a in results.albums:
        tracks = f"{a.total_tracks} tracks" if a.total_tracks else ""
        album_rows.append([
            m.label("album", style="small inactive"),
            m.label(tracks, style="small inactive"),
            m.execute_params("sound/browse_album", a.name, params={"album_id": a.id, "q": q}),
            m.execute_params("sound/save_album_form", "save",
                             params={"album_id": a.id, "album_name": a.name}, style="small"),
        ])
    if album_rows:
        groups.append(m.table(rows=album_rows))

    # Playlists
    playlist_rows = []
    for p in results.playlists:
        playlist_rows.append([
            m.label("playlist", style="small inactive"),
            m.execute_params("sound/browse_playlist", p.name, params={"playlist_id": p.id, "q": q}),
        ])
    if playlist_rows:
        groups.append(m.table(rows=playlist_rows))

    # Shows
    show_rows = []
    for s in results.shows:
        eps = f"{s.total_episodes} episodes" if s.total_episodes else ""
        show_rows.append([
            m.label("show", style="small inactive"),
            m.label(eps, style="small inactive"),
            m.execute_params("sound/browse_show", s.name, params={"show_id": s.id, "q": q}),
        ])
    if show_rows:
        groups.append(m.table(rows=show_rows))

    # Tracks
    track_rows = []
    for t in results.tracks:
        artist_btns = [
            m.execute_params("sound/browse_artist", a.name,
                             params={"artist_id": a.id, "q": q}, style="small inactive")
            if a.id else m.label(a.name, style="small inactive")
            for a in t.artists if a.name
        ]
        track_rows.append([
            m.label("track", style="small inactive"),
            m.label(_fmt_duration(t.duration_ms) if t.duration_ms else "", style="small inactive"),
            m.execute_params("sound/queue_track", "queue", params={"uri": t.uri, "name": t.name}),
            m.execute_params("sound/play", "play", params={"uri": t.uri}),
            m.label(" " + t.name),
            m.actions(artist_btns) if artist_btns else m.label(""),
            m.execute_params("sound/save_form", "save",
                             params={"track_uri": t.uri, "track_name": t.name,
                                     "by": ", ".join(a.name for a in t.artists if a.name),
                                     "back_func": "search", "back_q": q},
                             style="small"),
        ])
    if track_rows:
        groups.append(m.table(rows=track_rows))

    if not groups:
        return _search_form(q, [m.label("no results")])
    result_fields = []
    for i, group in enumerate(groups):
        if i > 0:
            result_fields.append(m.space(1))
        result_fields.append(group)
    return _search_form(q, result_fields)


# ---------------------------------------------------------------------------
# Browse
# ---------------------------------------------------------------------------

def browse_artist(artist_id: str = "", q: str = ""):
    if not artist_id:
        return _search_form()
    artist      = sctl.get_artist(artist_id)
    artist_name = artist.name if artist else artist_id
    albums      = sctl.get_artist_albums(artist_id)
    result_fields = [m.actions([
        m.label(artist_name, style="glow-a"),
        m.space(1),
        m.label("artist", style="small inactive"),
    ])]
    nav_row = []
    if q:
        nav_row += [m.execute_params("sound/search", "back to results", params={"q": q}), m.space(1)]
    nav_row.append(m.execute_params("sound/play_artist", "play top songs",
                                    params={"artist_id": artist_id, "q": q}))
    nav_row.append(m.execute_params("sound/queue_similar", "queue 10 related tracks",
                                    params={"artist_id": artist_id}))
    result_fields.append(m.actions(nav_row))
    result_fields.append(m.space(1))
    album_rows = []
    for album in albums:
        album_rows.append([
            m.label(album.album_type, style="small inactive"),
            m.label(album.release_date[:4] if album.release_date else "", style="small inactive"),
            m.execute_params("sound/browse_album", album.name,
                             params={"album_id": album.id, "artist_id": artist_id, "q": q}),
        ])
    if album_rows:
        result_fields.append(m.table(rows=album_rows))
    else:
        result_fields.append(m.label("no albums found"))
    return _search_form(result_fields=result_fields)


def browse_album(album_id: str = "", artist_id: str = "", q: str = "", page: int = 0):
    if not album_id:
        return _search_form()
    try:
        p = max(0, int(page))
    except (ValueError, TypeError):
        p = 0
    album = sctl.get_album(album_id)
    if not album:
        return _search_form()
    album_name = album.name
    uri        = album.uri
    total      = album.total_tracks
    if artist_id:
        artist = next((a for a in album.artists if a.id == artist_id),
                      album.artists[0] if album.artists else None)
    else:
        artist = album.artists[0] if album.artists else None
    artist_id   = artist_id or (artist.id   if artist else "")
    artist_name =               artist.name if artist else ""

    offset           = p * _PAGE_SIZE
    tracks, has_more = sctl.get_album_tracks(album_id, offset=offset, limit=_PAGE_SIZE)

    title_row = [m.label(album_name, style="glow-a")]
    if artist_name or artist_id:
        title_row.append(m.label("\u00a0album by\u00a0", style="small inactive"))
        if artist_id:
            title_row.append(m.execute_params("sound/browse_artist", artist_name or artist_id,
                                              params={"artist_id": artist_id, "q": q}))
        else:
            title_row.append(m.label(artist_name))
    else:
        title_row += [m.space(1), m.label("album", style="small inactive")]
    header_fields = [m.actions(title_row)]
    nav_row = []
    if q:
        nav_row += [m.execute_params("sound/search", "back to results", params={"q": q}), m.space(1)]
    nav_row += [
        m.execute_params("sound/play", "play album", params={"uri": uri}),
        m.space(1),
        m.execute_params("sound/queue_similar", "queue 10 related tracks", params={"album_id": album_id}),
        m.space(1),
        m.execute_params("sound/save_album_form", "save album",
                         params={"album_id": album_id, "album_name": album_name, "q": q}),
    ]
    header_fields.append(m.actions(nav_row))
    header_fields.append(m.space(1))

    track_rows = []
    for track in tracks:
        track_rows.append([
            m.label(str(track.track_number) if track.track_number else "", style="small inactive"),
            m.label(_fmt_duration(track.duration_ms) if track.duration_ms else "", style="small inactive"),
            m.execute_params("sound/queue_track", "queue", params={"uri": track.uri, "name": track.name}),
            m.execute_params("sound/play", "play", params={"uri": track.uri}),
            m.label(" " + track.name),
            m.execute_params("sound/save_form", "save",
                             params={"track_uri": track.uri, "track_name": track.name,
                                     "back_func": "browse_album", "back_id": album_id, "back_q": q},
                             style="small"),
        ])

    footer_fields = []
    if track_rows:
        footer_fields.append(m.table(rows=track_rows))
    else:
        footer_fields.append(m.label(""))
    nav = []
    if total > 2000 and p >= 50:
        nav.append(m.execute_params("sound/browse_album", "jump -1000",
            params={"album_id": album_id, "artist_id": artist_id, "q": q, "page": p - 50}))
    if total > 200 and p >= 5:
        nav.append(m.execute_params("sound/browse_album", "jump -100",
            params={"album_id": album_id, "artist_id": artist_id, "q": q, "page": p - 5}))
    if p > 0:
        nav.append(m.execute_params("sound/browse_album", "prev",
            params={"album_id": album_id, "artist_id": artist_id, "q": q, "page": p - 1}))
    if total and track_rows:
        nav.append(m.label(
            f"\u00a0\u00a0\u00a0\u00a0{offset + 1}\u2013{offset + len(track_rows)} of {total}\u00a0\u00a0\u00a0\u00a0",
            style="small inactive"))
    if has_more:
        nav.append(m.execute_params("sound/browse_album", "next",
            params={"album_id": album_id, "artist_id": artist_id, "q": q, "page": p + 1}))
    if total > 200 and (p + 5) * _PAGE_SIZE < total:
        nav.append(m.execute_params("sound/browse_album", "jump +100",
            params={"album_id": album_id, "artist_id": artist_id, "q": q, "page": p + 5}))
    if total > 2000 and (p + 50) * _PAGE_SIZE < total:
        nav.append(m.execute_params("sound/browse_album", "jump +1000",
            params={"album_id": album_id, "artist_id": artist_id, "q": q, "page": p + 50}))
    if nav:
        footer_fields += [m.actions(nav)]
    return _search_form(result_fields=header_fields + footer_fields)


def browse_playlist(playlist_id: str = "", q: str = "", page: int = 0):
    if not playlist_id:
        return _search_form()
    try:
        p = max(0, int(page))
    except (ValueError, TypeError):
        p = 0
    pl = sctl.get_playlist(playlist_id)
    if not pl:
        return _search_form()
    pl_name  = pl.name
    uri      = pl.uri
    total    = pl.total_tracks
    offset   = p * _PAGE_SIZE
    tracks, has_more = sctl.get_playlist_tracks(playlist_id, offset=offset, limit=_PAGE_SIZE)

    header_fields = [m.actions([
        m.label(pl_name, style="glow-a"),
        m.space(1),
        m.label("playlist", style="small inactive"),
    ])]
    nav_row = []
    if q:
        nav_row += [m.execute_params("sound/search", "back to results", params={"q": q}), m.space(1)]
    nav_row += [
        m.execute_params("sound/play_playlist", "play playlist", params={"uri": uri, "playlist_id": playlist_id, "shuffle": "on"}),
        m.space(1),
        m.execute_params("sound/queue_similar", "queue 10 related tracks",
                         params={"playlist_id": playlist_id}),
    ]
    header_fields.append(m.actions(nav_row))
    header_fields.append(m.space(1))

    track_rows = []
    for track in tracks:
        artist_btns = [
            m.execute_params("sound/browse_artist", a.name,
                             params={"artist_id": a.id, "q": q}, style="small inactive")
            if a.id else m.label(a.name, style="small inactive")
            for a in track.artists if a.name
        ]
        track_rows.append([
            m.label(_fmt_duration(track.duration_ms) if track.duration_ms else "", style="small inactive"),
            m.execute_params("sound/queue_track", "queue", params={"uri": track.uri, "name": track.name}),
            m.execute_params("sound/play", "play", params={"uri": track.uri}),
            m.label(" " + track.name),
            m.actions(artist_btns) if artist_btns else m.label(""),
            m.execute_params("sound/save_form", "save",
                             params={"track_uri": track.uri, "track_name": track.name,
                                     "back_func": "browse_playlist", "back_id": playlist_id, "back_q": q},
                             style="small"),
        ])

    footer_fields = []
    if track_rows:
        footer_fields.append(m.table(rows=track_rows, style="sound-results"))
    else:
        footer_fields.append(m.label(""))
    nav = []
    if total > 2000 and p >= 50:
        nav.append(m.execute_params("sound/browse_playlist", "jump -1000",
            params={"playlist_id": playlist_id, "q": q, "page": p - 50}))
    if total > 200 and p >= 5:
        nav.append(m.execute_params("sound/browse_playlist", "jump -100",
            params={"playlist_id": playlist_id, "q": q, "page": p - 5}))
    if p > 0:
        nav.append(m.execute_params("sound/browse_playlist", "prev",
            params={"playlist_id": playlist_id, "q": q, "page": p - 1}))
    if total and track_rows:
        nav.append(m.label(
            f"\u00a0\u00a0\u00a0\u00a0{offset + 1}\u2013{offset + len(track_rows)} of {total}\u00a0\u00a0\u00a0\u00a0",
            style="small inactive"))
    if has_more:
        nav.append(m.execute_params("sound/browse_playlist", "next",
            params={"playlist_id": playlist_id, "q": q, "page": p + 1}))
    if total > 200 and (p + 5) * _PAGE_SIZE < total:
        nav.append(m.execute_params("sound/browse_playlist", "jump +100",
            params={"playlist_id": playlist_id, "q": q, "page": p + 5}))
    if total > 2000 and (p + 50) * _PAGE_SIZE < total:
        nav.append(m.execute_params("sound/browse_playlist", "jump +1000",
            params={"playlist_id": playlist_id, "q": q, "page": p + 50}))
    if nav:
        footer_fields += [m.actions(nav)]
    return _search_form(result_fields=header_fields + footer_fields)


def browse_show(show_id: str = "", q: str = "", page: int = 0):
    if not show_id:
        return _search_form()
    try:
        p = max(0, int(page))
    except (ValueError, TypeError):
        p = 0
    show = sctl.get_show(show_id)
    if not show:
        return _search_form()
    show_name = show.name
    uri       = show.uri
    total     = show.total_episodes
    offset    = p * _PAGE_SIZE
    episodes, has_more = sctl.get_show_episodes(show_id, offset=offset, limit=_PAGE_SIZE)

    header_fields = [m.actions([
        m.label(show_name, style="glow-a"),
        m.space(1),
        m.label("show", style="small inactive"),
    ])]
    nav_row = []
    if q:
        nav_row += [m.execute_params("sound/search", "back to results", params={"q": q}), m.space(1)]
    if uri:
        nav_row.append(m.execute_params("sound/play", "play show",
                                        params={"uri": uri, "shuffle": "off"}))
    if nav_row:
        header_fields.append(m.actions(nav_row))
    header_fields.append(m.space(1))

    ep_rows = []
    for ep in episodes:
        ep_rows.append([
            m.label(ep.release_date, style="small inactive"),
            m.label(_fmt_ms(ep.duration_ms) if ep.duration_ms else "", style="small inactive"),
            m.execute_params("sound/play", "play", params={"uri": ep.uri}),
            m.label(" " + ep.name),
            m.execute_params("sound/save_form", "save",
                             params={"track_uri": ep.uri, "track_name": ep.name,
                                     "back_func": "browse_show", "back_id": show_id, "back_q": q},
                             style="small"),
        ])

    footer_fields = []
    if ep_rows:
        footer_fields.append(m.table(rows=ep_rows, style="sound-results"))
    else:
        footer_fields.append(m.label(""))
    nav = []
    if total > 2000 and p >= 50:
        nav.append(m.execute_params("sound/browse_show", "jump -1000",
            params={"show_id": show_id, "q": q, "page": p - 50}))
    if total > 200 and p >= 5:
        nav.append(m.execute_params("sound/browse_show", "jump -100",
            params={"show_id": show_id, "q": q, "page": p - 5}))
    if p > 0:
        nav.append(m.execute_params("sound/browse_show", "prev",
            params={"show_id": show_id, "q": q, "page": p - 1}))
    if total and ep_rows:
        nav.append(m.label(
            f"\u00a0\u00a0\u00a0\u00a0{offset + 1}\u2013{offset + len(ep_rows)} of {total}\u00a0\u00a0\u00a0\u00a0",
            style="small inactive"))
    if has_more:
        nav.append(m.execute_params("sound/browse_show", "next",
            params={"show_id": show_id, "q": q, "page": p + 1}))
    if total > 200 and (p + 5) * _PAGE_SIZE < total:
        nav.append(m.execute_params("sound/browse_show", "jump +100",
            params={"show_id": show_id, "q": q, "page": p + 5}))
    if total > 2000 and (p + 50) * _PAGE_SIZE < total:
        nav.append(m.execute_params("sound/browse_show", "jump +1000",
            params={"show_id": show_id, "q": q, "page": p + 50}))
    if nav:
        footer_fields += [m.actions(nav)]
    return _search_form(result_fields=header_fields + footer_fields)


# ---------------------------------------------------------------------------
# Playback control
# ---------------------------------------------------------------------------

def play(uri: str = "", device_id: str = "", shuffle: str = ""):
    sctl.play(uri=uri, device_id=device_id, shuffle=shuffle)
    player = sctl.get_player()
    return [_now_form(player), _header_form(player)]


def play_artist(artist_id: str = "", q: str = ""):
    sctl.play(uri=f"spotify:artist:{artist_id}", shuffle="on")
    return browse_artist(artist_id=artist_id, q=q)


def play_playlist(playlist_id: str = "", uri: str = "", shuffle: str = "on"):
    offset = -1
    if shuffle == "on" and playlist_id:
        pl = sctl.get_playlist(playlist_id)
        total = pl.total_tracks if pl else 0
        offset = random.randint(0, total - 1) if total > 1 else 0
    sctl.play(uri=uri, shuffle=shuffle, offset=offset)
    player = sctl.get_player()
    return [m.form("_popup", "", [], table=False), _now_form(player), _header_form(player)]


def play_show(show_id: str = "", uri: str = "", shuffle: str = "off"):
    sctl.play(uri=uri, shuffle=shuffle)
    player = sctl.get_player()
    return [m.form("_popup", "", [], table=False), _now_form(player), _header_form(player)]


def play_radio(album_id: str = "", playlist_id: str = ""):
    uri = sctl.find_radio_playlist(album_id=album_id, playlist_id=playlist_id)
    if not uri:
        return [m.error("radio: no playlist found"), _now_form()]
    radio_playlist_id = uri.split(":")[-1]
    pl = sctl.get_playlist(radio_playlist_id)
    total = pl.total_tracks if pl else 0
    offset = random.randint(0, total - 1) if total > 1 else 0
    sctl.play(uri=uri, shuffle="on", offset=offset)
    player = sctl.get_player()
    return [_now_form(player), _header_form(player)]


def queue_similar(track_id: str = "", album_id: str = "", artist_id: str = "", playlist_id: str = ""):
    recs   = srec.recommend(track_id=track_id, album_id=album_id, artist_id=artist_id, playlist_id=playlist_id)
    tracks = recs.all_tracks()
    if not tracks:
        return [m.form("_popup", "", [], table=False), _queue_form()]
    random.shuffle(tracks)
    tracks = tracks[:10]
    # Enqueue the rest in order.
    for t in tracks[1:]:
        if t.uri:
            sctl.add_to_queue(t.uri)
    player = sctl.get_player()
    return [m.form("_popup", "", [], table=False), _now_form(player), _header_form(player), _queue_form(player)]


def skip_next_tracks():
    # Skip at most 10 upcoming tracks.
    for _ in sctl.get_queue()[:10]:
        sctl.next_track()
    return [_queue_form()]


def queue_track(uri: str = "", name: str = ""):
    if uri:
        queue    = sctl.get_queue()
        last_uri = queue[-1].uri if queue else ""
        if uri != last_uri:
            sctl.add_to_queue(uri)
    return [_queue_form()]


def pause():
    sctl.pause()
    player            = sctl.get_player()
    player.is_playing = False
    return [_now_form(player)]


def resume():
    sctl.resume()
    player            = sctl.get_player()
    player.is_playing = True
    return [_now_form(player)]


def next_track():
    sctl.next_track()
    player = sctl.get_player()
    return [_now_form(player), _header_form(player), _queue_form(player)]


def prev_track():
    sctl.prev_track()
    player = sctl.get_player()
    return [_now_form(player), _header_form(player), _queue_form(player)]


def seek(pos_ms: int = 0):
    try:
        p = max(0, int(pos_ms))
    except (ValueError, TypeError):
        p = 0
    sctl.seek(p)
    player             = sctl.get_player()
    player.progress_ms = p
    return [_now_form(player)]


def set_volume(vol: int = 50):
    try:
        v = max(0, min(100, int(float(vol))))
    except (ValueError, TypeError):
        v = 50
    sctl.set_volume(v)
    player = sctl.get_player()
    if player.device:
        player.device.volume_percent = v
    return [_header_form(player)]


def transfer(device_id: str = ""):
    if device_id:
        player = sctl.get_player()
        sctl.transfer(device_id, keep_playing=player.is_playing)
        return [m.form("_popup", "", [], table=False), _now_form(player)]
    return [_now_form()]


def set_shuffle(shuffle: str = "off"):
    on = shuffle == "on"
    sctl.set_shuffle(on)
    player         = sctl.get_player()
    player.shuffle = on
    return [m.form("_popup", "", [], table=False), _now_form(player)]


def set_repeat(repeat: str = "off"):
    if repeat not in ("track", "context", "off"):
        repeat = "off"
    sctl.set_repeat(repeat)
    player        = sctl.get_player()
    player.repeat = repeat
    return [m.form("_popup", "", [], table=False), _now_form(player)]


# ---------------------------------------------------------------------------
# Save to playlist
# ---------------------------------------------------------------------------

def save_form(track_uri: str = "", track_name: str = "", by: str = "",
              back_func: str = "", back_id: str = "", back_q: str = ""):
    if not track_uri:
        return [m.form("_popup", "", [], table=False)]
    header = []
    if track_name:
        header.append(m.label(track_name))
    if by:
        header.append(m.actions([m.label("\u00a0by\u00a0", style="small inactive"), m.label(by)]))
    fields = header + [
        m.section([m.label("\u00b7\u00b7\u00b7", style="small inactive")], key="_popup_playlists"),
        m.autoupdate("sound/save_form_load", delay=300,
                     params={"track_uri": track_uri, "track_name": track_name, "by": by,
                             "back_func": back_func, "back_id": back_id, "back_q": back_q}),
    ]
    return [m.form("_popup", "save", fields, open=True, table=False)]


def save_form_load(track_uri: str = "", track_name: str = "", by: str = "",
                   back_func: str = "", back_id: str = "", back_q: str = ""):
    if not track_uri:
        return [m.form("_popup", "", [], table=False)]
    playlists    = sctl.get_my_playlists()
    in_playlists = sctl.get_track_playlists(track_uri)
    values   = [m.choice(pl.id, text=pl.name) for pl in playlists]
    defaults = [m.choice(pl.id, text=pl.name) for pl in playlists if pl.id in in_playlists]
    liked = sctl.is_track_liked(track_uri)
    liked_defaults = [m.choice("1", text="liked")] if liked else []
    back_hidden = []
    if back_func:
        back_hidden.append(m.hidden("back_func", back_func))
    if back_id:
        back_hidden.append(m.hidden("back_id", back_id))
    if back_q:
        back_hidden.append(m.hidden("back_q", back_q))
    return [m.section(
        content=[m.hidden("track_uri", track_uri)] + back_hidden + [
            m.hidden("liked_orig", "1" if liked else ""),
            m.select_many("liked", [m.choice("1", text="liked")], liked_defaults),
            m.space(1),
            m.select_many("playlist_ids", values, defaults),
            m.space(1),
            m.execute("sound/save_playlists", "save"),
        ],
        key="_popup_playlists",
    )]


def save_playlists(track_uri: str = "", playlist_ids: list = None, liked: list = None,
                   liked_orig: str = "",
                   back_func: str = "", back_id: str = "", back_q: str = ""):
    if not track_uri:
        return [m.form("_popup", "", [], table=False)]
    if playlist_ids is None:
        playlist_ids = []
    want_liked = bool(liked)
    was_liked  = liked_orig == "1"
    if want_liked and not was_liked:
        sctl.like_track(track_uri)
    elif not want_liked and was_liked:
        sctl.unlike_track(track_uri)
    current   = sctl.get_track_playlists(track_uri)
    new_set   = set(playlist_ids)
    to_add    = new_set - current
    to_remove = current - new_set
    for pid in to_add:
        sctl.add_track_to_playlist(pid, track_uri)
    for pid in to_remove:
        sctl.remove_track_from_playlist(pid, track_uri)
    if back_func == "browse_album":
        return browse_album(album_id=back_id, q=back_q)
    if back_func == "browse_playlist":
        return browse_playlist(playlist_id=back_id, q=back_q)
    if back_func == "browse_show":
        return browse_show(show_id=back_id, q=back_q)
    if back_func == "search" and back_q:
        return search(q=back_q)
    return [m.form("_popup", "", [], table=False)]


def save_album_form(album_id: str = "", album_name: str = "", q: str = ""):
    if not album_id:
        return [m.form("_popup", "", [], table=False)]
    fields = []
    if album_name:
        fields.append(m.label(album_name))
    fields += [
        m.section([m.label("\u00b7\u00b7\u00b7", style="small inactive")], key="_popup_playlists"),
        m.autoupdate("sound/save_album_form_load", delay=300,
                     params={"album_id": album_id, "q": q}),
    ]
    return [m.form("_popup", "save", fields, open=True, table=False)]


def save_album_form_load(album_id: str = "", q: str = ""):
    if not album_id:
        return [m.form("_popup", "", [], table=False)]
    tracks = sctl.get_all_album_tracks(album_id)
    if not tracks:
        return [m.form("_popup", "", [], table=False)]
    track_uris   = [t.uri for t in tracks]
    playlists    = sctl.get_my_playlists()
    in_playlists = sctl.get_album_track_playlists(track_uris)
    values   = [m.choice(pl.id, text=pl.name) for pl in playlists]
    defaults = [m.choice(pl.id, text=pl.name) for pl in playlists if pl.id in in_playlists]
    track_labels = []
    for t in tracks:
        by_str = ", ".join(a.name for a in t.artists if a.name)
        row = [m.label(t.name, style="small")]
        if by_str:
            row += [m.label("\u00a0by\u00a0", style="small inactive"), m.label(by_str, style="small")]
        track_labels.append(m.actions(row))
    return [m.section(
        content=track_labels + [
            m.hidden("album_id", album_id),
            m.select_many("playlist_ids", values, defaults),
            m.space(1),
            m.execute("sound/save_album_playlists", "save"),
        ],
        key="_popup_playlists",
    )]


def save_album_playlists(album_id: str = "", playlist_ids: list = None):
    if not album_id:
        return [m.form("_popup", "", [], table=False)]
    if playlist_ids is None:
        playlist_ids = []
    tracks = sctl.get_all_album_tracks(album_id)
    if not tracks:
        return [m.form("_popup", "", [], table=False)]
    track_uris = [t.uri for t in tracks]
    current    = sctl.get_album_track_playlists(track_uris)
    new_set    = set(playlist_ids)
    to_add     = new_set - current
    to_remove  = current - new_set
    for pid in to_add:
        sctl.add_tracks_to_playlist(pid, track_uris)
    for pid in to_remove:
        sctl.remove_tracks_from_playlist(pid, track_uris)
    return [m.form("_popup", "", [], table=False)]
