"""
口语评分 CLI 框架 - 配置加载模块

负责加载和管理配置文件。
"""
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# 默认配置文件路径
DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config" / "default.yaml"


class Config:
    """配置管理类"""
    
    _instance: "Config | None" = None
    _data: dict[str, Any] = {}
    
    def __new__(cls) -> "Config":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def load(self, config_path: Path | None = None) -> None:
        """
        加载配置文件
        
        Args:
            config_path: 配置文件路径，如果为 None 则使用默认路径
        """
        path = config_path or DEFAULT_CONFIG_PATH
        
        if not path.exists():
            logger.warning(f"配置文件不存在: {path}，使用默认配置")
            self._data = self._get_default_config()
            return
        
        with open(path, encoding="utf-8") as f:
            self._data = yaml.safe_load(f) or {}
        
        logger.info(f"已加载配置文件: {path}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值，支持点号分隔的嵌套键
        
        Args:
            key: 配置键，支持 "a.b.c" 格式
            default: 默认值
            
        Returns:
            配置值或默认值
        """
        keys = key.split(".")
        value = self._data
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def _get_default_config(self) -> dict[str, Any]:
        """返回内置默认配置"""
        return {
            "audio": {
                "sample_rate": 16000,
                "channels": 1,
                "bit_depth": 16,
            },
            "quality_thresholds": {
                "min_duration_sec": 2.5,
                "max_silence_ratio": 0.35,
                "min_rms_db": -28,
                "max_clipping_ratio": 0.1,
            },
            "normalization": {
                "gop": {"min": -10.0, "max": 0.0},
                "fluency": {
                    "silence_penalty_weight": 50,
                    "pause_penalty_weight": 20,
                },
                "intonation": {"energy_variance_weight": 0.5},
            },
            "analysis": {
                "weak_words_top_n": 3,
                "weak_phonemes_top_n": 2,
                "confusions_top_n": 2,
                "word_thresholds": {"ok": 70, "weak": 40},
                "phoneme_thresholds": {"ok": 70, "weak": 40},
            },
            "fallback": {
                "max_missing_words_ratio": 0.25,
                "retry_count": 1,
            },
            "report": {
                "colors": {
                    "ok": "#4CAF50",
                    "weak": "#FFC107",
                    "missing": "#F44336",
                    "poor": "#E91E63",
                },
                "show_audio_player": True,
                "show_phoneme_details": True,
            },
            "engines": {
                "standard": {
                    "docker_image": "score-reading/kaldi-gop:latest",
                    "timeout_sec": 120,
                },
                "fast": {
                    "service_url": "http://gentle:8765",
                    "timeout_sec": 30,
                },
                "pro": {"enabled": False},
            },
            "concurrency": {
                "default_jobs": 4,
                "max_jobs": 16,
            },
        }


# 全局配置实例
config = Config()


def load_config(config_path: Path | None = None) -> Config:
    """
    加载配置并返回配置实例
    
    Args:
        config_path: 配置文件路径
        
    Returns:
        配置实例
    """
    config.load(config_path)
    return config
