import re
import json
import os
import sys
import logging
import concurrent.futures
from datetime import datetime
import time
import random
from abc import ABC, abstractmethod
from typing import Optional, Any, Dict, List, Generator, Callable, TypeVar, Union, cast

from aqt import mw, gui_hooks
from aqt.utils import showInfo, tooltip
from aqt.qt import *
from aqt.gui_hooks import (
    reviewer_will_end,
    reviewer_did_show_question,
    reviewer_did_show_answer,
    reviewer_did_answer_card,
    reviewer_will_show_context_menu,
)

from anki.cards import Card
from aqt.reviewer import Reviewer

from bs4 import BeautifulSoup
from PyQt6.QtCore import pyqtSlot, pyqtSignal, QObject, QTimer, QMetaObject, Q_ARG, Qt
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, 
    QSpinBox, QDoubleSpinBox, QComboBox, QGroupBox,
    QScrollArea, QHBoxLayout, QWidget, QCheckBox
)

from .message import MessageManager, show_info
from .providers import OpenAIProvider, GeminiProvider, provider_factory
from .settings_manager import settings_manager
from .bridge import Bridge
from .answer_checker_window import AnswerCheckerWindow

# Setup logging
addon_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(addon_dir, 'MyAnswerChecker_debug.log')
os.makedirs(addon_dir, exist_ok=True)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    file_handler = logging.FileHandler(log_file_path)
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

logger.info("Addon load start")

# Global objects
bridge = None
answer_checker_window = None
message_manager = MessageManager()
chat_service = None

# Constants for difficulty levels
DIFFICULTY_AGAIN = "Again"
DIFFICULTY_HARD = "Hard"
DIFFICULTY_GOOD = "Good"
DIFFICULTY_EASY = "Easy"

class LLMProvider(ABC):
    @abstractmethod
    def call_api(self, system_message: str, user_message: str, temperature: float = 0.2) -> str:
        """LLM API를 호출하여 응답을 받아옵니다."""
        pass

T = TypeVar('T')

def setup_webchannel(bridge: Bridge, web: QWebEngineView) -> None:
    """Sets up QWebChannel to enable communication between JavaScript and Python."""
    try:
        channel = QWebChannel()
        channel.registerObject('bridge', bridge)
        if hasattr(web, 'page') and hasattr(web.page(), 'setWebChannel'):
            web.page().setWebChannel(channel)
            logger.debug("QWebChannel setup complete.")
        else:
            logger.error("Could not find webview object or it does not support setWebChannel method.")
    except Exception as e:
        logger.exception("Error setting up QWebChannel: %s", e)
        message_manager.handle_response_error("Error setting up QWebChannel", str(e))

def initialize_addon() -> None:
    """Initialize the addon"""
    global bridge, chat_service, answer_checker_window
    try:
        # 설정 로드
        settings: Dict[str, Any] = settings_manager.load_settings()
        mw.llm_addon_settings = settings
        
        # Instantiate chat_service using provider factory
        from services.chat_service import ChatService
        chat_service = ChatService(settings)
        
        # 브릿지 초기화
        if bridge is None:
            bridge = Bridge()
            
        # Answer Checker Window 초기화
        if answer_checker_window is None:
            answer_checker_window = AnswerCheckerWindow(bridge, mw)
            
        logger.info("Addon initialized successfully")
    except Exception as e:
        logger.exception("Error initializing addon: %s", e)
        raise

def add_menu() -> None:
    """Add Answer Checker menu to Anki main menubar"""
    try:
        # 기존 메뉴 제거
        for action in mw.form.menubar.actions():
            if action.text() == "Answer Checker":
                mw.form.menubar.removeAction(action)
                break

        # 새 메뉴 생성
        answer_checker_menu = QMenu("Answer Checker", mw)
        mw.form.menubar.addMenu(answer_checker_menu)

        # 메뉴 항목 추가
        menu_items: List[Tuple[str, Callable[[], None]]] = [
            ("Open Answer Checker", open_answer_checker_window),
            ("Settings", openSettingsDialog)
        ]

        for label, callback in menu_items:
            action = QAction(label, answer_checker_menu)
            action.triggered.connect(callback)
            answer_checker_menu.addAction(action)
            
        logger.debug("Answer Checker menu added to main menubar")
    except Exception as e:
        logger.error(f"Error adding menu items: {str(e)}")
        raise

