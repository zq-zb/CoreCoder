"""CoreCoder 评测集命令行入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import Agent
from .config import Config
from .evaluation import (
    CodingAgentEvaluator,
    EvaluationCase,
    build_evaluation_metadata,
    discover_cases,
    summarize_results,
    write_evaluation_report,
)
from .llm import LLM, LiteLLM
from .tools.bash import BashTool
from .tools.edit import EditFileTool
from .tools.glob_tool import GlobTool
from .tools.grep import GrepTool
from .tools.read import ReadFileTool
from .tools.repository_search import RepositorySearchTool
from .tools.write import WriteFileTool


def _coding_tools(*, repository_retrieval: bool = True):
    """评测只提供完成编码任务必需的最小工具集。"""

    # 专用工具优先，避免模型把 Bash 当作文件浏览器消耗预算。
    tools = [ReadFileTool(), EditFileTool(), WriteFileTool(), GlobTool(), GrepTool()]
    if repository_retrieval:
        tools.append(RepositorySearchTool())
    tools.append(BashTool())
    return tools


def _agent_factory(config: Config, strategy: str, *, retrieval_mode: str = "guided"):
    def create(case: EvaluationCase, workspace: Path) -> Agent:
        llm_class = LiteLLM if config.provider == "litellm" else LLM
        llm = llm_class(
            model=config.model,
            api_key=config.api_key,
            base_url=config.base_url,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        return Agent(
            llm=llm,
            tools=_coding_tools(repository_retrieval=retrieval_mode != "off"),
            max_context_tokens=config.max_context_tokens,
            max_rounds=case.max_tool_calls,
            context_strategy=strategy,
            repository_retrieval_policy="guided" if retrieval_mode == "guided" else "available",
        )

    return create


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="运行 CoreCoder Coding Agent 量化评测")
    default_cases = Path(__file__).parents[1] / "evals" / "cases"
    parser.add_argument("--cases", type=Path, default=default_cases, help="评测案例根目录")
    parser.add_argument("--case", action="append", dest="case_ids", help="只运行指定案例，可重复传入")
    parser.add_argument("--output", type=Path, default=Path("evals/reports/latest"), help="报告输出目录")
    parser.add_argument("--keep-workspaces", action="store_true", help="保留隔离评测工作区便于排障")
    parser.add_argument("--run", action="store_true", help="真实调用模型；不传时只列出案例")
    parser.add_argument("--repeat", type=int, default=1, help="每个案例重复运行次数，用于评估稳定性")
    parser.add_argument(
        "--strategy",
        choices=("baseline", "structured-memory"),
        default="baseline",
        help="上下文策略：原始模型摘要或带确定性工作记忆的摘要",
    )
    parser.add_argument(
        "--retrieval",
        choices=("off", "available", "guided"),
        default="guided",
        help="关闭检索、仅提供工具，或由运行时引导首次仓库检查；用于 A/B 对比",
    )
    options = parser.parse_args(argv)
    if options.repeat <= 0:
        parser.error("--repeat 必须大于 0")

    cases = discover_cases(options.cases)
    if options.case_ids:
        selected = set(options.case_ids)
        cases = [case for case in cases if case.case_id in selected]
        missing = selected - {case.case_id for case in cases}
        if missing:
            parser.error(f"未找到评测案例：{', '.join(sorted(missing))}")

    print(f"已加载 {len(cases)} 个评测案例：")
    for case in cases:
        print(f"- {case.case_id}: {case.task}")
    print(f"仓库检索：{options.retrieval}")
    if not options.run:
        print("\n未传入 --run，本次不调用付费模型。")
        return 0

    config = Config.from_env()
    if not config.api_key:
        print("未找到 API Key，请配置 DEEPSEEK_API_KEY、OPENAI_API_KEY 或 CORECODER_API_KEY。")
        return 2

    evaluator = CodingAgentEvaluator(
        _agent_factory(config, options.strategy, retrieval_mode=options.retrieval),
        keep_workspaces=options.keep_workspaces,
    )
    results = []
    for repetition in range(1, options.repeat + 1):
        if options.repeat > 1:
            print(f"\n开始第 {repetition}/{options.repeat} 轮评测")
        run_results, _ = evaluator.run_suite(cases)
        results.extend(run_results)
    summary = summarize_results(results)
    metadata = build_evaluation_metadata(
        cases,
        model=config.model,
        provider=config.provider,
        strategy=f"{options.strategy}+retrieval-{options.retrieval}",
    )
    json_path, markdown_path = write_evaluation_report(results, summary, options.output, metadata)
    print(f"\n评测完成：{summary.passed_cases}/{summary.total_cases} ({summary.success_rate:.1%})")
    print(f"JSON: {json_path.resolve()}")
    print(f"Markdown: {markdown_path.resolve()}")
    return 0 if summary.passed_cases == summary.total_cases else 1


if __name__ == "__main__":
    sys.exit(main())
