"""
预处理模块测试
"""
import tempfile
from pathlib import Path

import pytest


class TestConvertToWav:
    """测试 convert_to_wav 函数"""
    
    def test_convert_wav_to_wav(self, test_audio):
        """WAV 转 WAV 应该正常工作"""
        from src.pipeline.preprocess import convert_to_wav
        
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "output.wav"
            convert_to_wav(test_audio, output_path)
            
            assert output_path.exists()
            assert output_path.stat().st_size > 0
    
    def test_convert_nonexistent_file(self, tmp_path):
        """转换不存在的文件应该抛出异常"""
        from src.pipeline.preprocess import convert_to_wav
        
        nonexistent = tmp_path / "nonexistent.mp3"
        output = tmp_path / "output.wav"
        
        with pytest.raises(FileNotFoundError):
            convert_to_wav(nonexistent, output)


class TestAnalyzeAudioQuality:
    """测试 analyze_audio_quality 函数"""
    
    def test_analyze_valid_audio(self, test_audio):
        """分析有效音频应该返回正确的指标"""
        from src.pipeline.preprocess import analyze_audio_quality
        
        metrics = analyze_audio_quality(test_audio)
        
        assert metrics.duration_sec > 0
        assert 0 <= metrics.silence_ratio <= 1
        assert metrics.rms_db < 0  # RMS 通常是负值
        assert 0 <= metrics.clipping_ratio <= 1
    
    def test_analyze_nonexistent_file(self, tmp_path):
        """分析不存在的文件应该抛出异常"""
        from src.pipeline.preprocess import analyze_audio_quality
        
        nonexistent = tmp_path / "nonexistent.wav"
        
        with pytest.raises(FileNotFoundError):
            analyze_audio_quality(nonexistent)


class TestPreprocessAudio:
    """测试 preprocess_audio 函数"""
    
    def test_preprocess_complete_flow(self, test_audio, tmp_path):
        """完整预处理流程应该正常工作"""
        from src.pipeline.preprocess import preprocess_audio
        
        wav_path, metrics = preprocess_audio(test_audio, tmp_path)
        
        assert wav_path.exists()
        assert wav_path.suffix == ".wav"
        assert metrics.duration_sec > 0
