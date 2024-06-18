import logging
import os
import pathlib
import sys
from configparser import ConfigParser

import appdirs

logger = logging.getLogger(__name__)

def init_config() -> ConfigParser:
    config = ConfigParser()
    config_file = os.getenv("CONFIG_FILE_PATH", pathlib.Path(appdirs.user_config_dir("sc-archive"), "config.ini"))
    config_file = pathlib.Path(config_file)
    config.read(config_file)
        
    logger.info(f"Loaded config: {config_file}")
        
    return config