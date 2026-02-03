"""
Whisper 引擎 - 使用 faster-whisper 进行语音转录

提供真实的 ASR 转录功能，支持词级时间戳提取。
"""
import logging
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

# 延迟导入 faster_whisper 以避免在不使用时加载
_whisper_model = None


def _get_whisper_model():
    """延迟加载 Whisper 模型"""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        
        model_size = config.get("engines.whisper.model_size", "base")
        device = config.get("engines.whisper.device", "cpu")
        compute_type = config.get("engines.whisper.compute_type", "int8")
        
        logger.info(f"加载 Whisper 模型: {model_size} (device={device}, compute_type={compute_type})")
        _whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        logger.info("Whisper 模型加载完成")
    
    return _whisper_model


class WhisperEngine:
    """
    Whisper 引擎
    
    使用 faster-whisper 进行语音转录，提取词级时间戳，
    并与标准文本对齐生成评分。
    """
    
    def __init__(self) -> None:
        self.model_size = config.get("engines.whisper.model_size", "base")
    
    def run(
        self,
        wav_path: Path,
        script_text: str,
        work_dir: Path,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        运行 Whisper 转录引擎
        
        Args:
            wav_path: 音频文件路径
            script_text: 标准文本
            work_dir: 工作目录
            
        Returns:
            (Alignment, engine_raw) 元组
        """
        logger.info("Whisper 引擎开始运行")
        
        engine_raw: dict[str, Any] = {
            "engine": "whisper",
            "model_size": self.model_size,
        }
        
        try:
            # 1. 转录音频
            transcript_words = self._transcribe(wav_path)
            engine_raw["transcript_words"] = [
                {"word": w["word"], "start": w["start"], "end": w["end"]}
                for w in transcript_words
            ]
            
            # 2. 对齐转录结果与标准文本
            alignment = self._align_with_script(transcript_words, script_text)
            engine_raw["alignment_method"] = "levenshtein"
            
            # 3. 计算基础评分
            self._calculate_scores(alignment, transcript_words, script_text)
            
            # 4. 提取声学特征 (F0, Energy)
            try:
                pitch_contour = self._extract_acoustic_features(alignment, wav_path)
                engine_raw["pitch_contour"] = pitch_contour
            except Exception as e:
                logger.warning(f"声学特征提取失败: {e}")
            
            logger.info(f"Whisper 引擎完成: 转录 {len(transcript_words)} 词, 对齐 {len(alignment.words)} 词")
            
        except Exception as e:
            logger.error(f"Whisper 引擎运行失败: {e}")
            engine_raw["error"] = str(e)
            # 回退到 Mock 结果
            alignment = self._generate_fallback_result(script_text)
        
        return alignment, engine_raw
    
    def _transcribe(self, wav_path: Path) -> list[dict]:
        """
        使用 Whisper 转录音频
        
        Returns:
            词列表，每个词包含 word, start, end
        """
        model = _get_whisper_model()
        
        # 转录并获取词级时间戳
        segments, info = model.transcribe(
            str(wav_path),
            beam_size=5,
            word_timestamps=True,
            language="en",
        )
        
        logger.info(f"音频语言检测: {info.language} (概率: {info.language_probability:.2f})")
        
        words = []
        for segment in segments:
            if segment.words:
                for word in segment.words:
                    words.append({
                        "word": word.word.strip(),
                        "start": word.start,
                        "end": word.end,
                        "probability": word.probability,
                    })
        
        logger.info(f"Whisper 转录完成: {len(words)} 词")
        return words
    
    def _align_with_script(
        self, 
        transcript_words: list[dict], 
        script_text: str
    ) -> Alignment:
        """
        将转录结果与标准文本对齐
        
        使用 Levenshtein 距离算法进行序列对齐
        """
        # 清理标准文本
        script_words = self._tokenize(script_text)
        trans_words = [w["word"].lower().strip(".,!?;:'\"") for w in transcript_words]
        
        # 计算对齐矩阵
        alignment_pairs = self._levenshtein_align(script_words, trans_words)
        
        # 生成 WordAlignment 列表
        word_alignments = []
        
        for script_idx, trans_idx in alignment_pairs:
            if script_idx is not None and trans_idx is not None:
                # 匹配：正确读出
                tw = transcript_words[trans_idx]
                
                # 检查匹配程度
                script_word = script_words[script_idx]
                trans_word = trans_words[trans_idx]
                
                # NOTE: 评分基于匹配质量，而非 Whisper 原始置信度
                # Whisper 置信度反映的是 ASR 不确定性，不是发音质量
                if script_word == trans_word:
                    # 完全匹配 = 高分
                    tag = WordTag.OK
                    score = 95.0
                elif self._is_similar(script_word, trans_word):
                    # 相似匹配（如大小写不同、略微偏差）= 中等分
                    tag = WordTag.WEAK
                    score = 60.0
                else:
                    # 明显不同 = 低分，但也不是0
                    tag = WordTag.POOR
                    score = 35.0
                    
                word_alignments.append(WordAlignment(
                    word=script_words[script_idx],
                    start=tw["start"],
                    end=tw["end"],
                    tag=tag,
                    score=round(score, 1),
                ))
                
            elif script_idx is not None:
                # 漏读
                word_alignments.append(WordAlignment(
                    word=script_words[script_idx],
                    start=0.0,
                    end=0.0,
                    tag=WordTag.MISSING,
                    score=0.0,
                ))
            # trans_idx is not None but script_idx is None: 多读，忽略
        
        # 为弱词和错词生成模拟音素数据
        phoneme_alignments = self._generate_phonemes_from_words(word_alignments)
        
        return Alignment(words=word_alignments, phonemes=phoneme_alignments)
    
    def _generate_phonemes_from_words(
        self, 
        word_alignments: list[WordAlignment]
    ) -> list[PhonemeAlignment]:
        """
        为弱词和错词生成模拟音素数据
        
        由于 Whisper 不提供音素级别信息，我们基于常见发音规则
        为评分较低的词生成可能的音素问题。
        """
        # 常见易混淆音素映射
        COMMON_PHONEME_ISSUES = {
            # 元音问题
            "a": ("æ", "a vs æ"),
            "e": ("ɛ", "e vs ɛ"),
            "i": ("ɪ", "i vs ɪ"),
            "o": ("ɔ", "o vs ɔ"),
            "u": ("ʊ", "u vs ʊ"),
            # 辅音问题
            "th": ("θ/ð", "th 发音"),
            "r": ("r", "r 卷舌"),
            "l": ("l", "l 发音"),
            "v": ("v", "v vs w"),
            "w": ("w", "w vs v"),
        }
        
        phonemes = []
        for word in word_alignments:
            # 只为弱词和错词生成音素问题
            logger.debug(f"Checking word: {word.word}, tag: {word.tag}, tag in list: {word.tag in [WordTag.WEAK, WordTag.POOR, WordTag.MISSING]}")
            if word.tag not in [WordTag.WEAK, WordTag.POOR, WordTag.MISSING]:
                continue
            
            word_lower = word.word.lower()
            
            # 检测可能的音素问题
            for pattern, (phoneme, issue) in COMMON_PHONEME_ISSUES.items():
                if pattern in word_lower:
                    logger.info(f"生成音素问题: word={word.word}, phoneme={phoneme}, score={word.score * 0.8}")
                    phonemes.append(PhonemeAlignment(
                        phoneme=phoneme,
                        start=word.start,
                        end=word.end,
                        tag=PhonemeTag.WEAK if word.tag == WordTag.WEAK else PhonemeTag.POOR,
                        score=word.score * 0.8,  # 音素得分略低于词得分
                        in_word=word.word,
                    ))
                    break  # 每个词只生成一个音素问题
        
        logger.info(f"生成了 {len(phonemes)} 个音素问题")
        return phonemes

    
    def _tokenize(self, text: str) -> list[str]:
        """分词并清理"""
        import re
        words = re.findall(r"[a-zA-Z']+", text.lower())
        return words
    
    def _levenshtein_align(
        self, 
        seq1: list[str], 
        seq2: list[str]
    ) -> list[tuple[int | None, int | None]]:
        """
        使用 Levenshtein 算法对齐两个序列
        
        Returns:
            (seq1_idx, seq2_idx) 对齐对列表
        """
        m, n = len(seq1), len(seq2)
        
        # 动态规划矩阵
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        
        # 初始化
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        
        # 填充矩阵
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if seq1[i-1] == seq2[j-1]:
                    dp[i][j] = dp[i-1][j-1]
                else:
                    dp[i][j] = min(
                        dp[i-1][j] + 1,    # 删除
                        dp[i][j-1] + 1,    # 插入
                        dp[i-1][j-1] + 1,  # 替换
                    )
        
        # 回溯生成对齐
        alignments = []
        i, j = m, n
        
        while i > 0 or j > 0:
            if i > 0 and j > 0 and (seq1[i-1] == seq2[j-1] or dp[i][j] == dp[i-1][j-1] + 1):
                alignments.append((i-1, j-1))
                i -= 1
                j -= 1
            elif i > 0 and (j == 0 or dp[i][j] == dp[i-1][j] + 1):
                alignments.append((i-1, None))  # 漏读
                i -= 1
            else:
                alignments.append((None, j-1))  # 多读
                j -= 1
        
        alignments.reverse()
        return alignments
    
    def _is_similar(self, word1: str, word2: str) -> bool:
        """检查两个词是否相似（允许轻微发音偏差）"""
        if word1 == word2:
            return True
        # 简单规则：前缀匹配或编辑距离很小
        if word1.startswith(word2[:3]) or word2.startswith(word1[:3]):
            return True
        return False
    
    def _calculate_scores(
        self, 
        alignment: Alignment, 
        transcript_words: list[dict],
        script_text: str
    ) -> None:
        """计算各项评分并更新 WordAlignment"""
        # 基于置信度的发音评分已在对齐时计算
        # 这里计算 Stress (基于时长和能量)
        if not alignment.words:
            return
        
        # 计算平均时长
        durations = [w.end - w.start for w in alignment.words if w.end > w.start]
        if not durations:
            return
        avg_duration = np.mean(durations)
        
        for word in alignment.words:
            if word.end > word.start:
                duration = word.end - word.start
                # 时长长的词视为重读
                word.stress = min(1.0, duration / (avg_duration * 1.5))
    
    def _extract_acoustic_features(
        self, 
        alignment: Alignment, 
        wav_path: Path
    ) -> list[dict]:
        """提取 F0 曲线用于语调可视化"""
        import librosa
        
        y, sr = librosa.load(str(wav_path), sr=16000)
        
        # 提取 F0
        f0, voiced_flag, voiced_probs = librosa.pyin(
            y, 
            fmin=librosa.note_to_hz('C2'),
            fmax=librosa.note_to_hz('C7'),
            sr=sr
        )
        
        # 转换为时间序列
        times = librosa.times_like(f0, sr=sr)
        
        # 降采样并返回
        pitch_contour = []
        for i in range(0, len(times), 5):  # 每 5 帧取一次
            if f0[i] is not None and not np.isnan(f0[i]):
                pitch_contour.append({"t": float(times[i]), "f": float(f0[i])})
        
        return pitch_contour
    
    def _generate_fallback_result(self, script_text: str) -> Alignment:
        """生成回退结果"""
        words = self._tokenize(script_text)
        return Alignment(
            words=[
                WordAlignment(
                    word=w,
                    start=i * 0.5,
                    end=i * 0.5 + 0.4,
                    tag=WordTag.OK,
                    score=80.0,
                )
                for i, w in enumerate(words)
            ]
        )
