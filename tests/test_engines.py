"""
评分引擎测试
"""
import tempfile
from pathlib import Path

import pytest


class TestStandardEngine:
    """测试 Standard 引擎"""
    
    def test_standard_engine_returns_alignment(self, test_audio):
        """Standard 引擎应该返回对齐信息"""
        from src.pipeline.engines.standard import run_standard_engine
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            
            alignment, engine_raw = run_standard_engine(
                wav_path=test_audio,
                script_text="Hello world this is a test",
                work_dir=work_dir,
            )
            
            assert alignment is not None
            assert len(alignment.words) > 0
            assert "gop_mean" in engine_raw or "mock" in engine_raw
    
    def test_standard_engine_word_scores(self, test_audio):
        """Standard 引擎返回的词应该有分数"""
        from src.pipeline.engines.standard import run_standard_engine
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            
            alignment, _ = run_standard_engine(
                wav_path=test_audio,
                script_text="Hello world",
                work_dir=work_dir,
            )
            
            for word in alignment.words:
                assert word.word
                assert isinstance(word.score, (int, float))


class TestFastEngine:
    """测试 Fast 引擎"""
    
    def test_fast_engine_returns_alignment(self, test_audio):
        """Fast 引擎应该返回对齐信息"""
        from src.pipeline.engines.fast import run_fast_engine
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            work_dir = Path(tmp_dir)
            
            alignment, engine_raw = run_fast_engine(
                wav_path=test_audio,
                script_text="Hello world this is a test",
                work_dir=work_dir,
            )
            
            assert alignment is not None
            assert len(alignment.words) > 0


class TestRouter:
    """测试路由模块"""
    
    def test_select_engine_auto_good_audio(self):
        """高质量音频应该选择 standard 引擎"""
        from src.models import AudioMetrics, EngineMode
        from src.pipeline.router import select_engine
        
        # 模拟高质量音频
        metrics = AudioMetrics(
            duration_sec=10.0,
            silence_ratio=0.1,
            rms_db=-20.0,
            clipping_ratio=0.0,
        )
        
        result = select_engine(EngineMode.AUTO, metrics)
        assert result == EngineMode.STANDARD
    
    def test_select_engine_auto_poor_audio(self):
        """低质量音频应该选择 fast 引擎"""
        from src.models import AudioMetrics, EngineMode
        from src.pipeline.router import select_engine
        
        # 模拟低质量音频
        metrics = AudioMetrics(
            duration_sec=1.0,  # 太短
            silence_ratio=0.5,  # 太多静音
            rms_db=-35.0,  # 太弱
            clipping_ratio=0.0,
        )
        
        result = select_engine(EngineMode.AUTO, metrics)
        assert result == EngineMode.FAST
    
    def test_select_engine_explicit(self):
        """明确指定引擎时应该直接返回"""
        from src.models import AudioMetrics, EngineMode
        from src.pipeline.router import select_engine
        
        metrics = AudioMetrics(
            duration_sec=10.0,
            silence_ratio=0.1,
            rms_db=-20.0,
            clipping_ratio=0.0,
        )
        
        result = select_engine(EngineMode.FAST, metrics)
        assert result == EngineMode.FAST
        
        result = select_engine(EngineMode.STANDARD, metrics)
        assert result == EngineMode.STANDARD
