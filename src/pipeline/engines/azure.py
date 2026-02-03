"""
Azure 语音评价引擎 - 使用 Microsoft Azure Pronunciation Assessment API

提供工业级的语音评价精度，支持音标级别的错误诊断。
"""
import json
import logging
import time
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

# 延迟导入，防止在未配置时导致启动失败
_speech_sdk = None

def get_speech_sdk():
    global _speech_sdk
    if _speech_sdk is None:
        try:
            import azure.cognitiveservices.speech as sdk
            _speech_sdk = sdk
        except ImportError:
            logger.error("azure-cognitiveservices-speech 库未安装")
            raise ImportError("请运行 'pip install azure-cognitiveservices-speech' 以使用 Azure 引擎")
    return _speech_sdk

class AzureEngine:
    """
    Azure 语音评分引擎 (云端权威模式)
    """

    def __init__(self) -> None:
        self.api_key = config.get("engines.azure.api_key")
        self.region = config.get("engines.azure.region", "eastus")
        self.language = config.get("engines.azure.language", "en-US")
        
        if not self.api_key:
            logger.warning("Azure API Key 未配置，AzureEngine 将无法工作")

    def run(
        self,
        wav_path: Path,
        script_text: str,
        work_dir: Optional[Path] = None,
    ) -> tuple[Alignment, dict[str, Any]]:
        """
        运行 Azure 评分
        """
        sdk = get_speech_sdk()
        
        if not self.api_key:
            raise ValueError("Azure API Key is required for AzureEngine")

        logger.info(f"Azure 引擎：开始评估 '{wav_path.name}'")
        
        speech_config = sdk.SpeechConfig(subscription=self.api_key, region=self.region)
        audio_config = sdk.audio.AudioConfig(filename=str(wav_path))

        # 配置发音评估
        pronunciation_config = sdk.PronunciationAssessmentConfig(
            reference_text=script_text,
            grading_system=sdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=sdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=True
        )

        speech_recognizer = sdk.SpeechRecognizer(
            speech_config=speech_config, 
            language=self.language, 
            audio_config=audio_config
        )
        
        pronunciation_config.apply_to(speech_recognizer)

        # 执行识别
        result = speech_recognizer.recognize_once()
        
        if result.reason == sdk.ResultReason.RecognizedSpeech:
            return self._parse_result(result, script_text)
        elif result.reason == sdk.ResultReason.NoMatch:
            raise RuntimeError("Azure: 未能识别到有效语音")
        elif result.reason == sdk.ResultReason.Canceled:
            cancellation_details = result.cancellation_details
            raise RuntimeError(f"Azure: 评估被取消: {cancellation_details.reason}. 错误详情: {cancellation_details.error_details}")
        else:
            raise RuntimeError(f"Azure: 未知错误 reason={result.reason}")

    def _parse_result(self, result: Any, script_text: str) -> tuple[Alignment, dict[str, Any]]:
        """
        解析 Azure 返回的专业结果
        """
        sdk = get_speech_sdk()
        pron_result_json = result.properties.get(sdk.PropertyId.SpeechServiceResponse_JsonResult)
        data = json.loads(pron_result_json)
        
        # Azure 的结果层级：RecognizedPhrases -> NBest -> PronunciationAssessment
        nbest = data.get("NBest", [{}])[0]
        pron_assessment = nbest.get("PronunciationAssessment", {})
        
        alignment = Alignment()
        words = nbest.get("Words", [])
        
        # 转换单词
        for w in words:
            w_text = w.get("Word", "")
            w_assessment = w.get("PronunciationAssessment", {})
            w_error = w_assessment.get("ErrorType", "None")
            w_score = w_assessment.get("AccuracyScore", 0.0)
            
            # 映射标签
            if w_error == "Omission":
                tag = WordTag.MISSING
                w_score = 0.0
            elif w_error == "Mispronunciation" or w_score < 75:
                tag = WordTag.WEAK
            else:
                tag = WordTag.OK
                
            word_align = WordAlignment(
                word=w_text,
                start=w.get("Offset", 0) / 10000000.0, # 转换为秒
                end=(w.get("Offset", 0) + w.get("Duration", 0)) / 10000000.0,
                score=w_score,
                tag=tag
            )
            alignment.words.append(word_align)
            
            # 解析音素 (Azure 提供音标级详情)
            phonemes = w.get("Phonemes", [])
            for p in phonemes:
                p_text = p.get("Phoneme", "")
                p_assessment = p.get("PronunciationAssessment", {})
                p_score = p_assessment.get("AccuracyScore", 0.0)
                
                alignment.phonemes.append(PhonemeAlignment(
                    phoneme=p_text,
                    start=word_align.start, # 粗略估计
                    end=word_align.end,
                    score=p_score,
                    tag=PhonemeTag.OK if p_score >= 75 else PhonemeTag.WEAK,
                    in_word=w_text
                ))

        engine_raw = {
            "source": "Azure",
            "overall_score": pron_assessment.get("PronScore", 0),
            "accuracy_score": pron_assessment.get("AccuracyScore", 0),
            "fluency_score": pron_assessment.get("FluencyScore", 0),
            "completeness_score": pron_assessment.get("CompletenessScore", 0),
            "prosody_score": pron_assessment.get("ProsodyScore", 0),
            "json_raw": data
        }
        
        # 更新核心分数 (GOP 映射模拟)
        # Azure 的 AccuracyScore 对应我们的 Pronunciation
        engine_raw["gop_mean"] = (pron_assessment.get("AccuracyScore", 50) - 50) / 10.0 # 粗略映射回负数区间
        
        return alignment, engine_raw

def run_azure_engine(
    wav_path: Path,
    script_text: str,
    work_dir: Path,
) -> tuple[Alignment, dict[str, Any]]:
    """便捷入口"""
    engine = AzureEngine()
    return engine.run(wav_path, script_text, work_dir)