def open_answer_checker_window() -> None:
    """Opens the answer checker window"""
    global answer_checker_window, bridge
    try:
        if not bridge:
            initialize_addon()
        if answer_checker_window is None:
            answer_checker_window = AnswerCheckerWindow(bridge, mw)
            bridge.set_answer_checker_window(answer_checker_window)  # Bridge에 window 참조 설정
        answer_checker_window.show()
    except Exception as e:
        logger.error(f"Error opening Answer Checker: {str(e)}")
        showInfo(f"Error opening Answer Checker: {str(e)}")

def on_profile_loaded() -> None:
    """프로필이 로드될 때 호출되는 함수입니다."""
    global bridge, answer_checker_window, message_manager
    
    try:
        # Bridge 초기화
        if bridge is None:
            bridge = Bridge()
            logger.debug("Bridge initialized")

        # Answer Checker Window 초기화
        if answer_checker_window is None:
            answer_checker_window = AnswerCheckerWindow(bridge)
            logger.debug("Answer Checker Window initialized")

        # 메뉴 추가
        add_menu()
        logger.debug("Menu initialization completed")

    except Exception as e:
        logger.error(f"Error in on_profile_loaded: {str(e)}")
        show_info(f"초기화 중 오류가 발생했습니다: {str(e)}")

# Register hooks
gui_hooks.profile_did_open.append(on_profile_loaded)

def on_prepare_card(card: Card) -> None:
    """카드가 표시될 때 호출되는 함수입니다."""
    global answer_checker_window
    if not answer_checker_window or not answer_checker_window.isVisible():
        return
        
    try:
        # 이전 카드와 동일한지 확인
        if hasattr(answer_checker_window, 'last_prepared_card_id') and answer_checker_window.last_prepared_card_id == card.id:
            logger.debug("Skipping duplicate card preparation in on_prepare_card")
            return
            
        answer_checker_window.last_prepared_card_id = card.id
        
        # WebView 상태 확인
        if not answer_checker_window._check_webview_state():
            logger.debug("WebView not ready in on_prepare_card, scheduling delayed preparation")
            QTimer.singleShot(500, lambda: on_prepare_card(card))
            return
            
        card_content, _, _ = answer_checker_window.bridge.get_card_content()
        if not card_content:
            logger.error("Failed to get card content in on_prepare_card")
            return
            
        # MessageManager를 통한 메시지 생성
        question_message = answer_checker_window.message_manager.create_question_message(
            content=answer_checker_window.markdown_to_html(card_content)
        )
        
        def show_messages() -> None:
            if not answer_checker_window:
                return
            answer_checker_window.clear_chat()
            answer_checker_window.append_to_chat(question_message)
            
            if not answer_checker_window.last_difficulty_message:
                QTimer.singleShot(100, answer_checker_window.show_review_message)
            
            answer_checker_window.input_field.setFocus()
        
        # 적절한 딜레이 후 메시지 표시
        QTimer.singleShot(300, show_messages)
        
    except Exception as e:
        logger.exception("Error in on_prepare_card: %s", str(e))
        if answer_checker_window:
            answer_checker_window.show_error_message(f"문제 표시 중 오류: {str(e)}")

# Register hooks
reviewer_did_show_question.append(on_prepare_card)

from aqt import mw
from PyQt6.QtCore import QSettings
from aqt.utils import showInfo
from aqt.qt import *

def load_settings():
    """Loads settings from QSettings with default values."""
    settings = QSettings("LLM_response_evaluator", "Settings")
    defaults = {
        "apiKey": "",
        "baseUrl": "https://api.openai.com",
        "modelName": "gpt-4o-mini",
        "easyThreshold": 5,
        "goodThreshold": 40,
        "hardThreshold": 60,
        "temperature": 0.7,
        "providerType": "openai",
        "systemPrompt": "You are a helpful assistant."
    }
    
    return {key: settings.value(key, default) for key, default in defaults.items()}

