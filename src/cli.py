#!/usr/bin/env python3
"""
口语评分 CLI 框架 - 命令行入口

支持以下命令：
- single: 单文件评分
- run: 批量评分
- validate: 校验输入文件
- report: 从 JSON 重新生成 HTML 报告
"""
import hashlib
import json
import logging
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.advice.generator import generate_feedback
from src.config import load_config
from src.models import (
    EngineMode,
    Meta,
    ScoringResult,
)
from src.pipeline.analyze import analyze_results, assign_tags
from src.pipeline.normalize import normalize_scores
from src.pipeline.preprocess import preprocess_audio
from src.pipeline.router import run_with_fallback
from src.report.render_html import regenerate_report_from_json, render_html_report

# 创建 CLI 应用
app = typer.Typer(
    name="score_reading",
    help="朗读/背诵口语评分 CLI 框架",
    add_completion=False,
)

# 配置子命令
config_app = typer.Typer(name="config", help="配置管理")
app.add_typer(config_app, name="config")


@config_app.command()
def setup() -> None:
    """
    交互式设置配置 (LLM, API Key)
    """
    from src.config import config, USER_CONFIG_PATH
    
    console.print(f"\n[bold blue]🛠️  交互式配置向导[/bold blue]")
    console.print(f"配置将被保存到: {USER_CONFIG_PATH}\n")
    
    # 1. 选择 Provider
    provider_type = typer.prompt(
        "选择 API 类型", 
        default="openai", 
        show_default=True
    ).lower()
    
    # 2.设置 Base URL
    default_base_url = ""
    if provider_type == "openai":
        default_base_url = ""
    elif provider_type == "deepseek":
        default_base_url = "https://api.deepseek.com"
    elif provider_type == "moonshot":
        default_base_url = "https://api.moonshot.cn/v1"
        
    base_url = typer.prompt(
        "API Base URL (留空使用默认)", 
        default=default_base_url,
        show_default=True
    )
    
    # 3. 设置 Model
    default_model = "gpt-4o"
    if provider_type == "deepseek":
        default_model = "deepseek-chat"
    elif provider_type == "moonshot":
        default_model = "moonshot-v1-8k"
        
    model = typer.prompt(
        "模型名称", 
        default=default_model,
        show_default=True
    )
    
    # 4. 设置 API Key (掩码输入)
    api_key = typer.prompt(
        "API Key (输入时不显示)", 
        hide_input=True,
    )
    
    # 保存配置
    updates = {
        "llm": {
            "provider": provider_type,
            "base_url": base_url if base_url else None,
            "model": model,
            "api_key": api_key,
        }
    }
    
    try:
        config.save_user_config(updates)
        console.print(f"\n[bold green]✅ 配置已保存！[/bold green]")
        console.print(f"Provider: {provider_type}")
        console.print(f"Model: {model}")
        if base_url:
            console.print(f"Base URL: {base_url}")
    except Exception as e:
        console.print(f"\n[bold red]❌ 保存失败: {e}[/bold red]")

# 控制台输出
console = Console()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[RichHandler(console=console, rich_tracebacks=True)],
)
logger = logging.getLogger("score_reading")


