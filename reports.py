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

import json
from inspect import getframeinfo, stack
from logging import getLogger
from os.path import basename
from re import search
from time import time
from typing import Literal

import bpy

from . import colors, ui_bgl, utils
from .asset_bar import asset_bar_op


bk_logger = getLogger(__name__)
reports = []


def humanize_server_message(text: str) -> str:
    """Turn a raw server error string into a human-readable message.

    Server errors often arrive wrapped like
    'server returned non-OK status (403): {"detail": "...", "statusCode": 403}'.
    When such a JSON payload with a string 'detail' is detected, return that
    detail (which is written for end users). Otherwise return the text unchanged.
    """
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return text
    try:
        data = json.loads(text[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return text
    if not isinstance(data, dict):
        return text
    detail = data.get("detail")
    if not isinstance(detail, str) or detail.strip() == "":
        return text
    return detail.strip()


# check for same reports and just make them longer by the timeout.
def add_report(
    text: str = "",
    timeout: float = -1,
    type: Literal["INFO", "ERROR", "VALIDATOR", "WARNING"] = "INFO",
    details: str = "",
) -> None:
    """Add text report to GUI. Function checks for same reports and make them longer by the timeout.
    Also log the text and details into the console with levels: ERROR=RED, INFO=GREEN, VALIDATOR=BLUE, WARNING=YELLOW.
    When timeout is not specified, a default is used: ERROR=15s, others=5s, extended for long messages so they
    stay readable.
    """
    global reports
    text = humanize_server_message(text.strip())
    full_message = text
    details = details.strip()
    color = colors.GRAY
    if details != "":
        full_message = f"{text} {details}"

    if timeout == -1:
        if type == "ERROR":
            timeout = 15
        else:
            timeout = 5
        # Long messages (e.g. detailed server responses) need more time to read.
        # Allow roughly one extra second per 18 characters, capped at 60s.
        timeout = max(timeout, min(60, len(full_message) / 18))

    if type == "ERROR":
        regex = r"\[[^\[\]:]+:\d+\]"
        if search(regex, text) is None:
            caller = getframeinfo(stack()[1][0])
            location = f"[{basename(caller.filename)}:{caller.lineno}]"
            text = f"{text} {location}"
            full_message = f"{full_message} {location}"
        bk_logger.error(full_message, stacklevel=2)
        color = colors.RED
    elif type == "INFO":
        bk_logger.info(full_message, stacklevel=2)
        color = colors.GREEN
    elif type == "VALIDATOR":
        bk_logger.info(full_message, stacklevel=2)
        color = colors.BLUE
    elif type == "WARNING":
        bk_logger.warning(full_message, stacklevel=2)
        color = colors.YELLOW

    # check for same reports and just make them longer by the timeout.
    for old_report in reports:
        if old_report.text == text:
            old_report.timeout = old_report.age + timeout
            return
    report = Report(text=text, timeout=timeout, color=color)
    reports.append(report)


class Report:
    def __init__(self, text="", timeout=5, color=(0.5, 1, 0.5, 1)):
        self.text = text
        self.timeout = timeout
        self.start_time = time()
        self.color = color
        self.draw_color = color
        self.age = 0

        self.active_area_pointer = asset_bar_op.active_area_pointer
        if asset_bar_op.active_area_pointer == 0:
            w, a, r = utils.get_largest_area(area_type="VIEW_3D")
            if a is not None:
                self.active_area_pointer = a.as_pointer()

    def fade(self):
        fade_time = 1
        self.age = time() - self.start_time
        if self.age + fade_time > self.timeout:
            alpha_multiplier = (self.timeout - self.age) / fade_time
            self.draw_color = (
                self.color[0],
                self.color[1],
                self.color[2],
                self.color[3] * alpha_multiplier,
            )
            if self.age > self.timeout:
                global reports
                try:
                    reports.remove(self)
                except Exception as e:
                    bk_logger.warning("exception in fading: %s", e)

    def draw(self, x, y):
        if (
            bpy.context.area is not None
            and bpy.context.area.as_pointer() == self.active_area_pointer
        ):
            lines = self.text.split("\n")
            for i, line in enumerate(lines):
                ui_bgl.draw_text(line, x, y + 8 - i * 20, 16, self.draw_color)
            return len(lines)
        return 1