def load_global_settings():
    """Loads global settings into mw.llm_addon_settings"""
    settings = QSettings("LLM_response_evaluator", "Settings")
    mw.llm_addon_settings = load_settings()
    
    # Set logging level based on settings
    debug_logging = settings.value("debug_logging", False, type=bool)
    logger.setLevel(logging.DEBUG if debug_logging else logging.INFO)
    
    logger.debug("Global settings loaded")

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Settings")
        self.setMinimumWidth(400)

        self.layout = QVBoxLayout(self)
        self.tabWidget = QTabWidget()
        
        # API Settings Tab
        self.apiTab = QWidget()
        apiLayout = QVBoxLayout()
        
        # API Provider selection
        self.providerLabel = QLabel("API Provider:")
        self.providerCombo = QComboBox()
        self.providerCombo.addItems(["OpenAI", "Gemini"])
        apiLayout.addWidget(self.providerLabel)
        apiLayout.addWidget(self.providerCombo)

        # OpenAI Settings
        self.openaiGroup = QGroupBox("OpenAI Settings")
        openaiLayout = QVBoxLayout()
        
        self.openaiKeyLabel = QLabel("OpenAI API Key:")
        self.openaiKeyEdit = QLineEdit()
        self.baseUrlLabel = QLabel("Base URL:")
        self.baseUrlEdit = QLineEdit()
        self.modelLabel = QLabel("Model Name:")
        self.modelEdit = QLineEdit()
        
        openaiLayout.addWidget(self.openaiKeyLabel)
        openaiLayout.addWidget(self.openaiKeyEdit)
        openaiLayout.addWidget(self.baseUrlLabel)
        openaiLayout.addWidget(self.baseUrlEdit)
        openaiLayout.addWidget(self.modelLabel)
        openaiLayout.addWidget(self.modelEdit)
        self.openaiGroup.setLayout(openaiLayout)
        
        # Gemini Settings
        self.geminiGroup = QGroupBox("Gemini Settings")
        geminiLayout = QVBoxLayout()
        
        self.geminiKeyLabel = QLabel("Gemini API Key:")
        self.geminiKeyEdit = QLineEdit()
        self.geminiModelLabel = QLabel("Gemini Model:")
        self.geminiModelEdit = QLineEdit()
        
        geminiLayout.addWidget(self.geminiKeyLabel)
        geminiLayout.addWidget(self.geminiKeyEdit)
        geminiLayout.addWidget(self.geminiModelLabel)
        geminiLayout.addWidget(self.geminiModelEdit)
        self.geminiGroup.setLayout(geminiLayout)

        apiLayout.addWidget(self.openaiGroup)
        apiLayout.addWidget(self.geminiGroup)
        self.apiTab.setLayout(apiLayout)

        # Difficulty Settings Tab
        self.difficultyTab = QWidget()
        difficultyLayout = QVBoxLayout()

        self.thresholdGroup = QGroupBox("Difficulty Settings")
        thresholdLayout = QVBoxLayout()

        self.easyThresholdLabel = QLabel("Easy Threshold (seconds):")
        self.easyThresholdEdit = QSpinBox()
        self.easyThresholdEdit.setRange(1, 60)
        
        self.goodThresholdLabel = QLabel("Good Threshold (seconds):")
        self.goodThresholdEdit = QSpinBox()
        self.goodThresholdEdit.setRange(1, 60)
        
        self.hardThresholdLabel = QLabel("Hard Threshold (seconds):")
        self.hardThresholdEdit = QSpinBox()
        self.hardThresholdEdit.setRange(1, 60)

        thresholdLayout.addWidget(self.easyThresholdLabel)
        thresholdLayout.addWidget(self.easyThresholdEdit)
        thresholdLayout.addWidget(self.goodThresholdLabel)
        thresholdLayout.addWidget(self.goodThresholdEdit)
        thresholdLayout.addWidget(self.hardThresholdLabel)
        thresholdLayout.addWidget(self.hardThresholdEdit)
        self.thresholdGroup.setLayout(thresholdLayout)
        difficultyLayout.addWidget(self.thresholdGroup)
        self.difficultyTab.setLayout(difficultyLayout)

        # General Settings Tab
        self.generalTab = QWidget()
        generalLayout = QVBoxLayout()

        # Temperature settings
        self.temperatureLabel = QLabel("Temperature (0.0 ~ 1.0):")
        self.temperatureEdit = QDoubleSpinBox()
        self.temperatureEdit.setRange(0.0, 1.0)
        self.temperatureEdit.setSingleStep(0.1)
        self.temperatureEdit.setDecimals(2)
        generalLayout.addWidget(self.temperatureLabel)
        generalLayout.addWidget(self.temperatureEdit)

        # Debug logging settings
        self.debugGroup = QGroupBox("Debug Settings")
        debugLayout = QVBoxLayout()
        
        self.debugLoggingCheckbox = QCheckBox("Enable Debug Logging")
        debugLayout.addWidget(self.debugLoggingCheckbox)
        
        self.debugGroup.setLayout(debugLayout)
        generalLayout.addWidget(self.debugGroup)

        # System Prompt Settings
        systemPromptGroup = QGroupBox("System Prompt Settings")
        systemPromptLayout = QVBoxLayout()
        
        self.systemPromptEdit = QLineEdit()
        self.systemPromptEdit.setPlaceholderText("Enter system prompt (e.g., Answer like a cat)")
        systemPromptLayout.addWidget(QLabel("System Prompt:"))
        systemPromptLayout.addWidget(self.systemPromptEdit)
        
        systemPromptGroup.setLayout(systemPromptLayout)
        generalLayout.addWidget(systemPromptGroup)
        self.generalTab.setLayout(generalLayout)

        # Add tabs
        self.tabWidget.addTab(self.apiTab, "API Settings")
        self.tabWidget.addTab(self.difficultyTab, "Difficulty")
        self.tabWidget.addTab(self.generalTab, "General")
        
        self.layout.addWidget(self.tabWidget)

        # Save button
        self.saveButton = QPushButton("Save")
        self.saveButton.clicked.connect(self.saveSettings)
        self.layout.addWidget(self.saveButton)

        # Event connections
        self.providerCombo.currentTextChanged.connect(self.onProviderChanged)
        
        self.loadSettings()
        self.onProviderChanged(self.providerCombo.currentText())

    def onProviderChanged(self, provider):
        """Updates UI when API provider changes"""
        if provider.lower() == "openai":
            self.openaiGroup.show()
            self.geminiGroup.hide()
        else:
            self.openaiGroup.hide()
            self.geminiGroup.show()

    def loadSettings(self):
        """Loads settings into UI"""
        settings = settings_manager.load_settings()
        
        # API provider settings
        provider = settings.get("providerType", "openai")
        self.providerCombo.setCurrentText(provider.capitalize())
        
        # OpenAI settings
        self.openaiKeyEdit.setText(settings.get("openaiApiKey", ""))
        self.baseUrlEdit.setText(settings.get("baseUrl", "https://api.openai.com"))
        self.modelEdit.setText(settings.get("modelName", "gpt-4o-mini"))
        
        # Gemini settings
        self.geminiKeyEdit.setText(settings.get("geminiApiKey", ""))
        self.geminiModelEdit.setText(settings.get("geminiModel", "gemini-2.0-flash-exp"))
        
        # Other settings
        self.easyThresholdEdit.setValue(int(settings.get("easyThreshold", 5)))
        self.goodThresholdEdit.setValue(int(settings.get("goodThreshold", 40)))
        self.hardThresholdEdit.setValue(int(settings.get("hardThreshold", 60)))
        self.temperatureEdit.setValue(float(settings.get("temperature", 0.7)))
        
        # Debug settings
        self.debugLoggingCheckbox.setChecked(settings.get("debug_logging", False))
        
        # System prompt
        self.systemPromptEdit.setText(settings.get("systemPrompt", "You are a helpful assistant."))

    def saveSettings(self):
        """Saves settings"""
        settings = {
            "providerType": self.providerCombo.currentText().lower(),
            "openaiApiKey": self.openaiKeyEdit.text(),
            "baseUrl": self.baseUrlEdit.text(),
            "modelName": self.modelEdit.text(),
            "geminiApiKey": self.geminiKeyEdit.text(),
            "geminiModel": self.geminiModelEdit.text(),
            "easyThreshold": self.easyThresholdEdit.value(),
            "goodThreshold": self.goodThresholdEdit.value(),
            "hardThreshold": self.hardThresholdEdit.value(),
            "temperature": self.temperatureEdit.value(),
            "systemPrompt": self.systemPromptEdit.text(),
            "debug_logging": self.debugLoggingCheckbox.isChecked()
        }
        
        if settings_manager.save_settings(settings):
            showInfo("Settings saved successfully.")
            self.accept()
        else:
            showInfo("Failed to save settings. Please try again.")

