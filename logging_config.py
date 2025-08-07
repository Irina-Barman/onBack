import logging
import sys


def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
