"""
分数归一化模块测试
"""
import pytest


class TestNormalizeGopScore:
    """测试 GOP 分数归一化"""
    
    def test_normalize_perfect_gop(self):
        """完美的 GOP 分数应该接近 100"""
        from src.pipeline.normalize import normalize_gop_score
        
        score = normalize_gop_score(0.0)  # GOP=0 表示完美匹配
        assert 90 <= score <= 100
    
    def test_normalize_bad_gop(self):
        """差的 GOP 分数应该较低"""
        from src.pipeline.normalize import normalize_gop_score
        
        score = normalize_gop_score(-10.0)  # 差的 GOP
        assert 0 <= score <= 50
    
    def test_normalize_gop_range(self):
        """分数应该在 0-100 范围内"""
        from src.pipeline.normalize import normalize_gop_score
        
        for gop in range(-20, 5):
            score = normalize_gop_score(float(gop))
            assert 0 <= score <= 100


class TestCalculateFluencyScore:
    """测试流利度计算"""
    
    def test_fluency_low_silence(self):
        """低静音率应该得分高"""
        from src.models import Alignment, AudioMetrics
        from src.pipeline.normalize import calculate_fluency_score
        
        metrics = AudioMetrics(
            duration_sec=10.0,
            silence_ratio=0.1,
            rms_db=-20.0,
            clipping_ratio=0.0,
        )
        alignment = Alignment(words=[], phonemes=[])
        
        score = calculate_fluency_score(metrics, alignment)
        assert score >= 80
    
    def test_fluency_high_silence(self):
        """高静音率应该得分低"""
        from src.models import Alignment, AudioMetrics
        from src.pipeline.normalize import calculate_fluency_score
        
        metrics = AudioMetrics(
            duration_sec=10.0,
            silence_ratio=0.5,
            rms_db=-20.0,
            clipping_ratio=0.0,
        )
        alignment = Alignment(words=[], phonemes=[])
        
        score = calculate_fluency_score(metrics, alignment)
        assert score <= 80  # 高静音率会扣分


class TestCalculateOverallScore:
    """测试综合分数计算"""
    
    def test_overall_weighted_average(self):
        """综合分数应该是加权平均"""
        from src.models import Scores
        from src.pipeline.normalize import calculate_overall_score
        
        scores = Scores(
            pronunciation_100=80,
            fluency_100=90,
            intonation_100=70,
            completeness_100=100,
        )
        
        score = calculate_overall_score(scores)
        
        # 应该在 70-100 之间
        assert 70 <= score <= 100
    
    def test_overall_all_perfect(self):
        """全满分时综合分应该是 100"""
        from src.models import Scores
        from src.pipeline.normalize import calculate_overall_score
        
        scores = Scores(
            pronunciation_100=100,
            fluency_100=100,
            intonation_100=100,
            completeness_100=100,
        )
        
        score = calculate_overall_score(scores)
        
        assert score == 100
