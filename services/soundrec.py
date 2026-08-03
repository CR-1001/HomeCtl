# This file is part of HOMEctlx. Copyright (C) 2024 Christian Rauch.
# Distributed under terms of the GPL3 license.

"""
Sound recommendation service.

Given a track, album, artist, or playlist ID, returns similar tracks grouped
by source:
  - same_album:      other tracks on the same album
  - other_albums:    tracks from other albums/singles by the same primary artist
                     (or top tracks of the most-represented playlist artists)
  - related_artists: top tracks from artists Spotify considers related

All Spotify access is exclusively through soundctl — this service never calls
the Spotify API directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import services.soundctl as sc

log = logging.getLogger(__name__)


def _track_key(t: sc.Track) -> tuple:
    """Composite dedup key: (lowercase name, frozenset of artist IDs).
    Treats the same song appearing on multiple albums as a single entry."""
    return (t.name.lower(), frozenset(a.id for a in t.artists if a.id))

# Number of related artists whose top tracks are included.
MAX_RELATED_ARTISTS = 8
# Number of most-frequent playlist artists used as seeds for playlist recommendations.
MAX_PLAYLIST_ARTISTS = 8


@dataclass
class Recommendations:
    same_album:      list[sc.Track] = field(default_factory=list)
    other_albums:    list[sc.Track] = field(default_factory=list)
    related_artists: list[sc.Track] = field(default_factory=list)

    def all_tracks(self) -> list[sc.Track]:
        """Deduplicated flat list: same_album -> other_albums -> related_artists."""
        seen:   set        = set()
        result: list[sc.Track] = []
        for t in self.same_album + self.other_albums + self.related_artists:
            key = _track_key(t)
            if key not in seen:
                seen.add(key)
                result.append(t)
        return result


def recommend(
    track_id:    str = "",
    album_id:    str = "",
    artist_id:   str = "",
    playlist_id: str = "",
) -> Recommendations:
    """
    Return recommendations for a given track, album, artist, or playlist.
    At least one ID must be provided; the others are resolved automatically
    when omitted.
    """
    source_track_id = track_id

    # Resolve album and artist from a track ID when not provided.
    if track_id and (not album_id or not artist_id):
        track = sc.get_track(track_id)
        if track:
            if not album_id:
                album_id = track.album_id
            if not artist_id and track.artists:
                artist_id = track.artists[0].id

    # Resolve artist from an album ID when not provided.
    if album_id and not artist_id:
        album = sc.get_album(album_id)
        if album and album.artists:
            artist_id = album.artists[0].id

    result = Recommendations()

    # --- 1. Other tracks on the same album ---
    if album_id:
        for t in sc.get_all_album_tracks(album_id):
            if t.id != source_track_id:
                result.same_album.append(t)

    # --- 2. Tracks from other albums/singles by the same primary artist ---
    if artist_id:
        seen: set = {_track_key(t) for t in result.same_album}
        for album in sc.get_artist_albums(artist_id):
            if album.id == album_id:
                continue
            for t in sc.get_all_album_tracks(album.id):
                key = _track_key(t)
                if t.id != source_track_id and key not in seen:
                    result.other_albums.append(t)
                    seen.add(key)

    # --- 3. Top tracks from related artists ---
    if artist_id:
        seen_overall: set = {_track_key(t) for t in result.same_album + result.other_albums}
        related = sc.get_related_artists(artist_id)[:MAX_RELATED_ARTISTS]
        for rel in related:
            for t in sc.get_artist_top_tracks(rel.id):
                key = _track_key(t)
                if t.id != source_track_id and key not in seen_overall:
                    result.related_artists.append(t)
                    seen_overall.add(key)

    # --- Playlist path ---
    if playlist_id and not artist_id:
        result = _recommend_from_playlist(playlist_id)

    return result


def _recommend_from_playlist(playlist_id: str) -> Recommendations:
    """Derive recommendations from a playlist by seeding with its most-frequent artists."""
    # Sample the first 50 tracks to identify representative artists.
    sample, _ = sc.get_playlist_tracks(playlist_id, limit=50)

    # Count how often each artist appears in the sample.
    artist_counts: dict[str, tuple[str, int]] = {}  # id -> (name, count)
    for t in sample:
        for a in t.artists:
            if a.id:
                name, cnt = artist_counts.get(a.id, (a.name, 0))
                artist_counts[a.id] = (name, cnt + 1)

    top_artists = sorted(artist_counts.items(),
                         key=lambda x: x[1][1], reverse=True)[:MAX_PLAYLIST_ARTISTS]

    # Exclude tracks already in the playlist sample.
    seen: set = {_track_key(t) for t in sample}

    merged = Recommendations()
    for aid, _ in top_artists:
        recs = recommend(artist_id=aid)
        for t in recs.same_album + recs.other_albums:
            key = _track_key(t)
            if key not in seen:
                merged.other_albums.append(t)
                seen.add(key)
        for t in recs.related_artists:
            key = _track_key(t)
            if key not in seen:
                merged.related_artists.append(t)
                seen.add(key)

    return merged
