import datetime
import glob
import json
import logging
import os
import pathlib
import subprocess
import threading
import time
import urllib.parse
from typing import Optional

import pika
from requests import HTTPError
import requests
from requests.exceptions import ConnectionError
from soundcloud import SoundCloud, User, Track

from .config import init_config
from .rabbit import init_rabbitmq
from .sql import init_sql, SQLArtist, SQLTrack
from .watcher_webhook import run as run_webhooks

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def run():
    config = init_config()
    channel: pika.channel.Channel = None
    client: SoundCloud = None

    # init sql
    Session = init_sql(config.get("sql", "url"))

    # init rabbitmq
    channel = init_rabbitmq(config.get("rabbit", "url"))

    def get_sc_client():
        nonlocal client
        if (
            client is not None
            and client.is_client_id_valid()
            and client.is_auth_token_valid()
        ):
            return client
        user_id = int(config.get("soundcloud", "user_id"))
        base_url = config.get("soundcloud", "cookie_server_url")
        api_key = config.get("soundcloud", "cookie_server_api_key")
        url = urllib.parse.urljoin(base_url, f"/get_cookies/soundcloud/{user_id}")
        auth_token = None
        with requests.get(url, headers={"X-API-Key": api_key}) as r:
            r.raise_for_status()
            for cookie in r.json():
                if cookie["name"] == "oauth_token":
                    auth_token = cookie["value"]
                    break
        sc = SoundCloud(None, auth_token)
        if auth_token is None:
            raise Exception("Could not get oauth_token cookie")
        if not sc.is_auth_token_valid():
            raise Exception("Invalid auth token")
        client = sc
        return client

    def log_error(message: str):
        nonlocal channel
        logger.error(message)
        try:
            channel.basic_publish("errors", "", message.encode("utf-8"))
        except (pika.exceptions.ConnectionClosed, pika.exceptions.StreamLostError):
            channel = init_rabbitmq(config.get("rabbit", "url"))
            channel.basic_publish("errors", "", message.encode("utf-8"))

    def publish_message(exchange: str, data: dict, routing_key=""):
        nonlocal channel
        try:
            channel.basic_publish(
                exchange, routing_key, json.dumps(data).encode("utf-8")
            )
        except (pika.exceptions.ConnectionClosed, pika.exceptions.StreamLostError):
            channel = init_rabbitmq(config.get("rabbit", "url"))
            channel.basic_publish(
                exchange, routing_key, json.dumps(data).encode("utf-8")
            )

    def insert_artist(session, artist: User):
        artist = SQLArtist.from_dataclass(artist)
        session.add(artist)
        publish_message(
            "artists", {"event": "created", "changes": None, "artist": artist.to_dict()}
        )

    def insert_track(session, artist: SQLArtist, track: Track, path: str):
        track = SQLTrack.from_dataclass(track)
        track.file_path = path
        session.add(track)
        publish_message(
            "tracks",
            {
                "event": "created",
                "changes": None,
                "artist": artist.to_dict(),
                "track": track.to_dict(),
            },
        )

    def update_artist(session, old_artist: SQLArtist, new_artist: User):
        changes = old_artist.update_from_dataclass(new_artist)
        if old_artist.deleted:
            changes["deleted"] = (old_artist.deleted.isoformat(), None)
            old_artist.deleted = None
        if len(changes) > 0:
            publish_message(
                "artists",
                {
                    "event": "updated",
                    "changes": changes,
                    "artist": old_artist.to_dict(),
                },
            )

    def update_track(
        session,
        artist: SQLArtist,
        old_track: SQLTrack,
        new_track: Track,
        path: str = None,
    ):
        changes = old_track.update_from_dataclass(new_track)
        if old_track.deleted:
            changes["deleted"] = (old_track.deleted.isoformat(), None)
            old_track.deleted = None
        if path:
            changes["file_path"] = (old_track.file_path, path)
            old_track.file_path = path
        if len(changes) > 0:
            publish_message(
                "tracks",
                {
                    "event": "updated",
                    "changes": changes,
                    "artist": artist.to_dict(),
                    "track": old_track.to_dict(),
                },
            )

    def delete_artist(session, artist: SQLArtist):
        publish_message(
            "artists", {"event": "deleted", "changes": None, "artist": artist.to_dict()}
        )
        artist.tracking = False
        artist.deleted = datetime.datetime.utcnow()

    def delete_track(session, artist: SQLArtist, track: SQLTrack):
        publish_message(
            "tracks",
            {
                "event": "deleted",
                "changes": None,
                "artist": artist.to_dict(),
                "track": track.to_dict(),
            },
        )
        track.deleted = datetime.datetime.utcnow()

    def download_track(artist: SQLArtist, track: SQLTrack) -> Optional[str]:
        """
        Downloads a track and returns relative path to the file
        """
        sc = get_sc_client()
        try:
            base_path = config.get("system", "data_path")
            dir_path = pathlib.Path(base_path, str(artist.id))
            os.umask(0)
            dir_path.mkdir(mode=0o777, parents=True, exist_ok=True)
            timestamp = int(track.last_modified.timestamp())
            p = subprocess.run(
                [
                    "scdl",
                    "-l",
                    track.permalink_url,
                    "--flac",
                    "--original-art",
                    "--path",
                    dir_path,
                    "--name-format",
                    f"{{id}}_{timestamp}_{{title}}",
                    "--client-id",
                    sc.client_id,
                    "--auth-token",
                    sc.auth_token,
                    "--overwrite",
                    "--hide-progress",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
            )
            if p.returncode == 0:
                path = glob.glob(str(dir_path.joinpath(f"{track.id}_{timestamp}*")))[0]
                filename = os.path.basename(path)
                return str(pathlib.Path(str(artist.id), filename))
            else:
                logger.error(p.stderr)
                raise Exception("scdl call failed")
        except Exception:
            logger.exception("Could not download track")
            log_error(f"Could not download track: {track.permalink_url}")
            return None

    def download_tracks(session, artist: User):
        sc = get_sc_client()
        artist = SQLArtist.from_dataclass(artist)
        tracks = {
            t.id: t
            for t in session.query(SQLTrack).filter(SQLTrack.user_id == artist.id).all()
        }
        for track in sc.get_user_tracks(artist.id, limit=1000):
            # remove utc timezone to compare with database track
            track.last_modified = track.last_modified.replace(tzinfo=None)
            if track.id in tracks:
                old_track = tracks.pop(track.id)
                # download track if changed or not downloaded yet & update
                path = None
                if (
                    old_track.file_path is None
                    or track.full_duration != old_track.full_duration
                ):
                    if track.media.transcodings:
                        path = download_track(artist, track)
                if (
                    old_track.deleted
                    or path
                    or old_track.last_modified != track.last_modified
                ):
                    update_track(session, artist, old_track, track, path)
            else:
                # insert & download track
                if track.media.transcodings:
                    path = download_track(artist, track)
                insert_track(session, artist, track, path)
            session.commit()
        # remaining tracks are deleted tracks
        for track_id, track in tracks.items():
            if track.deleted:
                continue
            delete_track(session, artist, track)
            session.commit()

    # init webhooks
    t = threading.Thread(target=run_webhooks, daemon=True)
    t.start()

    while True:
        try:
            # reload config
            config = init_config()

            # init soundcloud
            sc = get_sc_client()
            user_id = int(config.get("soundcloud", "user_id"))

            with Session() as session:
                # get all not deleted artists
                artists = {a.id: a for a in session.query(SQLArtist).all()}
                for artist in sc.get_user_following(user_id, limit=5000):
                    # remove utc timezone to compare with database artist
                    artist.last_modified = artist.last_modified.replace(tzinfo=None)
                    if artist.id in artists:
                        old_artist = artists.pop(artist.id)
                        if (
                            old_artist.deleted
                            or old_artist.last_modified != artist.last_modified
                        ):
                            update_artist(session, old_artist, artist)
                    else:
                        insert_artist(session, artist)
                    session.commit()
                    try:
                        download_tracks(session, artist)
                    except Exception:
                        logger.exception(
                            f"Could not download tracks from {artist.permalink_url}"
                        )
                        log_error(
                            f"Could not download tracks for {artist.permalink_url}"
                        )
                # remaining artists are unfollowed or deleted artists
                for artist_id, artist in artists.items():
                    if not artist.tracking:
                        continue
                    if sc.get_user(artist_id):
                        # artist was unfollowed
                        artist.tracking = False
                    else:
                        # artist was deleted
                        delete_artist(session, artist)
                session.commit()
        except HTTPError as err:
            logger.exception(f"HTTPError: {err.response.status_code}")
            log_error(f"HTTPError: {err.response.status_code}")
            time.sleep(60)
        except ConnectionError as err:
            logger.exception("ConnectionError")
            log_error(f"ConnectionError: {err}")
            time.sleep(60)
        except Exception as ex:
            logger.exception("Other exception")
            log_error(f"Other exception: {ex}")
            time.sleep(600)