# Function to open settings dialog
def openSettingsDialog():
    dialog = SettingsDialog(mw)
    dialog.exec()

def on_js_message(handled, msg, context):
    """JavaScript 메시지 처리"""
    if not isinstance(msg, str):
        return handled
    try:
        data = json.loads(msg)
        if "type" in data and data["type"] == "error":
            message_manager.handle_response_error(data.get("message", "Unknown error"))
        elif "type" in data and data["type"] == "response":
            message_manager.process_complete_response(data.get("text", ""), data.get("model", "Unknown Model"))
    except json.JSONDecodeError:
        message_manager.handle_response_error("Invalid message format")
    except Exception as e:
        message_manager.handle_response_error("Error processing message", str(e))
    return handled

gui_hooks.webview_did_receive_js_message.append(on_js_message)

# Initial settings load
load_global_settings()

def on_show_question(card):
    global bridge
    if bridge:
        bridge.start_timer()

def on_show_answer(card):
    global bridge
    if bridge:
        bridge.stop_timer()

# Execute the on_show_question hook every time the card changes
reviewer_did_show_question.append(on_show_question)
reviewer_did_show_answer.append(on_show_answer)

def showInfo(message):
    """에러 메시지 표시를 위한 래퍼 함수"""
    try:
        from aqt.utils import showInfo as anki_showInfo
        # GUI 스레드에서 실행되도록 보장
        if mw.thread() != QThread.currentThread():
            QTimer.singleShot(0, lambda: anki_showInfo(message))
        else:
            anki_showInfo(message)
    except Exception as e:
        logger.error(f"Error showing info dialog: {str(e)}")

