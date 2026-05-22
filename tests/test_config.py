import pytest
from modules.config import settings, AppConfig

def test_settings_load():
    """설정 파일이 정상적으로 로드되는지 테스트"""
    assert settings is not None
    assert isinstance(settings, AppConfig)
    assert settings.lppl.bubble_threshold == 70.0
    assert settings.data_loader.data_dir == "data"

def test_config_structure():
    """설정 구조가 예상대로인지 테스트"""
    assert hasattr(settings, 'lppl')
    assert hasattr(settings, 'attractiveness')
    assert hasattr(settings, 'portfolio')
    assert hasattr(settings, 'screener')
    assert hasattr(settings, 'data_loader')
