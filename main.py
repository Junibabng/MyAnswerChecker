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

# Logging setup (Corrected)
import logging
import os

addon_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(addon_dir, 'MyAnswerChecker_debug.log')
os.makedirs(addon_dir, exist_ok=True)

# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Set the minimum logging level

# Create a file handler
file_handler = logging.FileHandler(log_file_path)
file_handler.setLevel(logging.DEBUG)  # Set the minimum logging level for the file handler

# Create a formatter
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

# Add the file handler to the logger
logger.addHandler(file_handler)

logger.info("Addon load start")

# Global bridge object
bridge = None
answer_checker_window = None

# Constants for difficulty levels
DIFFICULTY_AGAIN = "Again"
DIFFICULTY_HARD = "Hard"
DIFFICULTY_GOOD = "Good"
DIFFICULTY_EASY = "Easy"

class LLMProvider(ABC):
    @abstractmethod
    def call_api(self, system_message, user_message, temperature=0.2):
        pass

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key, base_url, model_name):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name

    def call_api(self, system_message, user_message, temperature=0.2):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            "temperature": temperature
        }
        response = requests.post(f"{self.base_url}/v1/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()

class GeminiProvider(LLMProvider):
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp"):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def call_api(self, system_message, user_message, temperature=0.2):
        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": user_message
                }]
            }],
            "systemInstruction": {
                "role": "user",
                "parts": [{
                    "text": system_message
                }]
            },
            "generationConfig": {
                "temperature": temperature,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 8192,
                "responseMimeType": "text/plain"
            }
        }
        
        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()

        # Gemini Flash Thinking 모델의 경우 사고 과정 제외
        if "flash-thinking" in self.model_name.lower():
            if result.get('candidates') and result['candidates'][0].get('content', {}).get('parts'):
                parts = result['candidates'][0]['content']['parts']
                # 첫 번째 부분(사고 과정)을 제외한 나머지 부분을 결합
                final_response = " ".join(part.get('text', '').strip() for part in parts[1:])
                return final_response.strip()
        
        # 일반 Gemini 모델의 경우 기존 처리 방식 유지
        return result['candidates'][0]['content']['parts'][0]['text'].strip()

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
        showInfo(f"Error setting up QWebChannel: ")

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
    """Focus on the text input field when a new card is displayed"""
    global answer_checker_window
    if answer_checker_window and answer_checker_window.isVisible():
        answer_checker_window.web_view.setHtml(answer_checker_window.default_html)
        answer_checker_window.input_field.setFocus()

# Register hooks
reviewer_did_show_question.append(on_prepare_card)

from aqt import mw
from PyQt6.QtCore import QSettings
from aqt.utils import showInfo
from aqt.qt import *

def load_settings():
    """Loads settings from QSettings with default values."""
    settings = QSettings("LLM_response_evaluator", "Settings")
    return {
        "apiKey": settings.value("apiKey", ""),
        "baseUrl": settings.value("baseUrl", "https://api.openai.com"),
        "modelName": settings.value("modelName", "gpt-4o-mini"),
        "easyThreshold": int(settings.value("easyThreshold", "5")),
        "goodThreshold": int(settings.value("goodThreshold", "15")),
        "hardThreshold": int(settings.value("hardThreshold", "50")),
        "language": settings.value("language", "English")
    }

def load_global_settings():
    """Loads global settings into a global variable."""
    mw.llm_addon_settings = load_settings()

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plugin Settings")
        self.setMinimumWidth(400)

        self.layout = QVBoxLayout(self)

        # API Provider selection
        self.providerLabel = QLabel("API Provider:")
        self.providerCombo = QComboBox()
        self.providerCombo.addItems(["OpenAI", "Gemini"])
        self.layout.addWidget(self.providerLabel)
        self.layout.addWidget(self.providerCombo)

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

        self.layout.addWidget(self.openaiGroup)
        self.layout.addWidget(self.geminiGroup)

        # Difficulty threshold settings
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
        self.layout.addWidget(self.thresholdGroup)

        # Language settings
        self.languageLabel = QLabel("Response Language:")
        self.languageEdit = QLineEdit()
        self.layout.addWidget(self.languageLabel)
        self.layout.addWidget(self.languageEdit)

        # Temperature settings
        self.temperatureLabel = QLabel("Temperature (0.0 ~ 1.0):")
        self.temperatureEdit = QDoubleSpinBox()
        self.temperatureEdit.setRange(0.0, 1.0)
        self.temperatureEdit.setSingleStep(0.1)
        self.temperatureEdit.setDecimals(2)
        self.layout.addWidget(self.temperatureLabel)
        self.layout.addWidget(self.temperatureEdit)

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
        self.goodThresholdEdit.setValue(int(settings.value("goodThreshold", "15")))
        self.hardThresholdEdit.setValue(int(settings.value("hardThreshold", "50")))
        self.languageEdit.setText(settings.value("language", "English"))
        self.temperatureEdit.setValue(float(settings.value("temperature", "0.2")))

    def saveSettings(self):
        """Saves settings"""
        settings = QSettings("LLM_response_evaluator", "Settings")
        
        # API provider settings
        provider_type = self.providerCombo.currentText().lower()
        settings.setValue("providerType", provider_type)
        
        # OpenAI settings
        settings.setValue("openaiApiKey", self.openaiKeyEdit.text())
        settings.setValue("baseUrl", self.baseUrlEdit.text())
        settings.setValue("modelName", self.modelEdit.text())
        
        # Gemini settings
        settings.setValue("geminiApiKey", self.geminiKeyEdit.text())
        settings.setValue("geminiModel", self.geminiModelEdit.text())
        
        # Other settings
        settings.setValue("easyThreshold", str(self.easyThresholdEdit.value()))
        settings.setValue("goodThreshold", str(self.goodThresholdEdit.value()))
        settings.setValue("hardThreshold", str(self.hardThresholdEdit.value()))
        settings.setValue("language", self.languageEdit.text())
        settings.setValue("temperature", str(self.temperatureEdit.value()))

        # Update Bridge's LLM provider
        if bridge:
            bridge.update_llm_provider()

        load_global_settings()
        showInfo("Settings saved successfully.")
        self.accept()

# Function to open settings dialog
def openSettingsDialog():
    dialog = SettingsDialog(mw)
    dialog.exec()

# Function to handle JavaScript message from pycmd
def on_js_message(handled, msg, context):
    if msg == "open_settings":
        openSettingsDialog()
        return (True, None)
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
