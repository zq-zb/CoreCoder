"""CoreCoder - Minimal AI coding agent inspired by Claude Code's architecture."""

__version__ = "0.4.0"

from corecoder.agent import Agent
from corecoder.audit import AuditLogger, AuditRecord
from corecoder.coding_task import CodingTaskReport, CodingTaskRunner, CodingTaskState
from corecoder.config import Config
from corecoder.evaluation import (
    CodingAgentEvaluator,
    EvaluationCase,
    EvaluationMetadata,
    EvaluationResult,
    EvaluationSummary,
)
from corecoder.execution import DockerSandboxExecutor, DockerSandboxProfile
from corecoder.incident import CIIncidentCoordinator, IncidentIntake, IncidentReport
from corecoder.llm import LLM
from corecoder.mcp_manager import MCPManager, MCPServerConfig
from corecoder.mcp_runtime import MCPRuntime, MCPRuntimeState
from corecoder.security import (
    ApprovalManager,
    ApprovalRequest,
    ApprovalStatus,
    CommandDecision,
    CommandPolicy,
    CommandRisk,
    PolicyGuardedBashTool,
)
from corecoder.task_store import TaskRecord, TaskStatus, TaskStore
from corecoder.task_worker import DurableCodingWorker
from corecoder.tools import ALL_TOOLS

__all__ = [
    "ALL_TOOLS",
    "LLM",
    "Agent",
    "ApprovalManager",
    "ApprovalRequest",
    "ApprovalStatus",
    "AuditLogger",
    "AuditRecord",
    "CIIncidentCoordinator",
    "CodingAgentEvaluator",
    "CodingTaskReport",
    "CodingTaskRunner",
    "CodingTaskState",
    "CommandDecision",
    "CommandPolicy",
    "CommandRisk",
    "Config",
    "DockerSandboxExecutor",
    "DockerSandboxProfile",
    "DurableCodingWorker",
    "EvaluationCase",
    "EvaluationMetadata",
    "EvaluationResult",
    "EvaluationSummary",
    "IncidentIntake",
    "IncidentReport",
    "MCPManager",
    "MCPRuntime",
    "MCPRuntimeState",
    "MCPServerConfig",
    "PolicyGuardedBashTool",
    "TaskRecord",
    "TaskStatus",
    "TaskStore",
    "__version__",
]
