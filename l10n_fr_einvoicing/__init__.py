from . import models
from . import controllers
from . import wizards

# If odoo is started with debug log level, facturx should be in debug too
import logging
from odoo.tools import config

if config.get("log_level", "info").startswith("debug"):
    logging.getLogger("facturx").setLevel(logging.DEBUG)
