import datetime
import json
import logging

import pika
import requests

from .config import init_config
from .rabbit import init_rabbitmq

config = init_config()

def make_error_webhook_data(error: str) -> dict:
    return {
        "username": "SoundCloud",
        "embeds": [
            {
                "type": "rich",
                "description": error,
                "color": 0xDC143C,
                "author": {
                    "name": "Error",
                }
            }
        ]
    }

def make_artist_webhook_data(artist: dict) -> dict:
    return {
        "username": "SoundCloud",
        "embeds": [
            {
                "type": "rich",
                "timestamp": datetime.datetime.fromtimestamp(artist["last_modified"]).isoformat() + "Z",
                "author": {
                    "name": artist["username"],
                    "url": artist["permalink_url"],
                    "icon_url": artist["avatar_url"]
                }
            }
        ]
    }

def make_track_webhook_data(track: dict, artist: dict) -> dict:
    return {
        "username": "SoundCloud",
        "embeds": [
            {
                "type": "rich",
                "title": track["title"],
                "description": track["description"],
                "url": track["permalink_url"],
                "timestamp": datetime.datetime.fromtimestamp(track["last_modified"]).isoformat() + "Z",
                "thumbnail": {
                    "url": track["artwork_url"]
                },
                "author": {
                    "name": artist["username"],
                    "url": artist["permalink_url"],
                    "icon_url": artist["avatar_url"]
                }
            }
        ]
    }

def artist_callback(ch: pika.channel.Channel, method, properties, body):
    try:
        data = json.loads(body.decode("utf-8"))
        webhook_data = make_artist_webhook_data(data["artist"])
        if data["event"] == "updated":
            webhook_data["embeds"][0]["color"] = 0xffbf1c
            webhook_url = config.get("watcher_webhook", "artist_updated_webhook")
            content = "```\n"
            for attr, (old_value, new_value) in data["changes"].items():
                old_value = old_value.replace("`", "\\`")
                new_value = new_value.replace("`", "\\`")
                content += f"{attr}: {old_value} -> {new_value}\n"
            content += "```"
            webhook_data["content"] = content
        elif data["event"] == "deleted":
            webhook_data["embeds"][0]["color"] = 0xDC143C
            webhook_url = config.get("watcher_webhook", "artist_deleted_webhook")
        else:
            return
        result = requests.post(webhook_url, json=webhook_data)
        result.raise_for_status()
    except:
        logging.exception("Could not send data")

def track_callback(ch: pika.channel.Channel, method, properties, body):
    try:
        data = json.loads(body.decode("utf-8"))
        webhook_data = make_track_webhook_data(data["track"], data["artist"])
        content = f"Path: `{data['track']['file_path']}`"
        if data["event"] == "updated":
            webhook_data["embeds"][0]["color"] = 0xffbf1c
            webhook_url = config.get("watcher_webhook", "track_updated_webhook")
            content = "\n```\n"
            for attr, (old_value, new_value) in data["changes"].items():
                old_value = old_value.replace("`", "\\`")
                new_value = new_value.replace("`", "\\`")
                content += f"{attr}: {old_value} -> {new_value}\n"
            content += "```"
        elif data["event"] == "created":
            webhook_data["embeds"][0]["color"] = 0x8eff1c
            webhook_url = config.get("watcher_webhook", "track_created_webhook")
        elif data["event"] == "deleted":
            webhook_data["embeds"][0]["color"] = 0xDC143C
            webhook_url = config.get("watcher_webhook", "track_deleted_webhook")
        else:
            return
        
        webhook_data["content"] = content
        result = requests.post(webhook_url, json=webhook_data)
        result.raise_for_status()
    except:
        logging.exception("Could not send data")

def error_callback(ch: pika.channel.Channel, method, properties, body):
    try:
        msg = body.decode("utf-8")
        webhook_data = make_error_webhook_data(msg)
        webhook_url = config.get("watcher_webhook", "error_webhook")
        result = requests.post(webhook_url, json=webhook_data)
        result.raise_for_status()
    except:
        logging.exception("Could not send data")

def run():
    # init rabbitmq
    channel = init_rabbitmq(config.get("rabbit", "url"))
    
    error_queue = channel.queue_declare("errors")
    artist_queue = channel.queue_declare("artists")
    track_queue = channel.queue_declare("tracks")
    
    channel.queue_bind("artists", "artists", routing_key="#")
    channel.queue_bind("errors", "errors", routing_key="#")
    channel.queue_bind("tracks", "tracks", routing_key="#")
    
    channel.basic_consume("artists", artist_callback, auto_ack=True)
    channel.basic_consume("errors", error_callback, auto_ack=True)
    channel.basic_consume("tracks", track_callback, auto_ack=True)
    
    channel.start_consuming()
