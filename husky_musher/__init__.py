import logging

from id3c.logging.config import load_config


def configure_logger(filename):
    logger = logging.getLogger('gunicorn.error').getChild('app')
    with open(filename, "rb") as file:
        logging.config.dictConfig(load_config(file))
