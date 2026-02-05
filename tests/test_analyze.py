"""
分析模块测试
"""
import pytest


class TestExtractWeakWords:
    """测试弱词提取"""
    
    def test_extract_weak_words_from_alignment(self):
        """应该从对齐结果中提取低分词"""
        from src.models import Alignment, WordAlignment, WordTag
        from src.pipeline.analyze import extract_weak_words
        
        alignment = Alignment(
            words=[
                WordAlignment(word="hello", start=0, end=0.5, tag=WordTag.OK, score=90),
                WordAlignment(word="world", start=0.5, end=1.0, tag=WordTag.WEAK, score=50),
                WordAlignment(word="test", start=1.0, end=1.5, tag=WordTag.POOR, score=30),
            ],
            phonemes=[],
        )
        
        weak_words = extract_weak_words(alignment)
        
        assert "test" in weak_words  # 最低分的词
        assert "world" in weak_words
        assert "hello" not in weak_words  # 高分词不应该出现


class TestExtractMissingWords:
    """测试缺失词提取"""
    
    def test_extract_missing_from_alignment(self):
        """应该提取标记为 missing 的词"""
        from src.models import Alignment, WordAlignment, WordTag
        from src.pipeline.analyze import extract_missing_words
        
        alignment = Alignment(
            words=[
                WordAlignment(word="hello", start=0, end=0.5, tag=WordTag.OK, score=90),
                WordAlignment(word="world", start=0, end=0, tag=WordTag.MISSING, score=0),
            ],
            phonemes=[],
        )
        
        missing = extract_missing_words(alignment, "hello world test")
        
        assert "world" in missing or "test" in missing


class TestAssignTags:
    """测试标签分配"""
    
    def test_assign_tags_based_on_score(self):
        """应该根据分数分配正确的标签"""
        from src.models import Alignment, PhonemeAlignment, WordAlignment, WordTag
        from src.pipeline.analyze import assign_tags
        
        alignment = Alignment(
            words=[
                WordAlignment(word="high", start=0, end=0.5, tag=WordTag.OK, score=90),
                WordAlignment(word="mid", start=0.5, end=1.0, tag=WordTag.OK, score=55),
                WordAlignment(word="low", start=1.0, end=1.5, tag=WordTag.OK, score=25),
            ],
            phonemes=[],
        )
        
        assign_tags(alignment)
        
        assert alignment.words[0].tag == WordTag.OK
        assert alignment.words[1].tag == WordTag.WEAK
        assert alignment.words[2].tag == WordTag.POOR


class TestDetectLinking:
    """测试连读检测"""
    
    def test_detect_linking_between_words(self):
        """应该检测到相邻词之间的连读"""
        from src.models import Alignment, WordAlignment
        from src.pipeline.analyze import detect_linking
        
        # 模拟 "pick up"
        # pick: 0.1 - 0.4
        # up:   0.38 - 0.6  (有重叠，典型的连读特征)
        alignment = Alignment(
            words=[
                WordAlignment(word="pick", start=0.1, end=0.4, score=90),
                WordAlignment(word="up", start=0.38, end=0.6, score=90),
                WordAlignment(word="now", start=0.65, end=0.9, score=90), # 间隙 0.05，非连读
            ],
            phonemes=[],
        )
        
        detect_linking(alignment)
        
        # pick 和 up 应该被标记为 has_linking (或类似字段)
        # Note: 我们需要先在 WordAlignment 模型中添加这个字段，或者通过 tag 实现
        # 根据 implementation_plan，我们可能需要扩展模型或者使用 metadata
        assert alignment.words[0].is_linked is True
        assert alignment.words[1].is_linked is False # 它是被连读的那一个，通常标记在前一个词后面

class TestCalculatePaceTrend:
    """测试语速趋势计算"""
    
    def test_calculate_pace_trend_excludes_missing_words(self):
        """应该排除标记为 missing 的词，避免 WPM 虚高"""
        from src.models import Alignment, WordAlignment, WordTag
        from src.pipeline.analyze import calculate_pace_trend
        
        # 1. 模拟含有很多 Missing 词的场景
        # 正常词：2个 (hello, world)，历时 1s
        # Missing 词：10个，历时 1s (0.1s each)
        # 总词数：12个
        # 如果计入 Missing 词，WPM = (12 / 2) * 60 = 360
        # 如果不计入 Missing 词，WPM = (2 / 2) * 60 = 60
        
        words = []
        # 0 - 0.5s: hello (OK)
        words.append(WordAlignment(word="hello", start=0.0, end=0.5, tag=WordTag.OK, score=90))
        # 0.5 - 1.5s: 10 missing words
        for i in range(10):
            words.append(WordAlignment(word=f"miss_{i}", start=0.5 + i*0.1, end=0.6 + i*0.1, tag=WordTag.MISSING, score=0))
        # 1.5 - 2.0s: world (OK)
        words.append(WordAlignment(word="world", start=1.5, end=2.0, tag=WordTag.OK, score=90))
        
        alignment = Alignment(words=words)
        
        # 使用 window_size=2.0
        points = calculate_pace_trend(alignment, window_size=2.0)
        
        # 在 t=1.0 附近（中心点），应该只统计到 "hello" 和 "world"
        # 目前的逻辑会统计到所有词
        for p in points:
            if 0.5 < p.x < 1.5:
                # 如果包含 Missing 词，这里 WPM 会很高
                assert p.y < 150, f"WPM at {p.x} is too high: {p.y}. Should exclude missing words."
