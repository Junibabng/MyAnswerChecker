import re
import json
import os
import sys
import threading
import logging
from aqt import mw, gui_hooks, QAction, QInputDialog, QMenu, QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox
from aqt.utils import showInfo
from bs4 import BeautifulSoup
from PyQt6.QtCore import pyqtSlot, pyqtSignal, QObject, QTimer, QMetaObject, Q_ARG, Qt
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QScrollArea, QHBoxLayout, QWidget
import requests
from datetime import datetime
import time
from aqt.qt import *
from abc import ABC, abstractmethod
from aqt.gui_hooks import (
    reviewer_will_end,
    reviewer_did_show_question,
    reviewer_did_show_answer,
    reviewer_did_answer_card,
    reviewer_will_show_context_menu,
)

from .message import MessageManager, show_info
from .providers import OpenAIProvider, GeminiProvider

# Logging setup (Corrected)
import logging
import os
from aqt import mw
from aqt.qt import QSettings
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QDoubleSpinBox, QComboBox, QGroupBox

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

# Global bridge object
bridge = None
answer_checker_window = None
message_manager = MessageManager()

# Constants for difficulty levels
DIFFICULTY_AGAIN = "Again"
DIFFICULTY_HARD = "Hard"
DIFFICULTY_GOOD = "Good"
DIFFICULTY_EASY = "Easy"

class LLMProvider(ABC):
    @abstractmethod
    def call_api(self, system_message, user_message, temperature=0.2):
        pass

from .bridge import Bridge
from .answer_checker_window import AnswerCheckerWindow

# Initialize Bridge and AnswerCheckerWindow
bridge = Bridge()

def setup_webchannel(bridge, web):
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

def initialize_addon():
    """Initialize the addon"""
    global bridge
    try:
        # 설정 로드
        settings = settings_manager.load_settings()
        mw.llm_addon_settings = settings
        
        # 브릿지 초기화
        if bridge is None:
            bridge = Bridge()
            
        logger.info("Addon initialized successfully")
    except Exception as e:
        logger.exception("Error initializing addon: %s", e)
        raise

def add_menu():
    """Add menu items to Anki"""
    try:
        # 기존 메뉴 확인
        tools_menu = None
        answer_checker_menu = None
        
        for action in mw.form.menubar.actions():
            if action.text() == "&Tools":
                tools_menu = action.menu()
                # 기존 Answer Checker 메뉴 찾기
                for menu_action in tools_menu.actions():
                    if menu_action.text() == "Answer Checker":
                        answer_checker_menu = menu_action.menu()
                        break
                break

        if tools_menu is None:
            logger.error("Tools menu not found")
            return
            
        # 이미 메뉴가 있으면 제거
        if answer_checker_menu is not None:
            tools_menu.removeAction(answer_checker_menu.menuAction())

        # 새 메뉴 생성
        answer_checker_menu = QMenu("Answer Checker", tools_menu)
        tools_menu.addMenu(answer_checker_menu)

        # 메뉴 항목 추가
        menu_items = [
            ("Open Answer Checker", open_answer_checker_window),
            ("Settings", openSettingsDialog)
        ]

        for label, callback in menu_items:
            action = QAction(label, answer_checker_menu)
            action.triggered.connect(callback)
            answer_checker_menu.addAction(action)
            
        logger.debug("Menu items added successfully")
    except Exception as e:
        logger.error(f"Error adding menu items: {str(e)}")
        raise

def open_answer_checker_window():
    """Opens the answer checker window"""
    global bridge
    window = AnswerCheckerWindow(bridge, mw)
    window.show()

def on_profile_loaded():
    """Function to be executed when the profile is loaded"""
    global bridge
    try:
        load_global_settings()
        if bridge is None:
            bridge = Bridge()
            add_menu()
            logger.info("Addon initialization complete")
        else:
            logger.info("Addon already initialized.")
    except Exception as e:
        logger.exception("Error initializing addon: %s", e)
        showInfo(f"Error initializing addon: ")

# Register hooks
gui_hooks.profile_did_open.append(on_profile_loaded)

def on_prepare_card(card):
    """카드가 표시될 때 호출되는 함수입니다."""
    global answer_checker_window
    if answer_checker_window and answer_checker_window.isVisible():
        try:
            card_content, _, _ = answer_checker_window.bridge.get_card_content()
            if card_content:
                # MessageManager를 통한 메시지 생성
                question_message = answer_checker_window.message_manager.create_question_message(
                    content=answer_checker_window.markdown_to_html(card_content)
                )
                
                answer_checker_window.clear_chat()
                answer_checker_window.append_to_chat(question_message)
                
                if not answer_checker_window.last_difficulty_message:
                    QTimer.singleShot(100, answer_checker_window.show_review_message)
            
            answer_checker_window.input_field.setFocus()
            
        except Exception as e:
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

from .settings_manager import settings_manager

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