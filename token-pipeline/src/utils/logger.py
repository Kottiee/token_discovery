import sys

from loguru import logger


def setup_logger():
    logger.remove()
    logger.add(sys.stdout, format="{time} {level} {message}", level="INFO")
    logger.add("token_pipeline.log", rotation="10 MB", retention=5, level="INFO")
    return logger
