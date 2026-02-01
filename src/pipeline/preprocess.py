"""
口语评分 CLI 框架 - 预处理模块

负责音频格式转换和质量检测。
"""
import logging
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from pydub import AudioSegment

from src.models import AudioMetrics

logger = logging.getLogger(__name__)

# 目标音频格式
TARGET_SAMPLE_RATE = 16000
TARGET_CHANNELS = 1
TARGET_BIT_DEPTH = 16


def convert_to_wav(input_path: Path, output_path: Path) -> None:
    """
    将音频文件转换为标准 WAV 格式
    
    目标格式：16kHz, mono, 16-bit PCM
    
    Args:
        input_path: 输入音频文件路径（支持 MP3, WAV, M4A 等）
        output_path: 输出 WAV 文件路径
        
    Raises:
        FileNotFoundError: 输入文件不存在
        RuntimeError: 转换失败
    """
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    
    logger.info(f"转换音频: {input_path} -> {output_path}")
    
    try:
        # 使用 pydub 加载音频
        audio = AudioSegment.from_file(str(input_path))
        
        # 转换为目标格式
        audio = audio.set_frame_rate(TARGET_SAMPLE_RATE)
        audio = audio.set_channels(TARGET_CHANNELS)
        audio = audio.set_sample_width(TARGET_BIT_DEPTH // 8)
        
        # 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 导出为 WAV
        audio.export(str(output_path), format="wav")
        
        logger.info(f"音频转换完成: 时长 {len(audio) / 1000:.2f}s")
        
    except Exception as e:
        logger.error(f"音频转换失败: {e}")
        raise RuntimeError(f"音频转换失败: {e}") from e


def analyze_audio_quality(wav_path: Path) -> AudioMetrics:
    """
    分析音频质量指标
    
    计算以下指标用于引擎选择和质量评估：
    - duration_sec: 音频时长（秒）
    - silence_ratio: 静音占比（0-1）
    - rms_db: 均方根能量（dB）
    - clipping_ratio: 削波占比（0-1）
    
    Args:
        wav_path: WAV 文件路径
        
    Returns:
        AudioMetrics 对象
        
    Raises:
        FileNotFoundError: 文件不存在
        RuntimeError: 分析失败
    """
    if not wav_path.exists():
        raise FileNotFoundError(f"WAV 文件不存在: {wav_path}")
    
    logger.info(f"分析音频质量: {wav_path}")
    
    try:
        # 加载音频
        audio = AudioSegment.from_wav(str(wav_path))
        
        # 获取原始采样数据
        samples = np.array(audio.get_array_of_samples(), dtype=np.float32)
        
        # 归一化到 [-1, 1]
        max_val = 2 ** (audio.sample_width * 8 - 1)
        samples = samples / max_val
        
        # 计算时长
        duration_sec = len(audio) / 1000.0
        
        # 计算静音占比
        # NOTE: 使用能量阈值判断静音，阈值可根据实际情况调整
        silence_threshold = 0.01  # 能量低于此值认为是静音
        frame_length = int(TARGET_SAMPLE_RATE * 0.025)  # 25ms 帧
        hop_length = int(TARGET_SAMPLE_RATE * 0.010)  # 10ms 步长
        
        silence_frames = 0
        total_frames = 0
        
        for i in range(0, len(samples) - frame_length, hop_length):
            frame = samples[i:i + frame_length]
            frame_energy = np.sqrt(np.mean(frame ** 2))
            total_frames += 1
            if frame_energy < silence_threshold:
                silence_frames += 1
        
        silence_ratio = silence_frames / total_frames if total_frames > 0 else 0.0
        
        # 计算 RMS（dB）
        rms = np.sqrt(np.mean(samples ** 2))
        rms_db = 20 * np.log10(rms + 1e-10)  # 避免 log(0)
        
        # 计算削波占比
        # NOTE: 检测接近最大振幅的采样点
        clipping_threshold = 0.99
        clipping_samples = np.sum(np.abs(samples) > clipping_threshold)
        clipping_ratio = clipping_samples / len(samples)
        
        # NOTE: 将 numpy 类型转换为 Python 原生类型，避免 JSON 序列化问题
        metrics = AudioMetrics(
            duration_sec=float(duration_sec),
            silence_ratio=float(silence_ratio),
            rms_db=float(rms_db),
            clipping_ratio=float(clipping_ratio),
        )
        
        logger.info(
            f"音频质量: 时长={duration_sec:.2f}s, "
            f"静音占比={silence_ratio:.2%}, "
            f"RMS={rms_db:.1f}dB, "
            f"削波={clipping_ratio:.4%}"
        )
        
        return metrics
        
    except Exception as e:
        logger.error(f"音频质量分析失败: {e}")
        raise RuntimeError(f"音频质量分析失败: {e}") from e


def preprocess_audio(input_path: Path, work_dir: Path) -> tuple[Path, AudioMetrics]:
    """
    完整的音频预处理流程
    
    1. 转换为标准 WAV 格式
    2. 分析音频质量
    
    Args:
        input_path: 输入音频文件路径
        work_dir: 工作目录
        
    Returns:
        (WAV 文件路径, 音频质量指标)
    """
    # 生成输出路径
    wav_path = work_dir / "audio.wav"
    
    # 转换格式
    convert_to_wav(input_path, wav_path)
    
    # 分析质量
    metrics = analyze_audio_quality(wav_path)
    
    # 验证音频有效性
    if metrics.duration_sec <= 0:
        raise RuntimeError("音频时长为 0，无法处理")
    
    return wav_path, metrics
