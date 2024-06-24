import datetime
import json
import logging
import pathlib

import pika
from discord_webhook import DiscordEmbed, DiscordWebhook

from .config import init_config
from .rabbit import init_rabbitmq

config = init_config()

MAX_DISCORD_FILE_SIZE = 25 * 1024 * 1024  # 25 MiB


def make_error_webhook_data(error: str) -> DiscordWebhook:
    webhook = DiscordWebhook("")
    webhook.username = "SoundCloud"
    webhook.add_embed(
        DiscordEmbed(description=error, color=0xDC143C, author={"name": "Error"})
    )
    return webhook


def make_artist_webhook_data(artist: dict) -> DiscordWebhook:
    webhook = DiscordWebhook("")
    webhook.username = "SoundCloud"
    webhook.add_embed(
        DiscordEmbed(
            timestamp=artist["last_modified"],
            author={
                "name": artist["username"],
                "url": artist["permalink_url"],
                "icon_url": artist["avatar_url"],
            },
        )
    )
    return webhook


def make_track_webhook_data(track: dict, artist: dict) -> DiscordWebhook:
    webhook = DiscordWebhook("")
    webhook.username = "SoundCloud"
    webhook.add_embed(
        DiscordEmbed(
            title=track["title"],
            description=track["description"],
            url=track["permalink_url"],
            timestamp=track["last_modified"],
            thumbnail={"url": track["artwork_url"]},
            author={
                "name": artist["username"],
                "url": artist["permalink_url"],
                "icon_url": artist["avatar_url"],
            },
        )
    )
    return webhook


def artist_callback(ch: pika.channel.Channel, method, properties, body):
    try:
        data = json.loads(body.decode("utf-8"))
        webhook = make_artist_webhook_data(data["artist"])
        if data["event"] == "updated":
            webhook.embeds[0]["color"] = 0xFFBF1C
            webhook.url = config.get("watcher_webhook", "artist_updated_webhook")
            content = "```\n"
            for attr, (old_value, new_value) in data["changes"].items():
                old_value = str(old_value)
                new_value = str(new_value)
                old_value = old_value.replace("`", "\\`")
                new_value = new_value.replace("`", "\\`")
                content += f"{attr}: {old_value} -> {new_value}\n"
                if attr == "avatar_url":
                    webhook.add_embed(
                        DiscordEmbed(title="Old", image={"url": old_value})
                    )
                    webhook.add_embed(
                        DiscordEmbed(title="New", image={"url": new_value})
                    )
            content += "```"
            webhook.content = content
        elif data["event"] == "deleted":
            webhook.embeds[0]["color"] = 0xDC143C
            webhook.url = config.get("watcher_webhook", "artist_deleted_webhook")
        else:
            return
        result = webhook.execute()
        result.raise_for_status()
    except:
        logging.exception("Could not send data")

def track_callback(ch: pika.channel.Channel, method, properties, body):
    try:
        data = json.loads(body.decode("utf-8"))
        webhook = make_track_webhook_data(data["track"], data["artist"])
        content = f"Path: `{data['track']['file_path']}`"
        if data["event"] == "updated":
            webhook.embeds[0]["color"] = 0xFFBF1C
            webhook.url = config.get("watcher_webhook", "track_updated_webhook")
            content = "\n```\n"
            for attr, (old_value, new_value) in data["changes"].items():
                old_value = str(old_value)
                new_value = str(new_value)
                old_value = old_value.replace("`", "\\`")
                new_value = new_value.replace("`", "\\`")
                content += f"{attr}: {old_value} -> {new_value}\n"
                if attr == "artwork_url":
                    webhook.add_embed(
                        DiscordEmbed(title="Old", image={"url": old_value})
                    )
                    webhook.add_embed(
                        DiscordEmbed(title="New", image={"url": new_value})
                    )
            content += "```"
        elif data["event"] == "created":
            webhook.embeds[0]["color"] = 0x8EFF1C
            webhook.url = config.get("watcher_webhook", "track_created_webhook")
        elif data["event"] == "deleted":
            webhook.embeds[0]["color"] = 0xDC143C
            base_path = config.get("system", "data_path")
            path = pathlib.Path(base_path, data["track"]["file_path"])
            if path.stat().st_size < MAX_DISCORD_FILE_SIZE:
                with open(path, "rb") as f:
                    webhook.add_file(f.read(), path.name)
            webhook.url = config.get("watcher_webhook", "track_deleted_webhook")
        else:
            return

        webhook.content = content
        result = webhook.execute()
        result.raise_for_status()
    except:
        logging.exception("Could not send data")

def error_callback(ch: pika.channel.Channel, method, properties, body):
    try:
        msg = body.decode("utf-8")
        webhook = make_error_webhook_data(msg)
        webhook.url = config.get("watcher_webhook", "error_webhook")
        result = webhook.execute()
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
