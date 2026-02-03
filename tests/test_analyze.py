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
