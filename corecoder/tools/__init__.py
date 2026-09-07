"""Tool registry."""

from .agent import AgentTool
from .bash import BashTool
from .edit import EditFileTool
from .fetch import FetchUrlTool
from .glob_tool import GlobTool
from .grep import GrepTool
from .now import NowTool
from .read import ReadFileTool
from .repository_search import RepositorySearchTool
from .write import WriteFileTool

ALL_TOOLS = [
    BashTool(),
    ReadFileTool(),
    RepositorySearchTool(),
    WriteFileTool(),
    EditFileTool(),
    GlobTool(),
    GrepTool(),
    AgentTool(),
    NowTool(),
    FetchUrlTool(),
]


def get_tool(name: str):
    """按名称创建独立工具实例，避免 Agent 之间泄漏可变状态。"""
    for t in ALL_TOOLS:
        if t.name == name:
            return type(t)()
    return None


def create_default_tools():
    """为一个新 Agent 创建完整且相互隔离的默认工具集合。"""

    return [type(tool)() for tool in ALL_TOOLS]
