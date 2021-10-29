import pika

def init_rabbitmq(url: str) -> pika.channel.Channel:
    conn = pika.BlockingConnection(pika.URLParameters(url))
    channel = conn.channel()
    channel.exchange_declare(
        "errors",
        exchange_type="topic"
    )
    channel.exchange_declare(
        "tracks",
        exchange_type="topic"
    )
    channel.exchange_declare(
        "artists",
        exchange_type="topic"
    )
    channel.exchange_declare(
        "track_download",
        exchange_type="topic"
    )
    return channel