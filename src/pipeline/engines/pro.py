"""
口语评分 CLI 框架 - Pro 引擎（Stub）

预留的高级引擎接口，后续可接入 GOPT 等更高级的模型。
"""
import logging
from pathlib import Path
from typing import Any

from src.models import Alignment
from src.pipeline.engines.standard import run_standard_engine

logger = logging.getLogger(__name__)


class ProEngine:
    """
    Pro 引擎（Stub 实现）
    
    当前为占位实现，直接复用 Standard 引擎的结果。
    后续可接入：
    - GOPT (Goodness of Pronunciation with Transformer)
    - 其他高级发音评估模型
    """
    
    def __init__(self) -> None:
        self.enabled = False
        logger.warning("Pro 引擎当前未启用，将回退到 Standard 引擎")
    
    def run(
        self,
        wav_path: Path,
        script_text: str,
        work_dir: Path,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        运行 Pro 引擎
        
        当前实现：直接复用 Standard 引擎结果。
        
        Args:
            wav_path: WAV 音频文件路径
            script_text: 标准文本
            work_dir: 工作目录
            
        Returns:
            (对齐信息, 引擎原始输出)
        """
        logger.info("Pro 引擎：复用 Standard 引擎")
        
        alignment, engine_raw = run_standard_engine(wav_path, script_text, work_dir)
        
        # 标记为 Pro 引擎结果
        engine_raw["engine_type"] = "pro_stub"
        engine_raw["note"] = "Pro 引擎当前为 Stub 实现，复用 Standard 结果"
        
        return alignment, engine_raw


# 模块级别的引擎实例
_engine_instance: ProEngine | None = None


def get_pro_engine() -> ProEngine:
    """获取 Pro 引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = ProEngine()
    return _engine_instance


def run_pro_engine(
    wav_path: Path,
    script_text: str,
    work_dir: Path,
) -> tuple[Alignment, dict[str, Any]]:
    """
    运行 Pro 引擎的便捷函数
    
    Args:
        wav_path: WAV 音频文件路径
        script_text: 标准文本
        work_dir: 工作目录
        
    Returns:
        (对齐信息, 引擎原始输出)
    """
    engine = get_pro_engine()
    return engine.run(wav_path, script_text, work_dir)
