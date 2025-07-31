import logging
import sys

def get_logger(name: str = "docgen", level=logging.INFO) -> logging.Logger:
    """
    Returns a logger instance configured for the project.
    Usage: from src.logging.logging import get_logger; logger = get_logger(__name__, level=logging.DEBUG)
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    else:
        logger.setLevel(level)
    return logger
