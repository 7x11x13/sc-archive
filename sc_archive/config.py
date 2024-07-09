import logging
import os
import pathlib
from configparser import ConfigParser

logger = logging.getLogger(__name__)


def init_config() -> ConfigParser:
    config = ConfigParser()
    config_file = os.getenv("CONFIG_FILE_PATH")
    config_file = pathlib.Path(config_file)
    config.read(config_file)

    logger.info(f"Loaded config: {config_file}")

    return config
