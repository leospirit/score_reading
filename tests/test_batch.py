"""
批处理模块测试
"""
import tempfile
from pathlib import Path

import pytest


class TestLoadManifest:
    """测试 manifest 加载"""
    
    def test_load_valid_manifest(self, test_manifest):
        """应该正确加载有效的 manifest"""
        from src.batch import load_manifest
        
        rows = list(load_manifest(test_manifest))
        
        assert len(rows) > 0
        assert "task_id" in rows[0]
        assert "student_id" in rows[0]
        assert "audio_path" in rows[0]
    
    def test_load_nonexistent_manifest(self, tmp_path):
        """加载不存在的 manifest 应该抛出异常"""
        from src.batch import load_manifest
        
        nonexistent = tmp_path / "nonexistent.csv"
        
        with pytest.raises(FileNotFoundError):
            list(load_manifest(nonexistent))


class TestLoadTasks:
    """测试任务配置加载"""
    
    def test_load_valid_tasks(self, test_tasks):
        """应该正确加载有效的任务配置"""
        from src.batch import load_tasks
        
        tasks = load_tasks(test_tasks)
        
        assert len(tasks) > 0
        for task_id, config in tasks.items():
            assert config.task_id == task_id
            assert config.script_text


class TestBuildSubmissions:
    """测试提交构建"""
    
    def test_build_submissions_from_manifest(self, test_manifest, test_tasks):
        """应该从 manifest 构建提交列表"""
        from src.batch import build_submissions, load_tasks
        
        tasks = load_tasks(test_tasks)
        submissions = build_submissions(test_manifest, tasks)
        
        assert len(submissions) > 0
        for sub in submissions:
            assert sub.task_id
            assert sub.student_id
            assert sub.script_text


class TestValidateManifest:
    """测试 manifest 校验"""
    
    def test_validate_valid_manifest(self, test_manifest, test_tasks):
        """有效的 manifest 应该校验通过"""
        from src.batch import validate_manifest
        
        result = validate_manifest(test_manifest, test_tasks)
        
        assert result["valid"] is True
        assert len(result["errors"]) == 0
    
    def test_validate_with_missing_audio(self, tmp_path, test_tasks):
        """缺少音频文件应该报错"""
        from src.batch import validate_manifest
        
        # 创建一个 manifest，引用不存在的音频
        manifest = tmp_path / "bad_manifest.csv"
        manifest.write_text(
            "task_id,student_id,audio_path\n"
            "reading-001,student_a,nonexistent.wav\n"
        )
        
        result = validate_manifest(manifest, test_tasks)
        
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        # 检查是否有 missing 相关的错误
        assert any("不存在" in str(e["message"]) for e in result["errors"])
