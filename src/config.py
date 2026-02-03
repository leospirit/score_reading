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
import os
# User config path (can be overridden by env var for Docker)
USER_CONFIG_PATH = Path(os.getenv("USER_CONFIG_PATH", Path.home() / ".score_reading" / "config.yaml"))


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
        
        优先加载如果指定的 config_path。
        如果未指定，则加载默认配置，并尝试合并用户配置。
        """
        # 1. 加载默认配置
        self._data = self._get_default_config()
        
        # 2. 如果有默认配置文件，覆盖内置默认值 (可选)
        if DEFAULT_CONFIG_PATH.exists():
            with open(DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
                default_file_data = yaml.safe_load(f) or {}
                self._merge_config(self._data, default_file_data)

        # 3. 如果指定了配置文件，加载并覆盖
        if config_path:
            if config_path.exists():
                with open(config_path, encoding="utf-8") as f:
                    custom_data = yaml.safe_load(f) or {}
                    self._merge_config(self._data, custom_data)
                logger.info(f"已加载自定义配置文件: {config_path}")
            else:
                logger.warning(f"指定配置文件不存在: {config_path}")
                
        # 4. 如果没指定配置文件，尝试加载用户配置 (~/.score_reading/config.yaml)
        elif USER_CONFIG_PATH.exists():
            try:
                with open(USER_CONFIG_PATH, encoding="utf-8") as f:
                    user_data = yaml.safe_load(f) or {}
                    self._merge_config(self._data, user_data)
                logger.info(f"已加载用户配置文件: {USER_CONFIG_PATH}")
            except Exception as e:
                logger.warning(f"加载用户配置失败: {e}")

    def save_user_config(self, updates: dict[str, Any]) -> None:
        """
        保存用户配置
        
        Args:
            updates: 要更新的配置项 (合并到现有用户配置)
        """
        USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        current_user_data = {}
        if USER_CONFIG_PATH.exists():
            try:
                with open(USER_CONFIG_PATH, encoding="utf-8") as f:
                    current_user_data = yaml.safe_load(f) or {}
            except Exception:
                pass
        
        self._merge_config(current_user_data, updates)
        
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(current_user_data, f, allow_unicode=True, default_flow_style=False)
            
        # Reload to apply changes
        self.load()
        logger.info(f"已保存用户配置: {USER_CONFIG_PATH}")

    def _merge_config(self, base: dict, update: dict) -> None:
        """递归合并配置字典"""
        for k, v in update.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._merge_config(base[k], v)
            else:
                base[k] = v
    
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
