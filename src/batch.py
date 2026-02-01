"""
口语评分 CLI 框架 - 批量处理模块

支持从 manifest CSV 批量处理音频文件。
"""
import csv
import json
import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

import yaml

from src.advice.generator import generate_feedback
from src.config import config, load_config
from src.models import EngineMode, Meta, ScoringResult
from src.pipeline.analyze import analyze_results, assign_tags
from src.pipeline.normalize import normalize_scores
from src.pipeline.preprocess import preprocess_audio
from src.pipeline.router import run_with_fallback
from src.report.render_html import render_html_report

logger = logging.getLogger(__name__)


@dataclass
class Submission:
    """
    单条提交记录
    """
    task_id: str
    student_id: str
    student_name: str
    audio_path: Path
    script_text: str
    
    # 可选字段
    extra_data: dict | None = None


@dataclass
class TaskConfig:
    """
    任务配置
    """
    task_id: str
    script_text: str
    engine: str = "auto"
    
    # 可选覆盖配置
    overrides: dict | None = None


def load_manifest(manifest_path: Path) -> Iterator[dict]:
    """
    加载 manifest CSV 文件
    
    CSV 格式要求：
    - 必须包含列：task_id, student_id, audio_path
    - 可选列：student_name, script_text（如果 tasks.yaml 中有定义则可省略）
    
    Args:
        manifest_path: CSV 文件路径
        
    Yields:
        每行数据的字典
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest 文件不存在: {manifest_path}")
    
    with open(manifest_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        
        # 验证必须的列
        required_columns = {"task_id", "student_id", "audio_path"}
        if not required_columns.issubset(set(reader.fieldnames or [])):
            missing = required_columns - set(reader.fieldnames or [])
            raise ValueError(f"Manifest 缺少必要的列: {missing}")
        
        for row in reader:
            yield row


def load_tasks(tasks_path: Path) -> dict[str, TaskConfig]:
    """
    加载任务配置 YAML 文件
    
    YAML 格式：
    ```yaml
    tasks:
      task_id_1:
        script_text: "Hello world"
        engine: auto
      task_id_2:
        script_text: "Another text"
    ```
    
    Args:
        tasks_path: YAML 文件路径
        
    Returns:
        task_id -> TaskConfig 的映射
    """
    if not tasks_path.exists():
        raise FileNotFoundError(f"任务配置文件不存在: {tasks_path}")
    
    with open(tasks_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    
    tasks: dict[str, TaskConfig] = {}
    
    for task_id, task_data in data.get("tasks", {}).items():
        tasks[task_id] = TaskConfig(
            task_id=task_id,
            script_text=task_data.get("script_text", ""),
            engine=task_data.get("engine", "auto"),
            overrides=task_data.get("overrides"),
        )
    
    return tasks


def build_submissions(
    manifest_path: Path,
    tasks: dict[str, TaskConfig],
    base_dir: Path | None = None,
) -> list[Submission]:
    """
    从 manifest 构建提交列表
    
    Args:
        manifest_path: CSV 文件路径
        tasks: 任务配置映射
        base_dir: 音频文件基准目录（如果 audio_path 是相对路径）
        
    Returns:
        Submission 列表
    """
    submissions: list[Submission] = []
    
    if base_dir is None:
        base_dir = manifest_path.parent
    
    for row in load_manifest(manifest_path):
        task_id = row["task_id"]
        student_id = row["student_id"]
        audio_path_str = row["audio_path"]
        
        # 解析音频路径
        audio_path = Path(audio_path_str)
        if not audio_path.is_absolute():
            audio_path = base_dir / audio_path
        
        # 获取 script_text
        if "script_text" in row and row["script_text"]:
            script_text = row["script_text"]
        elif task_id in tasks:
            script_text = tasks[task_id].script_text
        else:
            logger.warning(f"未找到 task {task_id} 的 script_text，跳过")
            continue
        
        # 构建提交
        submission = Submission(
            task_id=task_id,
            student_id=student_id,
            student_name=row.get("student_name", student_id),
            audio_path=audio_path,
            script_text=script_text,
        )
        
        submissions.append(submission)
    
    return submissions


def process_single_submission(
    submission: Submission,
    output_dir: Path,
    engine_mode: EngineMode,
) -> tuple[str, bool, str | None]:
    """
    处理单个提交
    
    Args:
        submission: 提交数据
        output_dir: 输出目录
        engine_mode: 引擎模式
        
    Returns:
        (submission_id, success, error_message)
    """
    import hashlib
    
    start_time = time.time()
    
    # 生成 submission_id
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_hash = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    submission_id = f"sub_{timestamp}_{random_hash}"
    
    # 输出目录
    sub_output_dir = output_dir / submission.task_id / submission.student_id / submission_id
    sub_output_dir.mkdir(parents=True, exist_ok=True)
    
    # 初始化结果
    result = ScoringResult()
    result.meta = Meta(
        task_id=submission.task_id,
        student_id=submission.student_id,
        student_name=submission.student_name,
        submission_id=submission_id,
        timestamp=datetime.now().isoformat(),
    )
    result.script_text = submission.script_text
    
    try:
        # 检查音频文件
        if not submission.audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {submission.audio_path}")
        
        with tempfile.TemporaryDirectory() as work_dir:
            work_path = Path(work_dir)
            
            # 1. 预处理
            wav_path, audio_metrics = preprocess_audio(
                submission.audio_path, work_path
            )
            result.audio = audio_metrics
            
            # 2. 运行引擎
            alignment, engine_raw, engine_used, fallback_chain = run_with_fallback(
                wav_path=wav_path,
                script_text=submission.script_text,
                work_dir=work_path,
                engine_mode=engine_mode,
                audio_metrics=audio_metrics,
            )
            
            result.alignment = alignment
            result.engine_raw = engine_raw
            result.meta.engine_used = engine_used
            result.meta.fallback_chain = fallback_chain
            
            # 3. 分数归一化
            result.scores = normalize_scores(
                engine_raw=engine_raw,
                audio_metrics=audio_metrics,
                alignment=alignment,
                script_text=submission.script_text,
            )
            
            # 分配标签
            assign_tags(alignment)
            
            # 4. 分析
            result.analysis = analyze_results(
                alignment, submission.script_text, engine_raw
            )
            
            # 5. 生成建议
            result.feedback = generate_feedback(result.analysis)
            
            # 计算处理时间
            result.meta.processing_time_ms = int((time.time() - start_time) * 1000)
            
            # 6. 保存结果
            json_path = sub_output_dir / f"{submission_id}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
            
            html_path = sub_output_dir / f"{submission_id}.html"
            render_html_report(result, html_path)
        
        logger.info(
            f"✅ {submission.student_id}/{submission.task_id}: "
            f"score={result.scores.overall_100:.1f}"
        )
        return submission_id, True, None
        
    except Exception as e:
        # 记录错误
        result.error = str(e)
        result.meta.processing_time_ms = int((time.time() - start_time) * 1000)
        
        # 保存错误结果
        json_path = sub_output_dir / f"{submission_id}.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
        
        logger.error(f"❌ {submission.student_id}/{submission.task_id}: {e}")
        return submission_id, False, str(e)


def run_batch(
    submissions: list[Submission],
    output_dir: Path,
    engine_mode: EngineMode = EngineMode.AUTO,
    max_workers: int = 4,
    progress_callback: Callable[[int, int, str, bool], None] | None = None,
) -> dict:
    """
    批量处理提交
    
    Args:
        submissions: 提交列表
        output_dir: 输出目录
        engine_mode: 默认引擎模式
        max_workers: 最大并发数
        progress_callback: 进度回调函数 (completed, total, submission_id, success)
        
    Returns:
        处理结果摘要
    """
    total = len(submissions)
    success_count = 0
    failed_count = 0
    results: list[dict] = []
    
    logger.info(f"开始批量处理 {total} 个提交，并发数: {max_workers}")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_submission = {
            executor.submit(
                process_single_submission,
                sub,
                output_dir,
                engine_mode,
            ): sub
            for sub in submissions
        }
        
        # 收集结果
        for i, future in enumerate(as_completed(future_to_submission), 1):
            submission = future_to_submission[future]
            
            try:
                submission_id, success, error = future.result()
                
                results.append({
                    "task_id": submission.task_id,
                    "student_id": submission.student_id,
                    "submission_id": submission_id,
                    "success": success,
                    "error": error,
                })
                
                if success:
                    success_count += 1
                else:
                    failed_count += 1
                
                if progress_callback:
                    progress_callback(i, total, submission_id, success)
                    
            except Exception as e:
                logger.error(f"处理异常: {e}")
                failed_count += 1
                results.append({
                    "task_id": submission.task_id,
                    "student_id": submission.student_id,
                    "submission_id": None,
                    "success": False,
                    "error": str(e),
                })
    
    summary = {
        "total": total,
        "success": success_count,
        "failed": failed_count,
        "results": results,
    }
    
    logger.info(
        f"批量处理完成: 成功 {success_count}/{total}, 失败 {failed_count}"
    )
    
    return summary


def validate_manifest(
    manifest_path: Path,
    tasks_path: Path,
    base_dir: Path | None = None,
) -> dict:
    """
    校验 manifest 文件
    
    检查：
    - 所有必须字段是否存在
    - 音频文件是否存在
    - task_id 是否在 tasks.yaml 中定义
    
    Args:
        manifest_path: CSV 文件路径
        tasks_path: YAML 文件路径
        base_dir: 音频文件基准目录
        
    Returns:
        校验结果
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    
    if base_dir is None:
        base_dir = manifest_path.parent
    
    # 加载任务配置
    try:
        tasks = load_tasks(tasks_path)
    except Exception as e:
        return {
            "valid": False,
            "errors": [{"type": "config", "message": f"无法加载任务配置: {e}"}],
            "warnings": [],
            "total_rows": 0,
        }
    
    row_count = 0
    
    for i, row in enumerate(load_manifest(manifest_path), 1):
        row_count += 1
        task_id = row.get("task_id", "")
        student_id = row.get("student_id", "")
        audio_path_str = row.get("audio_path", "")
        
        # 检查 task_id
        if task_id not in tasks:
            if "script_text" not in row or not row["script_text"]:
                errors.append({
                    "row": i,
                    "type": "missing_script",
                    "message": f"task_id '{task_id}' 未在 tasks.yaml 中定义，且未提供 script_text",
                })
        
        # 检查音频文件
        audio_path = Path(audio_path_str)
        if not audio_path.is_absolute():
            audio_path = base_dir / audio_path
        
        if not audio_path.exists():
            errors.append({
                "row": i,
                "type": "missing_audio",
                "message": f"音频文件不存在: {audio_path}",
            })
        
        # 检查文件扩展名
        suffix = audio_path.suffix.lower()
        if suffix not in {".mp3", ".wav", ".m4a", ".flac", ".ogg"}:
            warnings.append({
                "row": i,
                "type": "unsupported_format",
                "message": f"可能不支持的音频格式: {suffix}",
            })
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total_rows": row_count,
    }