# ...existing code...
# ...existing code...
    def handle_response_error(self, error_message, error_detail):
        """Handles errors during response processing"""
        logger.error(f"{error_message}: {error_detail}")
        error_html = f"""
        <div class="system-message-container">
            <div class="system-message">
                <p style='color: red;'>{error_message}</p>
            </div>
            <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
        </div>
        """
        self.append_to_chat(error_html)
        QTimer.singleShot(0, lambda: showInfo(error_message))
# ...existing code...

        def _process_complete_response(self, response_text):
            """Process complete response and update UI"""
            try:
                complete_json = self.partial_response + response_text
                response_json = json.loads(complete_json)
                self._clear_request_data(request_id)
# ...existing code...

            except json.JSONDecodeError:
                logger.warning("Incomplete JSON received, buffering...")
            except Exception as e:
                logger.exception("Unexpected error")
                # Buffer incomplete JSON
                self.partial_response += response_text
                self.partial_response = ""  # Reset buffer after successful parse
                # ...existing response 처리 로직...

class MainController:
    def __init__(self) -> None:
        self.thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=3)
        self.current_provider = None
        self.initialize_provider()
    
    def initialize_provider(self) -> None:
        try:
            provider_name = settings_manager.get("provider", "openai")
            self.current_provider = provider_factory.create_provider(provider_name)
        except Exception as e:
            logger.error(f"프로바이더 초기화 실패: {str(e)}")
            self.current_provider = None

    def show_question_(self, card: Card) -> None:
        """카드 질문이 표시될 때 호출되는 핸들러"""
        if not self.current_provider:
            return
        try:
            logger.debug(f"Question shown for card: {card.id}")
            # 여기에 질문 표시 로직 구현
        except Exception as e:
            logger.error(f"Error in show_question_: {str(e)}")

    def show_answer_(self, card: Card) -> None:
        """카드 답변이 표시될 때 호출되는 핸들러"""
        if not self.current_provider:
            return
        try:
            logger.debug(f"Answer shown for card: {card.id}")
            # 여기에 답변 표시 로직 구현
        except Exception as e:
            logger.error(f"Error in show_answer_: {str(e)}")

    def prepare_card_(self, card: Card) -> None:
        """카드 준비 시 호출되는 핸들러"""
        if not self.current_provider:
            return
        try:
            logger.debug(f"Preparing card: {card.id}")
            # 여기에 카드 준비 로직 구현
        except Exception as e:
            logger.error(f"Error in prepare_card_: {str(e)}")

    def cleanup(self) -> None:
        """리소스 정리"""
        if self.thread_pool:
            self.thread_pool.shutdown(wait=False)