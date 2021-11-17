import datetime
import glob
import json
import logging
import os
import pathlib
import subprocess
import sys
import time
from configparser import ConfigParser
from typing import Optional

import pika
from requests import HTTPError
from requests.exceptions import ConnectionError
from soundcloud import SoundCloud, User, Track

from .config import init_config
from .rabbit import init_rabbitmq
from .sql import init_sql, SQLArtist, SQLTrack

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
config = init_config()
channel = None


def run():
    global channel
    global config

    # init sql
    Session = init_sql(config.get("sql", "url"))

    # init rabbitmq
    channel = init_rabbitmq(config.get("rabbit", "url"))

    def log_error(message: str):
        global channel
        logger.error(message)
        try:
            channel.basic_publish("errors", "", message.encode("utf-8"))
        except (pika.exceptions.ConnectionClosed, pika.exceptions.StreamLostError):
            channel = init_rabbitmq(config.get("rabbit", "url"))
            channel.basic_publish("errors", "", message.encode("utf-8"))

    def publish_message(exchange: str, data: dict, routing_key=""):
        global channel
        try:
            channel.basic_publish(exchange, routing_key,
                                  json.dumps(data).encode("utf-8"))
        except (pika.exceptions.ConnectionClosed, pika.exceptions.StreamLostError):
            channel = init_rabbitmq(config.get("rabbit", "url"))
            channel.basic_publish(exchange, routing_key,
                                  json.dumps(data).encode("utf-8"))

    def check_sc_valid(sc: SoundCloud):
        if not sc.is_client_id_valid():
            log_error("Invalid client id!")
            sys.exit(1)
        if not sc.is_auth_token_valid():
            log_error("Invalid auth token!")
            sys.exit(1)

    def insert_artist(session, artist: User):
        artist = SQLArtist.from_dataclass(artist)
        session.add(artist)
        publish_message("artists", {
            "event": "created",
            "changes": None,
            "artist": artist.to_dict()
        })

    def insert_track(session, artist: SQLArtist, track: Track, path: str):
        track = SQLTrack.from_dataclass(track)
        track.file_path = path
        session.add(track)
        publish_message("tracks", {
            "event": "created",
            "changes": None,
            "artist": artist.to_dict(),
            "track": track.to_dict()
        })

    def update_artist(session, old_artist: SQLArtist, new_artist: User):
        changes = old_artist.update_from_dataclass(new_artist)
        if old_artist.deleted:
            changes["deleted"] = (old_artist.deleted.isoformat(), None)
            old_artist.deleted = None
        if len(changes) > 0:
            publish_message("artists", {
                "event": "updated",
                "changes": changes,
                "artist": old_artist.to_dict()
            })

    def update_track(session, artist: SQLArtist, old_track: SQLTrack, new_track: Track, path: str = None):
        changes = old_track.update_from_dataclass(new_track)
        if old_track.deleted:
            changes["deleted"] = (old_track.deleted.isoformat(), None)
            old_track.deleted = None
        if path:
            changes["file_path"] = (old_track.file_path, path)
            old_track.file_path = path
        if len(changes) > 0:
            publish_message("tracks", {
                "event": "updated",
                "changes": changes,
                "artist": artist.to_dict(),
                "track": old_track.to_dict()
            })

    def delete_artist(session, artist: SQLArtist):
        publish_message("artists", {
            "event": "deleted",
            "changes": None,
            "artist": artist.to_dict()
        })
        artist.tracking = False
        artist.deleted = datetime.datetime.utcnow()

    def delete_track(session, artist: SQLArtist, track: SQLTrack):
        publish_message("tracks", {
            "event": "deleted",
            "changes": None,
            "artist": artist.to_dict(),
            "track": track.to_dict()
        })
        track.deleted = datetime.datetime.utcnow()

    def download_track(sc: SoundCloud, artist: SQLArtist, track: SQLTrack) -> Optional[str]:
        """
        Downloads a track and returns relative path to the file
        """
        try:
            base_path = config.get("system", "data_path")
            dir_path = pathlib.Path(base_path, str(artist.id))
            dir_path.mkdir(parents=True, exist_ok=True)
            timestamp = int(track.last_modified.timestamp())
            p = subprocess.run(["scdl",
                                "-l", track.permalink_url,
                                "--flac",
                                "--original-art",
                                "--path", dir_path,
                                "--name-format", f"{{id}}_{{title}}_{timestamp}",
                                "--client-id", sc.client_id,
                                "--auth-token", sc.auth_token,
                                "--overwrite"],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               encoding="utf-8")
            if p.returncode == 0:
                path = glob.glob(str(dir_path.joinpath(
                    f"{track.id}_*_{timestamp}*")))[0]
                filename = os.path.basename(path)
                return str(pathlib.Path(str(artist.id), filename))
            else:
                logger.error(p.stderr)
                raise Exception("scdl call failed")
        except KeyboardInterrupt:
            raise
        except:
            check_sc_valid(sc)
            logger.exception("Could not download track")
            log_error(f"Could not download track: {track.permalink_url}")
            return None

    def download_tracks(session, sc: SoundCloud, artist: User):
        artist = SQLArtist.from_dataclass(artist)
        tracks = {t.id: t for t in session.query(SQLTrack).filter(
            SQLTrack.user_id == artist.id).all()}
        for track in sc.get_user_tracks(artist.id, limit=5000):
            # remove utc timezone to compare with database track
            track.last_modified = track.last_modified.replace(tzinfo=None)
            if track.id in tracks:
                old_track = tracks.pop(track.id)
                # download track if changed or not downloaded yet & update
                path = None
                if old_track.file_path is None or track.full_duration != old_track.full_duration:
                    if track.media.transcodings:
                        path = download_track(sc, artist, track)
                if old_track.deleted or path or old_track.last_modified != track.last_modified:
                    update_track(session, artist, old_track, track, path)
            else:
                # insert & download track
                if track.media.transcodings:
                    path = download_track(sc, artist, track)
                insert_track(session, artist, track, path)
            session.commit()
        # remaining tracks are deleted tracks
        for track_id, track in tracks.items():
            if track.deleted:
                continue
            delete_track(session, artist, track)
            session.commit()

    while True:
        try:

            # reload config
            config = init_config()

            # init soundcloud
            client_id = config.get("soundcloud", "client_id")
            auth_token = config.get("soundcloud", "auth_token")
            sc = SoundCloud(client_id, auth_token)
            check_sc_valid(sc)
            user_id = sc.get_me().id

            with Session() as session:
                # get all not deleted artists
                artists = {a.id: a for a in session.query(SQLArtist).all()}
                for artist in sc.get_user_following(user_id, limit=5000):
                    # remove utc timezone to compare with database artist
                    artist.last_modified = artist.last_modified.replace(
                        tzinfo=None)
                    if artist.id in artists:
                        old_artist = artists.pop(artist.id)
                        if old_artist.deleted or old_artist.last_modified != artist.last_modified:
                            update_artist(session, old_artist, artist)
                    else:
                        insert_artist(session, artist)
                    session.commit()
                    download_tracks(session, sc, artist)
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
            log_error(f"ConnectionError: {err}")
            time.sleep(60)


def set_auth():
    global config
    if len(sys.argv) < 2:
        logger.error("Must specify auth token")
        sys.exit(1)
    auth = sys.argv[1]
    config.set("soundcloud", "auth_token", auth)
    with open(config_file, "w", encoding="UTF-8") as f:
        config.write(f)


def set_client_id():
    global config
    if len(sys.argv) < 2:
        logger.error("Must specify client ID")
        sys.exit(1)
    client_id = sys.argv[1]
    config.set("soundcloud", "client_id", client_id)
    with open(config_file, "w", encoding="UTF-8") as f:
        config.write(f)
