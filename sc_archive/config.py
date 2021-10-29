import logging
import os
import pathlib
from configparser import ConfigParser

import appdirs

logger = logging.getLogger(__name__)

def init_config() -> ConfigParser:
    config = ConfigParser()
    config_file = pathlib.Path(appdirs.user_config_dir("sc-archive"), "config.ini")
    default_config_file = pathlib.Path(__file__).with_name("default.ini")
    config.read(default_config_file)
    if not os.path.exists(config_file):
        logger.warning(f"Config file not found, writing default config to {config_file}")
        config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(config_file, "w", encoding="UTF-8") as f:
            config.write(f)
    config.read(config_file)
    logger.info(f"Loaded config: {config_file}")
    return config