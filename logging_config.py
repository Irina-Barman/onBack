import logging
import sys


def setup_logging():  # noqa D103, ANN201
    logging.basicConfig(
        level=logging.DEBUG,
        format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
