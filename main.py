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

def add_menu():
    # "Tools" menu
    tools_menu = None
    for action in mw.form.menubar.actions():
        if action.text() == "&Tools":
            tools_menu = action.menu()
            break

    # Exit if "Tools" menu is not found
    if tools_menu is None:
        print("Error: Tools menu not found.")
        return

    # Create "Answer Checker" menu
    answer_checker_menu = QMenu("Answer Checker", tools_menu)
    tools_menu.addMenu(answer_checker_menu)

    # Create "Open" action
    open_action = QAction("Open Answer Checker", answer_checker_menu)
    open_action.triggered.connect(lambda: open_answer_checker_window(bridge))
    answer_checker_menu.addAction(open_action)

    # Create "Settings" action
    settings_action = QAction("Settings", answer_checker_menu)
    settings_action.triggered.connect(openSettingsDialog)
    answer_checker_menu.addAction(settings_action)

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

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Settings")
        self.setMinimumWidth(400)

        self.layout = QVBoxLayout(self)

        # Create tab widget
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
        self.generalTab.setLayout(generalLayout)

        # 시스템 프롬프트 설정 그룹
        systemPromptGroup = QGroupBox("System Prompt Settings")
        systemPromptLayout = QVBoxLayout()
        
        self.systemPromptEdit = QLineEdit()
        self.systemPromptEdit.setPlaceholderText("Enter system prompt (e.g., Answer like a cat)")
        systemPromptLayout.addWidget(QLabel("System Prompt:"))
        systemPromptLayout.addWidget(self.systemPromptEdit)
        
        systemPromptGroup.setLayout(systemPromptLayout)
        generalLayout.addWidget(systemPromptGroup)

        # Add tabs to tab widget
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
        settings = QSettings("LLM_response_evaluator", "Settings")
        
        # API provider settings
        provider = settings.value("providerType", "openai")
        self.providerCombo.setCurrentText(provider.capitalize())
        
        # OpenAI settings
        self.openaiKeyEdit.setText(settings.value("openaiApiKey", ""))
        self.baseUrlEdit.setText(settings.value("baseUrl", "https://api.openai.com"))
        self.modelEdit.setText(settings.value("modelName", "gpt-4o-mini"))
        
        # Gemini settings
        self.geminiKeyEdit.setText(settings.value("geminiApiKey", ""))
        self.geminiModelEdit.setText(settings.value("geminiModel", "gemini-2.0-flash-exp"))
        
        # Other settings
        self.easyThresholdEdit.setValue(int(settings.value("easyThreshold", "5")))
        self.goodThresholdEdit.setValue(int(settings.value("goodThreshold", "40")))
        self.hardThresholdEdit.setValue(int(settings.value("hardThreshold", "60")))
        self.temperatureEdit.setValue(float(settings.value("temperature", "0.7")))
        
        # Load debug settings
        self.debugLoggingCheckbox.setChecked(settings.value("debug_logging", False, type=bool))

        # Load system prompt (remove language setting)
        self.systemPromptEdit.setText(settings.value("systemPrompt", "You are a helpful assistant."))

    def saveSettings(self):
        """Saves settings"""
        settings = QSettings("LLM_response_evaluator", "Settings")
        
        # API provider settings
        provider_type = self.providerCombo.currentText().lower()
        settings.setValue("providerType", provider_type)
        
        # OpenAI settings (키 이름 수정)
        settings.setValue("openaiApiKey", self.openaiKeyEdit.text())  # 기존 "apiKey" -> "openaiApiKey"로 변경
        settings.setValue("baseUrl", self.baseUrlEdit.text())
        settings.setValue("modelName", self.modelEdit.text())
        
        # Gemini settings (키 이름 수정)
        settings.setValue("geminiApiKey", self.geminiKeyEdit.text())  # 추가
        settings.setValue("geminiModel", self.geminiModelEdit.text())  # 추가
        
        # Other settings
        settings.setValue("easyThreshold", str(self.easyThresholdEdit.value()))
        settings.setValue("goodThreshold", str(self.goodThresholdEdit.value()))
        settings.setValue("hardThreshold", str(self.hardThresholdEdit.value()))
        settings.setValue("temperature", str(self.temperatureEdit.value()))
        
        # Save system prompt instead of language
        settings.setValue("systemPrompt", self.systemPromptEdit.text())
        
        # Remove language setting
        settings.remove("language")
        
        # Save debug settings
        settings.setValue("debug_logging", self.debugLoggingCheckbox.isChecked())
        
        # Update logging level
        if self.debugLoggingCheckbox.isChecked():
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)

        # Update Bridge's LLM provider
        if bridge:
            try:
                bridge.update_llm_provider()
                # 설정 변경 후 대화 기록 초기화 추가
                bridge.clear_conversation_history()
                if answer_checker_window:
                    answer_checker_window.clear_chat()
            except Exception as e:
                showInfo(f"모델 변경 중 오류 발생: {str(e)}")

        load_global_settings()
        showInfo("Settings saved successfully.")
        self.accept()

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