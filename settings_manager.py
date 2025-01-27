from PyQt6.QtCore import QSettings
import logging
from aqt import mw
from typing import Dict, Any

logger = logging.getLogger(__name__)

class SettingsManager:
    """설정 관리를 위한 클래스"""
    
    ORGANIZATION = "LLM_response_evaluator"
    APPLICATION = "Settings"
    
    # 기본 설정값
    DEFAULT_SETTINGS = {
        "providerType": "openai",
        "openaiApiKey": "",
        "baseUrl": "https://api.openai.com",
        "modelName": "gpt-4o-mini",
        "geminiApiKey": "",
        "geminiModel": "gemini-2.0-flash-exp",
        "easyThreshold": 5,
        "goodThreshold": 40,
        "hardThreshold": 60,
        "temperature": 0.7,
        "systemPrompt": "You are a helpful assistant.",
        "debug_logging": False
    }
    
    def __init__(self):
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)
        self._observers = []
    
    def add_observer(self, observer):
        """설정 변경 알림을 받을 옵저버 추가"""
        if observer not in self._observers:
            self._observers.append(observer)
    
    def remove_observer(self, observer):
        """옵저버 제거"""
        if observer in self._observers:
            self._observers.remove(observer)
    
    def notify_observers(self, settings: Dict[str, Any]):
        """모든 옵저버에게 설정 변경 알림"""
        for observer in self._observers:
            if hasattr(observer, 'update_config'):
                observer.update_config(settings)
    
    def load_settings(self) -> Dict[str, Any]:
        """설정 로드"""
        settings = {}
        for key, default_value in self.DEFAULT_SETTINGS.items():
            value = self._settings.value(key, default_value)
            
            # 타입 변환
            if isinstance(default_value, bool):
                value = bool(value)
            elif isinstance(default_value, int):
                value = int(value)
            elif isinstance(default_value, float):
                value = float(value)
            
            settings[key] = value
        
        return settings
    
    def save_settings(self, settings: Dict[str, Any]):
        """설정 저장"""
        try:
            # 설정 저장
            for key, value in settings.items():
                self._settings.setValue(key, value)
            
            # 전역 설정 업데이트
            mw.llm_addon_settings = settings.copy()
            
            # 로깅 레벨 설정
            debug_logging = settings.get("debug_logging", False)
            logger.setLevel(logging.DEBUG if debug_logging else logging.INFO)
            
            # 옵저버들에게 알림
            self.notify_observers(settings)
            
            logger.debug("Settings saved successfully")
            return True
            
        except Exception as e:
            logger.error(f"Error saving settings: {str(e)}")
            return False
    
    def get_value(self, key: str, default=None):
        """특정 설정값 조회"""
        return self._settings.value(key, default)
    
    def set_value(self, key: str, value: Any):
        """특정 설정값 변경"""
        try:
            self._settings.setValue(key, value)
            
            # 전체 설정 로드
            current_settings = self.load_settings()
            
            # 옵저버들에게 알림
            self.notify_observers(current_settings)
            
            return True
        except Exception as e:
            logger.error(f"Error setting value for {key}: {str(e)}")
            return False

# 전역 설정 매니저 인스턴스
settings_manager = SettingsManager() 