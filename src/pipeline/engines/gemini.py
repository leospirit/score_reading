"""
Gemini 多模态评分引擎 - 使用 Google Gemini 1.5 Pro/Flash 直接评估音频

利用 Gemini 的原生音频理解能力，实现“真实教练”级的语音评测。
"""
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from src.config import config
from src.models import (
    Alignment,
    PhonemeAlignment,
    PhonemeTag,
    WordAlignment,
    WordTag,
)

logger = logging.getLogger(__name__)

# 延迟导入
_genai = None
_whisper_engine = None

def get_whisper_engine():
    global _whisper_engine
    if _whisper_engine is None:
        from src.pipeline.engines.whisper_engine import WhisperEngine
        _whisper_engine = WhisperEngine()
    return _whisper_engine

def get_genai():
    global _genai
    if _genai is None:
        try:
            import google.generativeai as genai
            _genai = genai
        except ImportError:
            logger.error("google-generativeai 库未安装")
            raise ImportError("请运行 'pip install google-generativeai' 以使用 Gemini 引擎")
    return _genai

class GeminiEngine:
    """
    Gemini 多模态引擎 (原生听感模式)
    """

    def __init__(self) -> None:
        config_key = config.get("engines.gemini.api_key")
        
        # Support multiple keys
        if config_key:
            self.api_keys = [k.strip() for k in config_key.split(",") if k.strip()]
        else:
            self.api_keys = []
            
        import random
        # Randomize start index to prevent multiple workers from hitting the same key first
        if self.api_keys:
            self.current_key_index = random.randint(0, len(self.api_keys) - 1)
        else:
            self.current_key_index = 0
            
        # Default to Gemini 2.0 Flash Express for best performance
        self.model_name = config.get("engines.gemini.model", "gemini-2.0-flash-exp")
        
        if not self.api_keys:
            logger.warning("Gemini API Key 未配置，GeminiEngine 将无法工作")
            
    def _configure_client(self):
        """Configure GenAI with current key"""
        genai = get_genai()
        current_key = self.api_keys[self.current_key_index]
        genai.configure(api_key=current_key)
        
        masked = f"{current_key[:4]}...{current_key[-4:]}" if len(current_key) > 8 else "***"
        logger.info(f"Gemini Engine 使用 Key Index {self.current_key_index} ({masked})")

    def _rotate_key(self):
        """Switch to next key"""
        if len(self.api_keys) <= 1:
            return False
            
        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        self._configure_client()
        logger.warning(f"Rotated to Gemini Key #{self.current_key_index}")
        return True

    def run(
        self,
        wav_path: Path,
        script_text: str,
        work_dir: Optional[Path] = None,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        通过 Gemini 评估音频
        """
        genai = get_genai()
        if not self.api_keys:
            raise ValueError("Gemini API Key is required for GeminiEngine")

        # Initial Config
        self._configure_client()
        
        model = genai.GenerativeModel(self.model_name)

        logger.info(f"Gemini 引擎：正在上传并听取音频 '{wav_path.name}'...")
        
        # 2. 构造提示词
        is_reference_mode = bool(script_text and script_text.strip() and "请自动听写" not in script_text)
        
        # --- HYBRID FUSION: Whisper/GOP for Time, Gemini for Score ---
        # Only enable if in Reference Mode (we need text to align to)
        # and if NOT in "Fast" fallback mode (implied by calling Gemini directly)
        base_alignment = None
        if is_reference_mode:
            try:
                # Determine Alignment Source
                align_source = config.get("engines.gemini.alignment_source", "whisper").lower()
                logger.info(f">>> 启动混合模式 (Hybrid Fusion). Align Source: {align_source}")
                
                if align_source == "gop":
                    try:
                        from src.pipeline.engines.wav2vec2 import Wav2Vec2Engine
                        wav2vec2 = Wav2Vec2Engine()
                        # GOP Alignment (High Precision)
                        base_alignment, _ = wav2vec2.run(wav_path, script_text, work_dir)
                        logger.info(f"GOP Skeleton Ready: {len(base_alignment.words)} words aligned.")
                    except Exception as gop_err:
                        logger.warning(f"GOP Alignment failed: {gop_err}. Falling back to Whisper for Hybrid Fusion.")
                        align_source = "whisper"
                
                if align_source == "whisper":
                    # 1.1 Whisper Alignment (The Skeleton)
                    # 使用 Whisper 提取精准的物理时间戳
                    whisper = get_whisper_engine()
                    whisper_words = whisper._transcribe(wav_path)
                    base_alignment = whisper._align_with_script(whisper_words, script_text)
                    logger.info(f"Whisper Skeleton Ready: {len(base_alignment.words)} words aligned.")
                    
            except Exception as e:
                logger.warning(f"Hybrid Fusion failed: {e}. Fallback to pure Gemini.")

        if is_reference_mode:
            # --- Reference Mode Prompt (Upgraded to Senior Diagnostic) ---
            prompt = f"""
            你是一位拥有顶级听力的英语语音分析专家。你正在分析一段学生朗读音频，并与【标准剧本】进行比对。
            
            【标准剧本 (Script)】：
            "{script_text}"
            
            你的核心任务：
            1. **精细化听写辨析 (Refereed Transcription)**：
               - 请仔细听音频。对于每一个单词，你需要判断学生实际发出的声音。
               - 如果学生发音有偏差，请**准确记录下听起来像什么**（例如：把 "fine" 读成了 "frine"，把 "lessons" 读成了 "lisens"）。
            
            2. **音素与停顿诊断 (phoneme_diagnosis & pause_diagnosis)**：
               - `phoneme_diagnosis`: 必须详细描述发音偏差。例如："原文识别为 frine" 或 "Said /r/ instead of /n/"。
               - `pause_diagnosis`: 重点指出**断句位置是否合理**。例如："在 subject 和 verb 之间断句不自然" 或 "此处应停顿但未停顿"。
               - `detected_transcript`: 必须是**全文转录**，且要刻意保留那些“听错”的单词，以便展示差距。
            
            3. **评分规则 (严格版)**：
               - **[0-40]**: 漏读或完全不可理解。
               - **[41-75]**: 单词能辨别，但有明显的发音偏差（如：Said X instead of Y）。
               - **[76-100]**: 发音地道，轻微口音但不影响理解。
            
            **输出 JSON 格式（严禁包含 Markdown）：**
            {{
                "overall_score": 0.0, 
                "accuracy_score": 0.0, 
                "fluency_score": 0.0, 
                "completeness_score": 0.0, 
                "top_errors": [
                    {{
                        "phoneme": "音素符号 (如 /r/)",
                        "description": "具体偏差，例如 '原文识别为 frine'",
                        "words": ["单词1", "单词2"],
                        "improvement": "物理改进建议"
                    }}
                ],
                "word_details": [
                    {{
                        "word": "Script 中的原单词",
                        "score": 0.0, 
                        "mistake_type": "None" | "Mispronunciation" | "Omission",
                        "phoneme_diagnosis": "具体发音/停顿偏差", 
                        "comment": "给学生的物理改进建议"
                    }}
                ],
                "general_advice": "综合性反馈。必须总结录音中学生表现出的‘发音习惯’（如：多余卷舌、单词结尾不完整等）。",
                "detected_transcript": "全文忠实听写结果",
                "feedback": {{
                    "overall_comment": "作为资深导师，用温暖且严谨的口吻点评。必须包含对‘物理发音习惯’和‘情感节奏’观察。",
                    "specific_suggestions": ["具体的改进动作，如：'把 fine 最后的 n 发得更清晰，舌尖顶住上齿龈'"],
                    "practice_tips": ["练习建议"],
                    "fun_challenge": "趣味模仿任务"
                }}
            }}
            """
        else:
            # --- Free Talk Mode ---
            script_text = "（无原文，请自动听写）"
            prompt = f"""
            你是一位亲切的少儿英语教练。请听这段音频。
            
            任务：
            1. **自动听写**：准确转录孩子说的话。
            2. **发音评估**：评估孩子说出的每个单词的发音质量。
            
            要求：
            - 对于孩子明显想说但说错的词，请尝试还原为正确单词并标记 Mispronunciation。
            - 关注流利度和自信心。
            
            输出 JSON 格式（严禁包含 Markdown）：
            {{
                "overall_score": 0.0, 
                "accuracy_score": 0.0, 
                "fluency_score": 0.0, 
                "completeness_score": 100.0, 
                "word_details": [
                    {{
                        "word": "听写出的单词",
                        "score": 0.0, 
                        "mistake_type": "None" | "Mispronunciation",
                        "comment": "简单建议"
                    }}
                ],
                "general_advice": "中文鼓励和建议",
                "detected_transcript": "全文转录",
                "feedback": {
                    "overall_comment": "【AI老师点评】：请用温柔、专业的口吻，对孩子的整体表现进行深度点评。",
                    "specific_suggestions": ["具体改进建议1", "具体改进建议2"],
                    "practice_tips": ["练习建议1", "练习建议2"],
                    "fun_challenge": "【趣味挑战】：给出一个有趣的模仿任务。"
                }
            }}
            """

        # 3. 获取 AI 反馈
        import time
        from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, InternalServerError

        max_retries = 3
        if len(self.api_keys) > 1:
            max_retries = 5
            
        retry_delay = 1

        for attempt in range(max_retries + 1):
            audio_file = None
            try:
                # Re-upload file each time to be safe? 
                # Actually GenAI file upload is separate from generation, but limit might apply to upload too.
                # Let's keep upload inside loop to be robust against upload failures too.
                audio_file = genai.upload_file(path=str(wav_path), mime_type="audio/wav")
                
                # 使用 temp=0 确保严格遵循格式
                response = model.generate_content(
                    [prompt, audio_file],
                    generation_config={"temperature": 0.0}
                )
                logger.info("Gemini 引擎：已收到 AI 反馈")
                logger.info("Gemini 引擎：已收到 AI 反馈")
                
                # Parse Gemini Result
                gemini_alignment, engine_raw = self._parse_response(response, script_text)
                
                # --- HYBRID FUSION MERGE ---
                if base_alignment:
                    final_alignment = self._merge_fusion(base_alignment, gemini_alignment)
                    return final_alignment, engine_raw
                else:
                    return gemini_alignment, engine_raw
                
                
            except (ResourceExhausted, ServiceUnavailable, InternalServerError) as e:
                is_last_attempt = attempt == max_retries
                
                logger.warning(f"Gemini Error (Attempt {attempt+1}/{max_retries+1}): {e}")
                
                if is_last_attempt:
                    logger.error("Gemini Max retries reached.")
                    raise
                
                # Try rotate
                rotated = self._rotate_key()
                
                if rotated:
                    time.sleep(1) # Fast retry on new key
                else:
                    wait = retry_delay * (2 ** attempt)
                    logger.info(f"Waiting {wait}s...")
                    time.sleep(wait)
                    
            except Exception as e:
                logger.error(f"Gemini Critical Error: {e}")
                raise
            finally:
                if audio_file:
                    try:
                        genai.delete_file(audio_file.name)
                    except:
                        pass

    def _parse_response(self, response, script_text):
        try:
            text = response.text.strip()
            
            # --- DEBUG DUMP ---
            try:
                debug_path = Path("debug_gemini_raw.txt")
                with open(debug_path, "w", encoding="utf-8") as f:
                    f.write(text)
                logger.info(f"DEBUG: Gemini raw response saved to {debug_path.absolute()}")
            except Exception as e:
                logger.warning(f"Failed to save debug log: {e}")
            # ------------------
            
            # 基础清洗
            if "```json" in text:
                text = text.split("```json")[-1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[-1].split("```")[0].strip()
            
            # 记录原始返回以便调试 (在测试环境下)
            logger.debug(f"Gemini Raw Response: {text[:200]}...")
                
            data = json.loads(text)
            
            # 额外校验必要字段
            if "accuracy_score" not in data:
                 raise ValueError("JSON missing accuracy_score")
                 
            return self._convert_to_alignment(data, script_text)

        except Exception as e:
            logger.error(f"Gemini 结果解析失败: {e}\nResponse: {response.text}")
            raise RuntimeError(f"Gemini 评估失败: 无法处理 AI 返回的格式")
        finally:
            # 清理文件（可选）
            # genai.delete_file(audio_file.name)
            pass
    def _convert_to_alignment(self, data: dict, script_text: str) -> tuple[Alignment, dict[str, Any]]:
        """
        将 Gemini 的理解转换为系统兼容的对齐格式
        """
        alignment = Alignment()
        word_details = data.get("word_details", [])
        
        # 因为 Gemini 不提供每词的毫秒级时间戳（或者不够精确），
        # 我们使用平均分配逻辑，确保 UI 能显示出颜色。
        # 真实的对齐建议由本地 Standard 引擎辅助。
        
        current_time = 0.3
        for w in word_details:
            w_text = w.get("word", "")
            w_score = w.get("score", 60.0)
            m_type = w.get("mistake_type", "None")
            p_diagnosis = w.get("phoneme_diagnosis", "") 
            pause_diag = w.get("pause_diagnosis", "")
            
            # Combine diagnoses for the UI components
            full_diag = p_diagnosis
            if pause_diag:
                full_diag = f"{full_diag} | {pause_diag}" if full_diag else pause_diag
            
            # Record it for the word object
            w.update({"full_diagnosis": full_diag}) # Temp storage for constructor
            
            # Rubric Enforcement... (Same as before)
            if m_type == "Omission":
                w_score = 0
            else:
                if w_score < 40:
                    w_score = 45 
            
            duration = 0.2 + len(w_text) * 0.05
            tag = WordTag.OK
            if m_type == "Omission":
                tag = WordTag.MISSING
                w_score = 0
            elif m_type != "None" or w_score < 60:
                tag = WordTag.WEAK
            
            word_align = WordAlignment(
                word=w_text,
                start=current_time,
                end=current_time + duration,
                score=w_score,
                tag=tag,
                # Store diagnosis in a way that downstream can find it
                # We'll put it in a custom attribute for now
            )
            word_align.diagnosis = full_diag
            alignment.words.append(word_align)
            current_time += duration + 0.1

        engine_raw = {
            "source": f"Gemini ({self.model_name})",
            "overall_score": data.get("overall_score", 0),
            "accuracy_score": data.get("accuracy_score", 0),
            "fluency_score": data.get("fluency_score", 0),
            "completeness_score": data.get("completeness_score", 0),
            "gemini_feedback": data.get("general_advice", ""),
            "detected_transcript": data.get("detected_transcript", ""),
            "ai_referee": {
                "status": "completed",
                "conflicts": len([w for w in word_details if w.get("mistake_type") != "None"]),
                "conflict_details": [
                    {
                        "word": w.get("word"),
                        "expected": w.get("word"),
                        "got": (diag := w.get("phoneme_diagnosis", "") + (" | " + w.get("pause_diagnosis", "") if w.get("pause_diagnosis") else "")) or "发音有误",
                        "comment": w.get("comment", "")
                    }
                    for w in word_details if w.get("mistake_type") != "None"
                ]
            },
            # INTEGRATED FEEDBACK (Pass-through to runner)
            "integrated_feedback": {
                **data.get("feedback", {}),
                "top_errors": data.get("top_errors", [])
            }
        }
        
        # 填充原始评分数据，由 normalize.py 直接使用
        engine_raw["pronunciation_score"] = data.get("accuracy_score", 75)
        engine_raw["fluency_score"] = data.get("fluency_score", 75)
        # 语调分通常包含在整体表现中，这里使用 accuracy 或 overall 的变体
        engine_raw["intonation_score"] = data.get("overall_score", 75)
        engine_raw["completeness_score"] = data.get("completeness_score", 100)
        
        # 为了兼容性，保留一个适中的 gop_mean
        engine_raw["gop_mean"] = -3.5
        
        logger.info(f"Gemini 原始评分已注入: Pronunciation={engine_raw['pronunciation_score']}, Fluency={engine_raw['fluency_score']}")
        
        # 4. Adaptive Calibration: The "All Red" Safety Net
        # If the entire session is scored too low (e.g. avg < 45), it's likely a model strictness issue.
        # We shift the distribution up to ensure at least some "Orange" and "Green".
        self._adaptive_calibration(alignment)
        
        return alignment, engine_raw

    def _adaptive_calibration(self, alignment: Alignment):
        """
        Adaptive calibration to prevent "All Red" / "All Orange" false positives.
        If the session average is unreasonably low, we boost the whole curve.
        """
        valid_words = [w for w in alignment.words if w.tag != WordTag.MISSING and w.score > 0]
        if not valid_words:
            return

        scores = [w.score for w in valid_words]
        avg_score = sum(scores) / len(scores)
        
        # Threshold: If average is below 60 (Mostly Orange/Red), target a "Safe Pass" (65-70)
        if avg_score < 60:
            target_mean = 68.0
            boost = target_mean - avg_score
            logger.warning(f"Detected low-scoring session (Avg {avg_score:.1f}). Applying adaptive boost +{boost:.1f}")
            
            for w in valid_words:
                # Apply boost, max 100
                w.score = min(100, w.score + boost)
                
                # Re-evaluate tags based on new score and NEW CONFIG THRESHOLDS (60/30)
                if w.score >= 60: 
                    w.tag = WordTag.OK
                elif w.score >= 30:
                    w.tag = WordTag.WEAK
                # Else remains POOR (if it was very low)
                # Else remains POOR (if it was very low)

    def _merge_fusion(self, base_alignment: Alignment, gemini_alignment: Alignment) -> Alignment:
        """
        Merge Whisper's Timestamps (Base) with Gemini's Scores (Judgement).
        """
        from difflib import SequenceMatcher
        
        # Extract sequences
        base_words = [w.word.lower() for w in base_alignment.words]
        gemini_words = [w.word.lower() for w in gemini_alignment.words]
        
        matcher = SequenceMatcher(None, base_words, gemini_words)
        
        fused_words = []
        
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                # Match: Use Base Time + Gemini Score
                for k in range(i2 - i1):
                    base_w = base_alignment.words[i1 + k]
                    gemini_w = gemini_alignment.words[j1 + k]
                    
                    # Fuse!
                    base_w.score = gemini_w.score
                    base_w.tag = gemini_w.tag
                    # Keep base_w.start/end (Real Time)
                    fused_words.append(base_w)
            elif tag == 'replace':
                # Conflict: Use Base Time + Gemini Score (Best Effort)
                # If counts match, map 1-to-1
                base_len = i2 - i1
                gem_len = j2 - j1
                
                if base_len == gem_len:
                    for k in range(base_len):
                        base_w = base_alignment.words[i1 + k]
                        gemini_w = gemini_alignment.words[j1 + k]
                        base_w.score = gemini_w.score
                        base_w.tag = gemini_w.tag
                        fused_words.append(base_w)
                else:
                    # Length mismatch: Trust Whisper's existence (Time), but mark as WEAK if Gemini missed it?
                    # Or trust Gemini's Score?
                    # Strategy: Prioritize Base Words (for UI stability)
                    for k in range(base_len):
                        w = base_alignment.words[i1 + k]
                        # Default to whatever Whisper thought, or conservative score
                        # Try to find best match in Gemini segment? No, too complex.
                        # Just keep Whisper's structure.
                        fused_words.append(w)
            elif tag == 'delete':
                # Word in Whisper but not in Gemini (Gemini merged/skipped)
                for k in range(i2 - i1):
                    fused_words.append(base_alignment.words[i1 + k])
            elif tag == 'insert':
                # Word in Gemini but not in Whisper (Hallucination or excessive splitting)
                # Ignore, as it has no timestamp.
                pass
                
        # Reconstruct Alignment
        # Also fuse phonemes? For now just Words.
        # Whisper doesn't give phoneme scores, Gemini doesn't give phonemes.
        # We lose phoneme details in Fusion unless we run G2P.
        # But User cares about Word Colors (Red/Orange).
        
        return Alignment(words=fused_words, phonemes=base_alignment.phonemes)

def run_gemini_engine(
    wav_path: Path,
    script_text: str,
    work_dir: Path,
) -> tuple[Alignment, dict[str, Any]]:
    """便捷入口"""
    engine = GeminiEngine()
    return engine.run(wav_path, script_text, work_dir)