def generate_submission_id() -> str:
    """生成唯一的提交 ID"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    return f"sub_{timestamp}_{random_hash}"


@app.command()
def single(
    mp3: Path = typer.Option(..., "--mp3", help="输入音频文件路径（MP3/WAV）"),
    text: str = typer.Option(..., "--text", help="标准朗读文本"),
    student: str = typer.Option("unknown", "--student", help="学生 ID 或姓名"),
    task: str = typer.Option("default", "--task", help="任务 ID"),
    engine: str = typer.Option("auto", "--engine", help="引擎模式: auto/fast/pro/wav2vec2"),
    out: Path = typer.Option(Path("./data/out"), "--out", help="输出目录"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="配置文件路径"),
) -> None:
    """
    单文件评分
    
    对单个音频文件进行口语评分，输出 JSON 结果和 HTML 报告。
    """
    start_time = time.time()
    
    # 加载配置
    load_config(config_path)
    
    # 验证输入
    if not mp3.exists():
        console.print(f"[red]错误: 音频文件不存在: {mp3}[/red]")
        raise typer.Exit(1)
    
    # 解析引擎模式
    try:
        engine_mode = EngineMode(engine.lower())
    except ValueError:
        console.print(f"[red]错误: 无效的引擎模式: {engine}[/red]")
        console.print("有效选项: auto, fast, pro, wav2vec2")
        raise typer.Exit(1)
    
    # 初始化结果 (Moved to runner, but we need submission_id for error handling if outside runner)
    # Actually runner handles everything including error saving.
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            
            task_id = progress.add_task("正在评分...", total=None)
            
            def progress_callback(desc: str):
                progress.update(task_id, description=desc)

            # 调用通用 Pipeline
            from src.pipeline.runner import run_scoring_pipeline
            
            result, json_path, html_path = run_scoring_pipeline(
                mp3_path=mp3,
                text=text,
                output_dir=out,
                student_id=student,
                task_id=task,
                engine_mode=engine_mode,
                progress_callback=progress_callback
            )
            
            progress.update(task_id, description="✅ 评分完成")
        
        # 输出结果摘要
        console.print()
        console.print("[bold green]✅ 评分完成！[/bold green]")
        console.print()
        console.print(f"[bold]综合得分: {result.scores.overall_100:.1f}[/bold]")
        console.print(f"  发音: {result.scores.pronunciation_100:.1f}")
        console.print(f"  流利: {result.scores.fluency_100:.1f}")
        console.print(f"  语调: {result.scores.intonation_100:.1f}")
        console.print(f"  完整: {result.scores.completeness_100:.1f}")
        console.print()
        console.print(f"JSON: {json_path}")
        console.print(f"HTML: {html_path}")
        
    except Exception as e:
        console.print(f"[red]❌ 评分失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def run(
    manifest: Path = typer.Option(..., "--manifest", help="提交清单 CSV 文件"),
    tasks: Path = typer.Option(..., "--tasks", help="任务配置 YAML 文件"),
    engine: str = typer.Option("auto", "--engine", help="默认引擎模式"),
    jobs: int = typer.Option(4, "--jobs", "-j", help="并发任务数"),
    out: Path = typer.Option(Path("./data/out"), "--out", help="输出目录"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="配置文件路径"),
) -> None:
    """
    批量评分
    
    根据 manifest CSV 文件批量处理多个音频文件。
    """
    from rich.progress import BarColumn, MofNCompleteColumn, TimeElapsedColumn
    from src.batch import build_submissions, load_tasks, run_batch
    
    # 加载配置
    load_config(config_path)
    
    # 验证输入文件
    if not manifest.exists():
        console.print(f"[red]错误: Manifest 文件不存在: {manifest}[/red]")
        raise typer.Exit(1)
    
    if not tasks.exists():
        console.print(f"[red]错误: 任务配置文件不存在: {tasks}[/red]")
        raise typer.Exit(1)
    
    # 解析引擎模式
    try:
        engine_mode = EngineMode(engine.lower())
    except ValueError:
        console.print(f"[red]错误: 无效的引擎模式: {engine}[/red]")
        raise typer.Exit(1)
    
    console.print(f"\n[bold blue]📦 开始批量评分[/bold blue]")
    console.print(f"  Manifest: {manifest}")
    console.print(f"  Tasks: {tasks}")
    console.print(f"  引擎: {engine_mode.value}")
    console.print(f"  并发: {jobs}")
    console.print()
    
    try:
        # 加载任务配置
        task_configs = load_tasks(tasks)
        console.print(f"已加载 {len(task_configs)} 个任务配置")
        
        # 构建提交列表
        submissions = build_submissions(manifest, task_configs)
        console.print(f"共 {len(submissions)} 个提交待处理")
        console.print()
        
        if not submissions:
            console.print("[yellow]没有需要处理的提交[/yellow]")
            return
        
        # 使用进度条
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            progress_task = progress.add_task(
                "处理中...",
                total=len(submissions),
            )
            
            def progress_callback(completed: int, total: int, sub_id: str, success: bool):
                status = "✅" if success else "❌"
                progress.update(
                    progress_task,
                    completed=completed,
                    description=f"{status} {sub_id[:20]}...",
                )
            
            # 执行批量处理
            summary = run_batch(
                submissions=submissions,
                output_dir=out,
                engine_mode=engine_mode,
                max_workers=jobs,
                progress_callback=progress_callback,
            )
        
        # 输出结果摘要
        console.print()
        console.print("[bold green]✅ 批量评分完成！[/bold green]")
        console.print()
        console.print(f"  总计: {summary['total']}")
        console.print(f"  成功: [green]{summary['success']}[/green]")
        console.print(f"  失败: [red]{summary['failed']}[/red]")
        console.print()
        console.print(f"输出目录: {out}")
        
        # 如果有失败，列出失败项
        if summary['failed'] > 0:
            console.print()
            console.print("[yellow]失败详情:[/yellow]")
            for result in summary['results']:
                if not result['success']:
                    console.print(
                        f"  - {result['student_id']}/{result['task_id']}: "
                        f"{result['error']}"
                    )
        
    except Exception as e:
        console.print(f"[red]❌ 批量评分失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def validate(
    manifest: Path = typer.Option(..., "--manifest", help="提交清单 CSV 文件"),
    tasks: Path = typer.Option(..., "--tasks", help="任务配置 YAML 文件"),
) -> None:
    """
    校验输入文件
    
    检查 manifest 中的文件是否存在，字段是否完整。
    """
    from src.batch import validate_manifest
    
    console.print(f"\n[bold blue]🔍 校验输入文件[/bold blue]")
    console.print(f"  Manifest: {manifest}")
    console.print(f"  Tasks: {tasks}")
    console.print()
    
    # 验证输入文件存在
    if not manifest.exists():
        console.print(f"[red]错误: Manifest 文件不存在: {manifest}[/red]")
        raise typer.Exit(1)
    
    if not tasks.exists():
        console.print(f"[red]错误: 任务配置文件不存在: {tasks}[/red]")
        raise typer.Exit(1)
    
    try:
        result = validate_manifest(manifest, tasks)
        
        console.print(f"总行数: {result['total_rows']}")
        console.print()
        
        if result['valid']:
            console.print("[bold green]✅ 校验通过！[/bold green]")
        else:
            console.print("[bold red]❌ 校验失败[/bold red]")
        
        # 显示错误
        if result['errors']:
            console.print()
            console.print(f"[red]错误 ({len(result['errors'])}):[/red]")
            for err in result['errors'][:10]:  # 最多显示 10 条
                if 'row' in err:
                    console.print(f"  行 {err['row']}: {err['message']}")
                else:
                    console.print(f"  {err['message']}")
            
            if len(result['errors']) > 10:
                console.print(f"  ... 还有 {len(result['errors']) - 10} 条错误")
        
        # 显示警告
        if result['warnings']:
            console.print()
            console.print(f"[yellow]警告 ({len(result['warnings'])}):[/yellow]")
            for warn in result['warnings'][:5]:  # 最多显示 5 条
                if 'row' in warn:
                    console.print(f"  行 {warn['row']}: {warn['message']}")
                else:
                    console.print(f"  {warn['message']}")
        
        if not result['valid']:
            raise typer.Exit(1)
            
    except Exception as e:
        console.print(f"[red]❌ 校验失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def report(
    json_file: Path = typer.Option(..., "--json", help="JSON 结果文件路径"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="输出 HTML 路径"),
    config_path: Optional[Path] = typer.Option(None, "--config", help="配置文件路径"),
) -> None:
    """
    从 JSON 重新生成 HTML 报告
    """
    load_config(config_path)
    
    if not json_file.exists():
        console.print(f"[red]错误: JSON 文件不存在: {json_file}[/red]")
        raise typer.Exit(1)
    
    # 确定输出路径
    if output is None:
        output = json_file.with_suffix(".html")
    
    try:
        regenerate_report_from_json(json_file, output)
        console.print(f"[green]✅ HTML 报告已生成: {output}[/green]")
    except Exception as e:
        console.print(f"[red]❌ 报告生成失败: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """显示版本信息"""
    from src import __version__
    console.print(f"score_reading v{__version__}")


def main() -> None:
    """CLI 主入口"""
    app()


if __name__ == "__main__":
    main()
