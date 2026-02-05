"""
口语评分 CLI 框架 - pytest 配置
"""
import pytest


@pytest.fixture(scope="session")
def samples_dir():
    """返回 samples 目录路径"""
    from pathlib import Path
    return Path(__file__).parent.parent / "samples"


@pytest.fixture(scope="session")
def test_audio(samples_dir):
    """返回测试音频文件路径"""
    audio_path = samples_dir / "test_audio.wav"
    if not audio_path.exists():
        pytest.skip("测试音频文件不存在")
    return audio_path


@pytest.fixture(scope="session")
def test_manifest(samples_dir):
    """返回测试 manifest 文件路径"""
    return samples_dir / "test_manifest.csv"


@pytest.fixture(scope="session")
def test_tasks(samples_dir):
    """返回测试 tasks 文件路径"""
    return samples_dir / "test_tasks.yaml"


@pytest.fixture
def temp_output_dir(tmp_path):
    """返回临时输出目录"""
    return tmp_path / "output"
