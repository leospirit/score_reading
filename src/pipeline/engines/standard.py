import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from src.config import config
from src.models import (
    Alignment,
    PhonemeAlignment,
    PhonemeTag,
    WordAlignment,
    WordTag,
)

logger = logging.getLogger(__name__)


class StandardEngine:
    """
    Standard 引擎
    
    使用 kaldi-dnn-ali-gop 进行强制对齐和 GOP 发音评分。
    集成 Librosa 进行声学特征提取 (Pitch, Energy, Stress)。
    """
    
    def __init__(self) -> None:
        self.docker_image = config.get(
            "engines.standard.docker_image",
            "score-reading/kaldi-gop:latest"
        )
        self.timeout = config.get("engines.standard.timeout_sec", 120)
    
    def run(
        self,
        wav_path: Path,
        script_text: str,
        work_dir: Path,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        运行 Standard 引擎
        """
        logger.info("Standard 引擎开始运行")
        
        # 准备输入
        audio_dir = work_dir / "audio_input"
        result_dir = work_dir / "result"
        audio_dir.mkdir(parents=True, exist_ok=True)
        result_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建 speaker 目录结构
        speaker_dir = audio_dir / "speaker1"
        speaker_dir.mkdir(exist_ok=True)
        
        # 复制/链接音频文件
        target_wav = speaker_dir / "utt1.wav"
        if not target_wav.exists():
            import shutil
            shutil.copy(wav_path, target_wav)
        
        # 创建 lab 文件（标准文本）
        lab_path = speaker_dir / "utt1.lab"
        lab_path.write_text(script_text.upper(), encoding="utf-8")
        
        alignment = None
        engine_raw = {}

        try:
            # 1. 尝试运行 Kaldi (ASR/GOP)
            alignment, engine_raw = self._run_kaldi_gop(
                audio_dir, result_dir, script_text
            )
        except Exception as e:
            logger.warning(f"Standard 引擎 Kaldi 部分运行失败 (可能未安装 Docker): {e}")
            logger.info("回退到模拟对齐模式，但将尝试提取真实声学特征...")
            # 回退：生成模拟对齐
            alignment, engine_raw = self._generate_mock_result(script_text)

        # 2. 增强：提取声学特征并计算 Stress
        # 无论对齐是来自 Kaldi 还是 Mock，只要有 WAV 文件，我们都可以计算 Stress
        try:
            logger.info("开始提取声学特征 (Librosa)...")
            self._enrich_with_acoustic_features(alignment, wav_path)
            engine_raw["acoustic_features_extracted"] = True
        except Exception as e:
            logger.error(f"声学特征提取失败: {e}")
            engine_raw["acoustic_features_error"] = str(e)
            
        return alignment, engine_raw
    
    def _run_kaldi_gop(
        self,
        audio_dir: Path,
        result_dir: Path,
        script_text: str,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        执行 Kaldi GOP 评分
        """
        logger.info(f"准备调用 Kaldi GOP: audio_dir={audio_dir}")
        
        textgrid_dir = result_dir / "aligned_textgrid"
        gop_file = result_dir / "gop.txt"
        
        if self._check_docker_available() and self._check_kaldi_image():
            self._execute_kaldi_docker(audio_dir, result_dir)
            
            if textgrid_dir.exists() and gop_file.exists():
                alignment = self._parse_textgrid(textgrid_dir / "speaker1_utt1.TextGrid")
                gop_scores = self._parse_gop_file(gop_file)
                self._merge_gop_scores(alignment, gop_scores)
                
                engine_raw = {
                    "gop_mean": self._calculate_gop_mean(gop_scores),
                    "word_gop": gop_scores.get("words", {}),
                    "phoneme_gop": gop_scores.get("phonemes", {}),
                }
                return alignment, engine_raw
        
        raise RuntimeError("Kaldi Docker 环境不可用")

    def _enrich_with_acoustic_features(self, alignment: Alignment, wav_path: Path) -> None:
        """
        提取 Pitch/Energy 并计算单词 Stress
        """
        try:
            import librosa
        except ImportError:
            logger.warning("librosa 未安装，跳过声学特征提取")
            return

        # 1. 加载音频
        y, sr = librosa.load(wav_path, sr=16000)
        
        # 2. 提取 F0 (Pitch) - 使用 Yin 算法
        f0 = librosa.yin(y, fmin=50, fmax=300, sr=sr)
        # 处理无声段 (NaN) -> 0
        f0 = np.nan_to_num(f0)
        
        # 3. 提取 RMS (Energy)
        rms = librosa.feature.rms(y=y)[0]
        
        # 4. 对齐时间轴
        # f0 和 rms 的帧长通常是 hop_length (默认 512)
        hop_length = 512 # librosa default
        times = librosa.times_like(rms, sr=sr, hop_length=hop_length)
        
        # 全局统计 (用于归一化)
        # 过滤掉静音段/异常值计算 mean/max
        valid_f0 = f0[f0 > 50] # > 50Hz
        valid_rms = rms[rms > 0.001]
        
        mean_f0 = np.mean(valid_f0) if len(valid_f0) > 0 else 100.0
        std_f0 = np.std(valid_f0) if len(valid_f0) > 0 else 20.0
        
        max_rms = np.max(valid_rms) if len(valid_rms) > 0 else 0.1
        
        # 5. 为每个单词计算 Stress
        for word in alignment.words:
            # 找到对应的时间帧索引
            start_frame = np.searchsorted(times, word.start)
            end_frame = np.searchsorted(times, word.end)
            
            if start_frame >= end_frame:
                continue
                
            w_f0 = f0[start_frame:end_frame]
            w_rms = rms[start_frame:end_frame]
            
            # 计算单词内的特征值
            # Stress 定义: 高音 (Pitch High) + 响度 (Loudness) + 时长 (Duration)
            # 这里简化为 Pitch Max + RMS Max 的加权
            
            w_max_f0 = np.max(w_f0) if len(w_f0) > 0 else 0
            w_max_rms = np.max(w_rms) if len(w_rms) > 0 else 0
            
            # 归一化 Score (0.0 - 1.0)
            # Z-score normalization for pitch
            score_pitch = 0.0
            if std_f0 > 0:
                z_pitch = (w_max_f0 - mean_f0) / std_f0
                # 假设 z-score 2.0 以上为显著高音
                score_pitch = np.clip((z_pitch + 1) / 3, 0, 1) # simple sigmoid-ish mapping
            
            # linear normalization for rms
            score_rms = np.clip(w_max_rms / max_rms, 0, 1)
            
            # 综合 Stress: 60% Pitch, 40% Energy
            stress = 0.6 * score_pitch + 0.4 * score_rms
            
            # 放大差异，让重读更明显
            word.stress = round(stress, 2)
            
            # Debug log
            # logger.debug(f"Word: {word.word}, Pitch: {score_pitch:.2f}, Energy: {score_rms:.2f}, Stress: {word.stress}")

    def _check_docker_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            result = subprocess.run(
                ["docker", "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _check_kaldi_image(self) -> bool:
        """检查 Kaldi Docker 镜像是否存在"""
        try:
            result = subprocess.run(
                ["docker", "images", "-q", self.docker_image],
                capture_output=True,
                timeout=10,
            )
            return bool(result.stdout.strip())
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _execute_kaldi_docker(self, audio_dir: Path, result_dir: Path) -> None:
        """执行 Kaldi Docker 容器"""
        cmd = [
            "docker", "run", "--rm",
            "-v", f"{audio_dir}:/app/audio_dir:ro",
            "-v", f"{result_dir}:/app/result_dir",
            self.docker_image,
            "/app/run.sh", "/app/audio_dir", "/app/data_dir", "/app/result_dir",
        ]
        
        logger.info(f"执行 Docker 命令: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=self.timeout,
        )
        
        if result.returncode != 0:
            raise RuntimeError(f"Kaldi 执行失败: {result.stderr.decode()}")
    
    def _parse_textgrid(self, textgrid_path: Path) -> Alignment:
        """
        解析 TextGrid 文件获取对齐信息
        """
        try:
            import textgrid
            
            tg = textgrid.TextGrid.fromFile(str(textgrid_path))
            
            alignment = Alignment()
            
            # 解析 words tier
            for tier in tg.tiers:
                if tier.name.lower() in ("words", "word"):
                    for interval in tier:
                        if interval.mark and interval.mark.strip():
                            alignment.words.append(WordAlignment(
                                word=interval.mark.strip(),
                                start=interval.minTime,
                                end=interval.maxTime,
                            ))
                
                elif tier.name.lower() in ("phones", "phonemes", "phone"):
                    current_word = ""
                    word_idx = 0
                    
                    for interval in tier:
                        if interval.mark and interval.mark.strip():
                            # 尝试关联到词
                            if word_idx < len(alignment.words):
                                word = alignment.words[word_idx]
                                if interval.minTime >= word.end:
                                    word_idx += 1
                                    if word_idx < len(alignment.words):
                                        current_word = alignment.words[word_idx].word
                                else:
                                    current_word = word.word
                            
                            alignment.phonemes.append(PhonemeAlignment(
                                phoneme=interval.mark.strip(),
                                start=interval.minTime,
                                end=interval.maxTime,
                                in_word=current_word,
                            ))
            
            return alignment
            
        except ImportError:
            logger.warning("textgrid 库未安装，无法解析 TextGrid")
            return Alignment()
        except Exception as e:
            logger.error(f"解析 TextGrid 失败: {e}")
            return Alignment()
    
    def _parse_gop_file(self, gop_path: Path) -> dict[str, Any]:
        """
        解析 GOP 分数文件
        """
        gop_scores: dict[str, Any] = {"words": {}, "phonemes": {}}
        
        try:
            content = gop_path.read_text(encoding="utf-8")
            
            # GOP 文件格式通常为: utterance_id phone gop_score
            for line in content.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 3:
                    phone = parts[1]
                    try:
                        score = float(parts[2])
                        if phone not in gop_scores["phonemes"]:
                            gop_scores["phonemes"][phone] = []
                        gop_scores["phonemes"][phone].append(score)
                    except ValueError:
                        continue
            
        except Exception as e:
            logger.error(f"解析 GOP 文件失败: {e}")
        
        return gop_scores
    
    def _merge_gop_scores(
        self, alignment: Alignment, gop_scores: dict[str, Any]
    ) -> None:
        """将 GOP 分数合并到对齐结果"""
        phoneme_scores = gop_scores.get("phonemes", {})
        
        for phoneme in alignment.phonemes:
            if phoneme.phoneme in phoneme_scores:
                scores = phoneme_scores[phoneme.phoneme]
                if scores:
                    # 使用平均分或最小分
                    phoneme.score = self._gop_to_100(min(scores))
        
        # 计算词级分数（取其中音素的最低分）
        for word in alignment.words:
            word_phonemes = [
                p for p in alignment.phonemes if p.in_word == word.word
            ]
            if word_phonemes:
                word.score = min(p.score for p in word_phonemes)
    
    def _gop_to_100(self, gop: float) -> float:
        """将 GOP 分数转换为 0-100"""
        # GOP 通常为负数，-10 到 0
        gop_min = -10.0
        gop_max = 0.0
        clamped = max(gop_min, min(gop_max, gop))
        return (clamped - gop_min) / (gop_max - gop_min) * 100
    
    def _calculate_gop_mean(self, gop_scores: dict[str, Any]) -> float:
        """计算平均 GOP 分数"""
        all_scores = []
        for scores in gop_scores.get("phonemes", {}).values():
            all_scores.extend(scores)
        
        if all_scores:
            return sum(all_scores) / len(all_scores)
        return -5.0  # 默认中间值
    
    def _generate_mock_result(
        self, script_text: str
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        生成模拟结果（用于开发测试）
        
        基于文本生成合理的对齐和分数数据。
        """
        import random
        
        alignment = Alignment()
        words = script_text.split()
        
        current_time = 0.3  # 开始时间
        
        for word in words:
            # 估算词时长（基于词长）
            word_duration = 0.1 + len(word) * 0.08
            
            # 生成词对齐
            word_score = random.uniform(60, 95)
            alignment.words.append(WordAlignment(
                word=word.lower().strip(".,!?;:'\""),
                start=current_time,
                end=current_time + word_duration,
                score=word_score,
            ))
            
            # 生成简化的音素对齐
            # NOTE: 实际应使用词典进行 G2P 转换
            phoneme_count = max(1, len(word) // 2)
            phoneme_duration = word_duration / phoneme_count
            
            for i in range(phoneme_count):
                phoneme_score = random.uniform(55, 98)
                alignment.phonemes.append(PhonemeAlignment(
                    phoneme=f"P{i}",  # 模拟音素
                    start=current_time + i * phoneme_duration,
                    end=current_time + (i + 1) * phoneme_duration,
                    score=phoneme_score,
                    in_word=word.lower().strip(".,!?;:'\""),
                ))
            
            current_time += word_duration + random.uniform(0.1, 0.3)
        
        # 生成模拟的引擎原始数据
        engine_raw = {
            "gop_mean": random.uniform(-4, -2),
            "alignment_confidence": random.uniform(0.85, 0.98),
            "mock": True,
        }
        
        return alignment, engine_raw


# 模块级别的引擎实例
_engine_instance: StandardEngine | None = None


def get_standard_engine() -> StandardEngine:
    """获取 Standard 引擎单例"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = StandardEngine()
    return _engine_instance


def run_standard_engine(
    wav_path: Path,
    script_text: str,
    work_dir: Path,
) -> tuple[Alignment, dict[str, Any]]:
    """
    运行 Standard 引擎的便捷函数
    """
    engine = get_standard_engine()
    return engine.run(wav_path, script_text, work_dir)

