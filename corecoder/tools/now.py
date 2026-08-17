"""A tool that tells the agent the current time."""

import time
from .base import Tool


class NowTool(Tool):
    name = "now"
    # 什么时候调用该工具
    description = "Get the current local date and time. Use this when the user asks about the current time or you need a timestamp."
    parameters = { # 参数：空 不需要参数， JSON Schema
        "type": "object",
        "properties": {},
        "required": [],
    }

    def execute(self) -> str: # 返回回填当前时间的字符串
        return time.strftime("%Y-%m-%d %H:%M:%S")