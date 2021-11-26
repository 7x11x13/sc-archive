import logging
import pathlib
import sys
from configparser import ConfigParser

logger = logging.getLogger(__name__)

def init_config(config_file: pathlib.Path) -> ConfigParser:
    config = ConfigParser()
    default_config_file = pathlib.Path(__file__).with_name("default.ini")
    config.read(default_config_file)
    config.read(config_file)
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="UTF-8") as f:
        config.write(f)
    
    if not config.get("sql", "url"):
        logger.error(f"Must specify a url for SQLAlchemy in {config_file}")
        sys.exit(1)
    if not config.get("rabbit", "url"):
        logger.error(f"Must specify a url for RabbitMQ in {config_file}")
        sys.exit(1)
        
    logger.info(f"Loaded config: {config_file}")
        
    return config