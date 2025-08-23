from typing import Dict, Any, List, Optional, Protocol, TypeVar, Union, cast
from dataclasses import dataclass
from aqt.qt import QSettings

import logging
from aqt import mw

logger = logging.getLogger(__name__)

class SettingsObserver(Protocol):
    """설정 변경 알림을 받는 옵저버를 위한 프로토콜"""
    def update_config(self, settings: Dict[str, Any]) -> None:
        """설정이 변경되었을 때 호출되는 메서드"""
        ...

@dataclass
class Settings:
    """설정 데이터를 담는 클래스"""
    providerType: str = "openai"
    openaiApiKey: str = ""
    baseUrl: str = "https://api.openai.com"
    modelName: str = "gpt-5-nano"
    geminiApiKey: str = ""
    geminiModel: str = "gemini-2.5-flash-lite"
    easyThreshold: int = 5
    goodThreshold: int = 40
    hardThreshold: int = 60
    temperature: float = 0.7
    systemPrompt: str = "You are a helpful assistant."
    debug_logging: bool = False

class SettingsError(Exception):
    """설정 관련 예외 클래스"""
    pass

class SettingsManager:
    """설정 관리를 위한 클래스"""
    
    ORGANIZATION: str = "LLM_response_evaluator"
    APPLICATION: str = "Settings"
    
    def __init__(self) -> None:
        self._settings: QSettings = QSettings(self.ORGANIZATION, self.APPLICATION)
        self._observers: List[SettingsObserver] = []
        self._current_settings: Settings = Settings()
        self._load_initial_settings()
    
    def _load_initial_settings(self) -> None:
        """초기 설정 로드"""
        try:
            settings_dict = self.load_settings()
            for key, value in settings_dict.items():
                if hasattr(self._current_settings, key):
                    setattr(self._current_settings, key, value)
        except Exception as e:
            logger.error(f"초기 설정 로드 실패: {str(e)}")
            # 기본값 유지
    
    def add_observer(self, observer: SettingsObserver) -> None:
        """설정 변경 알림을 받을 옵저버 추가"""
        if observer not in self._observers:
            self._observers.append(observer)
            logger.debug(f"Observer added: {observer.__class__.__name__}")
    
    def remove_observer(self, observer: SettingsObserver) -> None:
        """옵저버 제거"""
        if observer in self._observers:
            self._observers.remove(observer)
            logger.debug(f"Observer removed: {observer.__class__.__name__}")
    
    def notify_observers(self, settings: Dict[str, Any]) -> None:
        """모든 옵저버에게 설정 변경 알림"""
        for observer in self._observers:
            try:
                observer.update_config(settings)
            except Exception as e:
                logger.error(f"Observer notification failed: {observer.__class__.__name__} - {str(e)}")
    
    def load_settings(self) -> Dict[str, Any]:
        """설정 로드"""
        try:
            settings = {}
            current = self._current_settings.__dict__
            
            for key, default_value in current.items():
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
            
        except Exception as e:
            logger.error(f"설정 로드 실패: {str(e)}")
            return self._current_settings.__dict__.copy()
    
    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """설정 저장"""
        try:
            # 설정값 검증
            self._validate_settings(settings)
            
            # 설정 저장
            for key, value in settings.items():
                self._settings.setValue(key, value)
                if hasattr(self._current_settings, key):
                    setattr(self._current_settings, key, value)
            
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
            logger.error(f"설정 저장 실패: {str(e)}")
            return False
    
    def _validate_settings(self, settings: Dict[str, Any]) -> None:
        """설정값 유효성 검사"""
        try:
            # 필수 필드 확인
            required_fields = ["providerType", "modelName", "temperature"]
            for field in required_fields:
                if field not in settings:
                    raise SettingsError(f"Missing required setting: {field}")
            
            # 값 범위 검사
            if "temperature" in settings:
                temp = float(settings["temperature"])
                if not 0.0 <= temp <= 1.0:
                    raise SettingsError("temperature must be between 0.0 and 1.0")
            
            # 임계값 검사
            thresholds = ["easyThreshold", "goodThreshold", "hardThreshold"]
            for threshold in thresholds:
                if threshold in settings:
                    value = int(settings[threshold])
                    if not 0 <= value <= 100:
                        raise SettingsError(f"{threshold} must be between 0 and 100")
            
        except ValueError as e:
            raise SettingsError(f"Invalid settings value format: {str(e)}")
    
    def get_value(self, key: str, default: Any = None) -> Any:
        """특정 설정값 조회"""
        try:
            if hasattr(self._current_settings, key):
                return getattr(self._current_settings, key)
            return self._settings.value(key, default)
        except Exception as e:
            logger.error(f"설정값 조회 실패 ({key}): {str(e)}")
            return default
    
    def set_value(self, key: str, value: Any) -> bool:
        """특정 설정값 변경"""
        try:
            # 설정값 검증
            test_settings = self.load_settings()
            test_settings[key] = value
            self._validate_settings(test_settings)
            
            # 설정 저장
            self._settings.setValue(key, value)
            if hasattr(self._current_settings, key):
                setattr(self._current_settings, key, value)
            
            # 전체 설정 로드
            current_settings = self.load_settings()
            
            # 옵저버들에게 알림
            self.notify_observers(current_settings)
            
            logger.debug(f"Setting updated: {key} = {value}")
            return True
            
        except Exception as e:
            logger.error(f"설정값 변경 실패 ({key}): {str(e)}")
            return False

# 전역 설정 매니저 인스턴스
settings_manager = SettingsManager() 