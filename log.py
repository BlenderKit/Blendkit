# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

import logging
import re
import sys

from . import global_vars


bk_logger = logging.getLogger(__name__)


# Custom level below DEBUG for very high-frequency diagnostic logs (e.g. per-draw
# add-on installation status checks) that would otherwise flood DEBUG output.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")


def _trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)


logging.Logger.trace = _trace  # type: ignore[attr-defined]


class BlenderKitFormatter(logging.Formatter):
    """Add emojis for logging level and mask API key tokens.
    Replace temporary tokens with *** and permanent tokens with *****.
    """

    EMOJIS = {
        TRACE: "🔬 ",
        logging.DEBUG: "🐞 ",
        logging.INFO: "ℹ️ ",
        logging.WARNING: "⚠️ ",
        logging.ERROR: "❌ ",
        logging.CRITICAL: "🔥 ",
    }

    def format(self, record):
        record.levelname = self.EMOJIS.get(record.levelno, "")
        msg = super().format(record)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{30}\b(?=["\'\s])', r"***", msg)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{40}\b(?=["\'\s])', r"*****", msg)
        return msg


def get_blenderkit_formatter():
    """Get default sensitive formatter for Blendkit loggers."""
    return BlenderKitFormatter(
        fmt="%(levelname)s blendkit: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]",
        datefmt="%H:%M:%S",
    )


class SensitiveFormatter(logging.Formatter):
    """Mask API key tokens. Replace temporary tokens with *** and permanent tokens with *****."""

    def format(self, record):
        msg = super().format(record)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{30}\b(?=["\'\s])', r"***", msg)
        msg = re.sub(r'(?<=["\'\s])\b[A-Za-z0-9]{40}\b(?=["\'\s])', r"*****", msg)
        return msg


def get_sensitive_formatter():
    """Get default sensitive formatter for Blendkit loggers."""
    return SensitiveFormatter(
        fmt="blendkit %(levelname)s: %(message)s [%(asctime)s.%(msecs)03d, %(filename)s:%(lineno)d]",
        datefmt="%H:%M:%S",
    )


def configure_bk_logger():
    """Configure 'blendkit' logger to which all other logs defined as `bk_logger = logging.getLogger(__name__)` writes.
    Sets it logging level to `global_vars.LOGGING_LEVEL_BLENDKIT`.
    """
    bk_logger = logging.getLogger(__name__.removesuffix(".log"))
    bk_logger.setLevel(global_vars.LOGGING_LEVEL_BLENDKIT)
    bk_logger.propagate = False
    bk_logger.handlers = []

    stream_handler = logging.StreamHandler()
    stream_handler.stream = sys.stdout  # 517
    stream_handler.setFormatter(get_blenderkit_formatter())
    bk_logger.addHandler(stream_handler)


def configure_imported_loggers():
    """Configure loggers for imported modules so they can have different logging level `global_vars.LOGGING_LEVEL_IMPORTED` than main Blendkit logger."""
    urllib3_logger = logging.getLogger("urllib3")
    urllib3_logger.propagate = False
    urllib3_logger.handlers = []

    urllib3_handler = logging.StreamHandler()
    urllib3_handler.stream = sys.stdout  # 517
    urllib3_handler.setLevel(global_vars.LOGGING_LEVEL_IMPORTED)
    urllib3_handler.setFormatter(get_sensitive_formatter())
    urllib3_logger.addHandler(urllib3_handler)


def configure_loggers():
    """Configure all loggers for Blendkit addon. See called functions for details."""
    configure_bk_logger()
    configure_imported_loggers()
