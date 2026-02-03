"""
Wav2Vec2-GOP 评分引擎 - 使用 Transformers 实现现代强制对齐与评分

该引擎代替 Kaldi，利用 Wav2Vec2 模型提取音素后验概率，并结合 CTC 对齐算法实现精准切片。
"""
import logging
import os
import torch
import torchaudio
import numpy as np
import librosa
from pathlib import Path
from typing import Any, Optional, Dict, List
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

try:
    from num2words import num2words
except ImportError:
    num2words = None

# DeepFilterNet for noise reduction
try:
    from df.enhance import enhance, init_df
    HAS_DF = True
except ImportError:
    HAS_DF = False

from src.config import config
from src.models import (
    Alignment,
    PhonemeAlignment,
    PhonemeTag,
    WordAlignment,
    WordTag,
)

logger = logging.getLogger(__name__)

class Wav2Vec2Engine:
    """
    Wav2Vec2 GOP 评分引擎
    """
    
    def __init__(self) -> None:
        model_id = config.get("engines.wav2vec2.model", "facebook/wav2vec2-base-960h")
        self.device = config.get("engines.wav2vec2.device", "cpu")
        if self.device == "auto":
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
            
        logger.info(f"正在加载 Wav2Vec2 模型: {model_id} (Device: {self.device})")
        
        try:
            self.processor = Wav2Vec2Processor.from_pretrained(model_id)
            self.model = Wav2Vec2ForCTC.from_pretrained(model_id).to(self.device)
            self.model.eval()
        except Exception as e:
            logger.error(f"模型加载失败: {e}")
            raise RuntimeError(f"Wav2Vec2 加载失败，请检查网络或模型名称: {model_id}")
            
        # 初始化降噪模型
        if HAS_DF:
            logger.info("Initializing DeepFilterNet for noise reduction...")
            self.df_state = init_df()
        else:
            self.df_state = None
            logger.warning("DeepFilterNet not installed, skipping advanced noise reduction.")

    def run(
        self,
        wav_path: Path,
        script_text: str,
        work_dir: Optional[Path] = None,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        运行对齐与评分逻辑
        """
        waveform, sample_rate = torchaudio.load(str(wav_path))
        
        # 强制转换为单声道 (Avoid stereo processing errors)
        if waveform.shape[0] > 1:
            logger.info(f"Converting stereo audio ({waveform.shape[0]} channels) to mono.")
            waveform = torch.mean(waveform, dim=0, keepdim=True)
            
        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
        
        waveform = waveform.squeeze().to(self.device)
        
        # 1.5 降噪增强 (DeepFilterNet)
        if HAS_DF and self.df_state:
            try:
                # DeepFilterNet 期望的数据是 2-dim (C, T) 且采样率通常是 48k
                # 但它也支持不同采样率，内部会自动重采样
                # 我们先将 16k 信号转为 48k 增强，再转回 16k
                logger.info("Applying DeepFilterNet enhancement...")
                
                # waveform 目前是 (T,) 16k
                # 转为 (1, T)
                wf_in = waveform.unsqueeze(0).cpu()
                
                # 使用 librosa 重采样到 48k (DF 最佳采样率)
                wf_48k = librosa.resample(wf_in.numpy()[0], orig_sr=16000, target_sr=48000)
                wf_48k_tensor = torch.from_numpy(wf_48k).unsqueeze(0)
                
                # 增强
                enhanced_48k = enhance(self.model_df if hasattr(self, 'model_df') else self.df_state, self.df_state, wf_48k_tensor)
                
                # 转回 16k
                enhanced_16k = librosa.resample(enhanced_48k.numpy()[0], orig_sr=48000, target_sr=16000)
                waveform = torch.from_numpy(enhanced_16k).to(self.device)
                
                logger.info("Noise reduction complete.")
            except Exception as e:
                logger.warning(f"Noise reduction failed, proceeding with original audio: {e}")
        
        # 2. 获取 Logits
        with torch.no_grad():
            inputs = self.processor(waveform, sampling_rate=16000, return_tensors="pt", padding=True)
            input_values = inputs.input_values.to(self.device)
            logits = self.model(input_values).logits
            
        # 转换概率
        log_probs = torch.nn.functional.log_softmax(logits, dim=-1).squeeze(0).cpu().numpy()
        
        # 3. CTC 强制对齐 (简化的对齐实现)
        # 注意：这里需要将文本转换为 ID。Wav2Vec2 默认基于 Character。
        # 对于发音评估，理想情况是基于 Phoneme 模型，这里先实现 Character 对齐作为基础。
        target_text = script_text.upper()
        alignment = self._forced_align(log_probs, target_text)
        
        # 汇总为单词级评分
        alignment_obj, engine_raw = self._process_alignment_results(alignment, log_probs, script_text)
        
        # 计算高级维度
        duration = alignment_obj.words[-1].end if alignment_obj.words else 0
        fluency_score, fluency_stats = self._calculate_fluency(alignment_obj.words, duration)
        intonation_score, intonation_stats = self._calculate_intonation(wav_path)
        
        engine_raw["pronunciation_score"] = engine_raw["overall_score"]
        engine_raw["fluency_score"] = fluency_score
        engine_raw["intonation_score"] = intonation_score
        engine_raw["completeness_score"] = 100
        
        engine_raw.update(fluency_stats)
        engine_raw.update(intonation_stats)
        
        return alignment_obj, engine_raw

    def _forced_align(self, log_probs: np.ndarray, target_text: str) -> List[Dict]:
        """
        极简 CTC 对齐逻辑 (Viterbi 路径搜索)
        """
        # 1. 预处理文本：转大写，处理数字，移除标点
        # Wav2Vec2 词表通常没有标点 (除了 ' 和 -) 和 数字
        import re
        
        def _normalize_text(text: str) -> str:
            # Convert numbers to words (e.g., "25" -> "twenty five")
            if num2words:
                tokens = []
                for word in text.split():
                    if word.isdigit():
                        try:
                            tokens.append(num2words(int(word), lang='en'))
                        except:
                            tokens.append(word)
                    else:
                        tokens.append(word)
                text = " ".join(tokens)
            
            # Remove punctuation except apostrophes
            text = re.sub(r"[^A-Za-z' ]", " ", text.upper())
            # Collapse spaces
            return re.sub(r"\s+", " ", text).strip()

        normalized_script = _normalize_text(target_text)
        raw_words = re.findall(r"[\w']+", normalized_script)
        processed_text = "|".join(raw_words)
        
        tokens = self.processor.tokenizer.tokenize(processed_text)
        token_ids = self.processor.tokenizer.convert_tokens_to_ids(tokens)
        
        T = log_probs.shape[0]
        N = len(token_ids)
        
        # 对齐矩阵 (DP)
        dp = np.full((T, N), -np.inf)
        backtrack = np.zeros((T, N), dtype=int)
        
        # 初始化
        dp[0][0] = log_probs[0][token_ids[0]]
        
        for t in range(1, T):
            for n in range(N):
                # 状态转移：保留当前状态 or 从上一个状态转移 or 跳过当前状态 (Skip-Token)
                p_stay = dp[t-1][n]
                p_move = dp[t-1][n-1] if n > 0 else -np.inf
                # Skip-Token: 允许跳过一个 Token (例如 | 或极短词)
                p_skip = dp[t-1][n-2] if n > 1 else -np.inf
                
                # 权重调整：移动 > 停顿 >> 跳过
                p_move += 0.2    # 增强移动意愿，防止在一个 Token 停留过久
                p_skip -= 15.0   # 极大增加跳过惩罚 (从 5.0 -> 15.0)，强制算法优先留在原剧本路径上
                
                if p_move >= p_stay and p_move >= p_skip:
                    dp[t][n] = p_move + log_probs[t][token_ids[n]]
                    backtrack[t][n] = n - 1
                elif p_stay >= p_skip:
                    dp[t][n] = p_stay + log_probs[t][token_ids[n]]
                    backtrack[t][n] = n
                else:
                    dp[t][n] = p_skip + log_probs[t][token_ids[n]]
                    backtrack[t][n] = n - 2
                    
        # 回溯路径
        path = []
        # CRITICAL: 找到最后一帧得分最高且最靠后的 Token (处理未完全对齐的情况)
        best_n = np.argmax(dp[T-1, :])
        curr_n = int(best_n)
        
        for t in range(T - 1, -1, -1):
            path.append((t, curr_n))
            curr_n = int(backtrack[t][curr_n])
            if curr_n < 0: curr_n = 0
        path.reverse()
        
        # 转换为时间轴段
        segments = []
        for n in range(N):
            frames = [t for t, token_idx in path if token_idx == n]
            
            if frames:
                # Wav2Vec2 帧长通常约为 20ms
                start_s = min(frames) * 0.02
                end_s = (max(frames) + 1) * 0.02
                
                # 计算 GOP (校准版)
                frame_probs = [log_probs[t][token_ids[n]] for t in frames]
                frame_max_probs = [np.max(log_probs[t]) for t in frames]
                gop = np.mean(np.array(frame_probs) - np.array(frame_max_probs))
            else:
                # CRITICAL FIX: 如果该 Token 没有匹配到任何帧（常见于发音极差或短促词）
                # 赋予一个极小的持续时间，位置参考上一个有效帧，防止索引错位导致后面的词全部标记为“漏读”
                prev_end = segments[-1]["end"] if segments else 0.0
                start_s = prev_end
                end_s = prev_end + 0.01 # 10ms 占位
                gop = -10.0 # 极低分表示未检测到有效发音
            
            segments.append({
                "token": tokens[n],
                "start": start_s,
                "end": end_s,
                "gop": gop
            })
            
        # 如果对齐失败或严重缺失（比如只识别了不到 85% 的词），则启动线性兜底
        # 提高阈值以确保用户体验，宁愿给个大概分也不要漏读
        if not segments or (len(segments) < len(tokens) * 0.85):
             logger.warning(f"CTC Alignment poor (Found {len(segments)} segments vs {len(tokens)} tokens). Triggering Linear Fallback.")
             segments = self._linear_alignment_fallback(tokens, log_probs.shape[0] * 0.02)

        return segments

    def _linear_alignment_fallback(self, tokens: List[str], duration: float) -> List[Dict]:
        """
        线性兜底对齐：将所有 Token (包括分隔符 |) 均匀分布在音频时间轴上。
        必须保留 |，否则下游无法组词。
        """
        segments = []
        if not tokens:
             return []
        
        # 假设首尾各留 0.2s 静音
        margin = min(0.2, duration * 0.05)
        start_t = margin
        end_t = max(margin + 0.1, duration - margin)
        
        # 计算每个 Token 的 avg duration
        # 注意：tokens 包含 |
        n_tokens = len(tokens)
        step = (end_t - start_t) / n_tokens
        
        for i, token in enumerate(tokens):
            t_start = start_t + i * step
            t_end = t_start + step
            
            # 如果是分隔符 |，通常时间很短或附着在前一个词？
            # 简单起见，线性分配即可。下游逻辑 handle checking |
            
            # GOP 分数：给一个比较好的分数，例如 80 分 -> GOP approx -1.5 ~ -2.0 ?
            # logic: 100 + gop * 9.5 >= 80 => gop * 9.5 >= -20 => gop >= -2.1
            gop_score = -1.5 
            
            segments.append({
                "token": token,
                "start": t_start,
                "end": t_end,
                "gop": gop_score
            })
            
        return segments


    def _calculate_fluency(self, words: List[WordAlignment], duration_sec: float) -> tuple[float, dict]:
        """
        计算流利度 (WPM + Pauses)
        """
        if not words or duration_sec <= 0:
            return 0.0, {}
            
        # 1. WPM Calculation
        num_words = len(words)
        wpm = (num_words / duration_sec) * 60
        
        # 2. Pause Detection
        pauses = []
        total_pause_duration = 0.0
        
        for i in range(len(words) - 1):
            gap = words[i+1].start - words[i].end
            if gap > 0.3: # 300ms threshold for pause
                pauses.append(gap)
                total_pause_duration += gap
                
        # 3. Scoring
        # Target WPM: 80-130 for reading. (Lowered from 110 baseline)
        # Score = 100 - penalty
        wpm_score = min(100, (wpm / 90) * 100) if wpm < 90 else 100
        if wpm > 170: # Too fast penalty
             wpm_score -= (wpm - 170) * 0.3
             
        # Scale penalties by duration to be fairer for long audio
        # Reduced penalty coefficients (2 -> 1, 5 -> 2)
        pause_penalty = (len(pauses) * 1.0) + (total_pause_duration * 2.0)
        
        fluency_score = float(np.clip(wpm_score - pause_penalty, 0, 100))
        
        return fluency_score, {
            "wpm": wpm,
            "pause_count": len(pauses),
            "total_pause_duration": total_pause_duration
        }

    def _calculate_intonation(self, wav_path: Path) -> tuple[float, dict]:
        """
        计算语调分数 (基于 F0 和 能量标准差)
        """
        try:
            y, sr = librosa.load(str(wav_path), sr=16000)
            
            # 1. Energy Variation (RMSE)
            rmse = librosa.feature.rms(y=y)[0]
            energy_std = np.std(rmse)
            
            # 2. Pitch Variation (F0) - using pyin (can be slow, use checks)
            # optimizations: limit duration or frame length if needed
            if len(y) / sr > 150: # Increased from 30 to 150s (2.5 mins) per user request
                f0_std = 0
                f0 = np.array([])
            else:
                 # Reduce n_fft for long audio to save memory/time
                 f0, _, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), frame_length=1024)
                 f0 = f0[~np.isnan(f0)]
                 f0_std = np.std(f0) if len(f0) > 0 else 0
                 
            # Scoring logic
            # Energy std typically 0.01 - 0.05 for good speech
            energy_score = min(100, (energy_std / 0.02) * 80)
            
            # F0 std typically 20-50Hz for expressive speech
            pitch_score = min(100, (f0_std / 30) * 90) if f0_std > 0 else 0
            
            # Combined score (Fallback to energy if pitch failed)
            final_score = (original_score := (0.4 * energy_score + 0.6 * pitch_score) if pitch_score > 0 else energy_score)
             
            # Construct Pitch Contour (Downsample for JSON/UI size)
            pitch_contour = []
            if len(f0) > 0:
                times = librosa.times_like(f0, sr=sr, hop_length=512)
                # Take every 10th point to reduce size
                for i in range(0, len(f0), 10):
                    if i < len(times):
                        pitch_contour.append({"t": float(times[i]), "f": float(f0[i])})

            return float(np.clip(final_score, 0, 100)), {
                "energy_std": float(energy_std),
                "f0_std": float(f0_std),
                "pitch_contour": pitch_contour
            }
            
        except Exception as e:
            logger.warning(f"Intonation calc failed: {e}")
            return 70.0, {"pitch_contour": []} # Fallback

    def _process_alignment_results(self, segments: List[Dict], log_probs: np.ndarray, script_text: str) -> tuple[Alignment, dict[str, Any]]:
        """
        转换对齐段到 Alignment 模型
        """
        result = Alignment()
        
        # 按 | 组合单词
        words_data = []
        current_word_tokens = []
        
        for seg in segments:
            if seg["token"] == "|":
                if current_word_tokens:
                    words_data.append(current_word_tokens)
                    current_word_tokens = []
            else:
                current_word_tokens.append(seg)
        if current_word_tokens:
            words_data.append(current_word_tokens)
            
        import re
        raw_words = re.findall(r"[\w']+", script_text.upper())
        
        weak_words_list = []
        
        # 确保对齐：如果 words_data 少于 raw_words，补全 Missing 字样
        # 这防止了“最后一句显示漏读”
        while len(words_data) < len(raw_words):
             words_data.append([]) # 插入空列表作为占位
             
        for i, word_segs in enumerate(words_data):
            if i >= len(raw_words): break
            
            word_text = raw_words[i]
            
            if not word_segs:
                 # 兜底：真的完全没有对齐到任何 Token
                 score = 0.0
                 tag = WordTag.MISSING
            else:
                avg_gop = np.mean([s["gop"] for s in word_segs])
                
            # Calibrated Score (Gentle Mapping v3 - Ultra Relaxed)
            # 目标：让普通中国学生的流利朗读也能达到 80+，重口音也有 60+
            # GOP -12 (极差) -> 100 - 12*5 = 40 (Red)
            # GOP -8 (及格) -> 100 - 40 = 60 (Orange)
            # GOP -6 (尚可) -> 100 - 30 = 70 (Orange/Green)
            # GOP -3 (良好) -> 100 - 15 = 85 (Green)
            score = float(np.clip(100 + avg_gop * 5.0, 0, 100))
            if score < 40 and avg_gop > -20: score = 40 # 保持生存底线
            
            tag = WordTag.OK if score >= 75 else (WordTag.WEAK if score >= 45 else WordTag.POOR)
            
            if tag != WordTag.OK:
                weak_words_list.append(word_text)
            
            # --- Phoneme / Detail Processing ---
            phonemes_list = []
            for seg in word_segs:
                # 内部判定分：更严厉一些，确保能在 mistake_highlights 中体现
                # GOP -3 (良好) -> 100 - 24 = 76 (OK)
                # GOP -6 (尚可) -> 100 - 48 = 52 (WEAK)
                p_score = float(np.clip(100 + seg["gop"] * 8.0, 0, 100))
                p_tag = PhonemeTag.OK if p_score >= 80 else (PhonemeTag.WEAK if p_score >= 60 else PhonemeTag.POOR)
                phonemes_list.append(PhonemeAlignment(
                    phoneme=seg["token"],
                    start=seg["start"],
                    end=seg["end"],
                    score=p_score,
                    tag=p_tag
                ))
            
            w_align = WordAlignment(
                word=word_text,
                start=word_segs[0]["start"],
                end=word_segs[-1]["end"],
                score=score,
                tag=tag,
                phonemes=phonemes_list
            )
            result.words.append(w_align)

        # 全局评分
        overall_score = float(np.mean([w.score for w in result.words])) if result.words else 0
        
        # 生成集成反馈 (Rule-based specific feedback)
        integrated_feedback = self._generate_integrated_feedback(weak_words_list, overall_score)
        
        engine_raw = {
            "source": "Wav2Vec2-GOP",
            "overall_score": overall_score,
            "integrated_feedback": integrated_feedback
        }
        
        return result, engine_raw

    def _generate_integrated_feedback(self, weak_words: list[str], overall_score: float) -> dict[str, Any]:
        """
        基于规则生成具体的发音建议，作为 AI 老师的替代/增强。
        """
        tips = []
        
        # 1. 弱读词汇建议
        if weak_words:
            unique_weak = list(sorted(set(weak_words), key=weak_words.index))[:3]
            tips.append(f"重点练习以下单词的发音：{', '.join(unique_weak)}。尝试把每个音节发饱满。")
        else:
            tips.append("你的单词发音都很清晰，非常棒！")
            
        # 2. 只有整体很高分才夸自然度
        if overall_score > 85:
            tips.append("整体语流非常自然，继续保持这种自信的语调！")
        elif overall_score < 60:
             tips.append("尝试放慢语速，先确保每个单词发音准确，再追求连贯性。")
             
        # 3. 这里的 dict 结构要匹配 runner.py 期望的 'integrated' 结构
        return {
            "overall_comment": "整体表现不错，" + ("但在部分单词的发音细节上可以更精准。" if weak_words else "发音清晰流畅！"),
            "specific_suggestions": tips,
            "practice_tips": ["每天坚持跟读 10 分钟", "遇到难读的长难句可以拆分成小节练习"],
            "fun_challenge": "🌟 挑战：尝试用这种语调朗读一段你最喜欢的电影台词！"
        }
