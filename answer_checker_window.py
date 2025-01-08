from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QHBoxLayout, QInputDialog, QDoubleSpinBox, QSpinBox, QComboBox, QGroupBox
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QTimer, Qt, QThread, QMetaObject, Q_ARG, pyqtSlot
from PyQt6.QtWebChannel import QWebChannel
from aqt import mw, gui_hooks
from aqt.utils import showInfo
from aqt.qt import *
from aqt.gui_hooks import (
    reviewer_did_show_question,
    reviewer_did_show_answer,
    reviewer_did_answer_card
)
from datetime import datetime
import json
import re
import time
import logging
import threading

logger = logging.getLogger(__name__)

class AnswerCheckerWindow(QDialog):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setWindowTitle("MyAnswerChecker")
        self.setGeometry(300, 300, 600, 400)
        self.layout = QVBoxLayout(self)
        self.last_response = None
        self.is_webview_initialized = False
        self.last_difficulty_message = None
        self.last_question_time = 0
        
        self.input_label = QLabel("Enter your answer:")
        self.input_field = QLineEdit()
        self.send_button = QPushButton("Send")

        self.joke_button = QPushButton("Joke 😆")
        self.edit_advice_button = QPushButton("Card Edit ✏️")
        
        self.timer_label = QLabel("Elapsed time: 0 seconds") 
        self.layout.addWidget(self.timer_label)

        self.web_view = QWebEngineView()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.web_view)

        self.layout.addWidget(self.scroll_area)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        self.layout.addLayout(input_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.joke_button)
        buttons_layout.addWidget(self.edit_advice_button)
        self.layout.addLayout(buttons_layout)

        button_style = """
            QPushButton {
                border-radius: 15px;
                padding: 5px;
                background-color: #333;
                border: 1px solid #555;
                color: #fff;
            }
            QPushButton:hover {
                background-color: #444;
            }
        """
        self.joke_button.setStyleSheet(button_style)
        self.edit_advice_button.setStyleSheet(button_style)

        self.send_button.clicked.connect(self.send_answer)
        self.joke_button.clicked.connect(self.show_joke)
        self.edit_advice_button.clicked.connect(self.show_edit_advice)

        self.bridge.sendResponse.connect(self.display_response)
        self.bridge.sendQuestionResponse.connect(self.display_question_response)
        self.bridge.sendJokeResponse.connect(self.display_joke)
        self.bridge.sendEditAdviceResponse.connect(self.display_edit_advice)
        self.bridge.timer_signal.connect(self.update_timer_display)
        self.bridge.stream_data_received.connect(self.bridge.update_response_chunk)
        
        self.default_html = """
        <!DOCTYPE html>
        <html>
        <head>
        <style>
        body {
            font-family: 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
            background-color: #b2c7d9;
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            min-height: 100vh;
        }

        .chat-container {
            flex-grow: 1;
            overflow-y: auto;
            padding: 10px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            max-width: 800px; 
            margin: 0 auto;
        }

        .message-container {
            width: 100%;
            display: flex;
            flex-direction: column;
            margin: 8px 0;
            position: relative;
        }

        .message {
            position: relative;
            padding: 12px 16px;
            max-width: 70%;
            word-wrap: break-word;
            font-size: 14px;
            line-height: 1.4;
        }

        .user-message-container {
            align-items: flex-end;
        }

        .user-message {
            background-color: #ffeb33;
            margin-left: auto;
            border-radius: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            color: #000000;
            position: relative;
            margin-right: 16px;
            padding: 14px 18px;
            max-width: 75%;
        }

        .system-message-container {
            align-items: flex-start;
        }

        .system-message {
            background-color: #ffffff;
            margin-right: auto;
            border-radius: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            color: #000000;
            position: relative;
            margin-left: 16px;
            padding: 14px 18px;
            max-width: 75%;
        }

        .message-time {
            font-size: 11px;
            color: #8e8e8e;
            margin-top: 4px;
            padding: 0 12px;
            align-self: flex-end;
        }

        .user-message-container .message-time {
            align-self: flex-end;
        }

        .system-message-container .message-time {
            align-self: flex-start;
        }

        .read-status {
            font-size: 11px;
            color: #8e8e8e;
            margin-top: 2px;
            margin-right: 12px;
        }

        .loading-indicator {
            background-color: transparent;
            border-radius: 20px;
            padding: 18px;
            margin: 8px 0;
            box-shadow: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            max-width: 75%;
        }

        .model-info {
            font-size: 12px;
            color: #666;
            margin-bottom: 4px;
            margin-left: 16px;
            font-weight: bold;
        }

        .loading-dots {
            display: flex;
            gap: 6px;
        }

        .loading-dots span {
            width: 8px;
            height: 8px;
            background-color: #b2b2b2;
            border-radius: 50%;
            display: inline-block;
            animation: bounce 1.4s infinite ease-in-out both;
        }

        .loading-dots span:nth-child(1) { animation-delay: -0.32s; }
        .loading-dots span:nth-child(2) { animation-delay: -0.16s; }

        @keyframes bounce {
            0%, 80%, 100% { 
                transform: scale(0);
            }
            40% { 
                transform: scale(1.0);
            }
        }

        .recommendation-again {
            background-color: red;
            color: white;
            border-radius: 12px;
            padding: 5px 10px;
            display: inline-block;
        }

        .recommendation-hard {
            background-color: #f0ad4e;
            color: white;
            border-radius: 12px;
            padding: 5px 10px;
            display: inline-block;
        }

        .recommendation-good {
            background-color: green;
            color: white;
            border-radius: 12px;
            padding: 5px 10px;
            display: inline-block;
        }

        .recommendation-easy {
            background-color: blue;
            color: white;
            border-radius: 12px;
            padding: 5px 10px;
            display: inline-block;
        }

        .system-message h2,
        .system-message h3 {
            margin: 0 0 8px 0;
            font-size: 15px;
            color: #333;
        }

        .system-message p {
            margin: 0 0 8px 0;
            line-height: 1.5;
        }

        .system-message p:last-child {
            margin-bottom: 0;
        }

        .evaluation, .recommendation, .answer, .reference {
            margin: 8px 0;
            padding: 8px 0;
            border-bottom: 1px solid rgba(0,0,0,0.1);
        }

        .evaluation:last-child,
        .recommendation:last-child,
        .answer:last-child,
        .reference:last-child {
            border-bottom: none;
            padding-bottom: 0;
        }
        </style>
        </head>
        <body>
        <div class="chat-container"></div>
        </body>
        </html>
        """
        self.input_field.returnPressed.connect(self.handle_enter_key)
        self.initialize_webview()
        reviewer_did_show_question.append(self.on_show_question)
        reviewer_did_show_answer.append(self.on_show_answer)
        reviewer_did_answer_card.append(self.on_user_answer_card)

        self.is_initial_answer = True
        self.is_processing = False

    def initialize_webview(self):
        """Initializes the webview with default HTML and sets the background color explicitly."""
        if not self.is_webview_initialized:
            logger.debug("=== WebView Initialization ===")
            self.web_view.setHtml(self.default_html)
            self.is_webview_initialized = True
            self.web_view.page().setBackgroundColor(Qt.GlobalColor.transparent)
            self._saved_messages = []
            
            # 웹뷰 로드 완료 이벤트 연결
            self.web_view.loadFinished.connect(self._on_initial_load)
            
            if self.last_difficulty_message:
                self._saved_messages.append(self.last_difficulty_message)

    def _on_initial_load(self, ok):
        """웹뷰 초기 로드가 완료되었을 때 호출됩니다."""
        if ok:
            logger.debug("WebView initial load completed successfully")
            # 초기 메시지 표시
            welcome_message = """
            <div class="system-message-container">
                <div class="system-message">
                    <p>카드 리뷰를 진행해주세요.</p>
                    <p class="sub-text">답변을 입력하고 Enter 키를 누르거나 Send 버튼을 클릭하세요.</p>
                </div>
                <div class="message-time">{}</div>
            </div>
            """.format(datetime.now().strftime("%p %I:%M"))
            
            self.append_to_chat(welcome_message)
            
            # 마지막 난이도 메시지가 있다면 표시
            if self.last_difficulty_message:
                self.append_to_chat(self.last_difficulty_message)
            
            # 입력 필드에 포커스
            self.input_field.setFocus()
        else:
            logger.error("WebView initial load failed")

    def show_default_message(self):
        """기본 메시지를 표시합니다."""
        pass  # 초기 로드 시 _on_initial_load에서 처리하므로 여기서는 아무것도 하지 않습니다.

    def show_review_message(self):
        """리뷰 메시지를 표시합니다."""
        pass  # 초기 로드 시 _on_initial_load에서 처리하므로 여기서는 아무것도 하지 않습니다.

    def on_show_question(self, card):
        """새로운 질문이 표시될 때 호출됩니다."""
        if self.isVisible():
            current_time = time.time()
            if current_time - self.last_question_time < 0.5:
                logger.debug("Ignoring duplicate question show event")
                return
            self.last_question_time = current_time
            logger.debug(f"""
=== Question Show Event ===
Card ID: {card.id}
Time: {datetime.now().strftime('%H:%M:%S.%f')}
""")
            if not self.last_difficulty_message:
                logger.debug("No difficulty message, showing review message")
                QTimer.singleShot(100, self.show_review_message)
            else:
                logger.debug("Difficulty message exists, skipping review message")

    def on_show_answer(self, card):
        """Called when an answer is shown."""
        if self.isVisible():
            pass

    def on_user_answer_card(self, reviewer, card, ease):
        """Called when the user answers a card."""
        if self.isVisible():
            logger.debug(f"""
=== User Answer Card Event ===
Card ID: {card.id}
Ease: {ease}
Time: {datetime.now().strftime('%H:%M:%S.%f')}
""")
            self.bridge.clear_conversation_history()
            self.clear_chat()
            self.input_field.clear()
            self.input_field.setFocus()
            if self.last_difficulty_message:
                logger.debug("Displaying difficulty message")
                self.append_to_chat(self.last_difficulty_message)
            self.is_initial_answer = True

    def closeEvent(self, event):
        """Clean up when window is closed."""
        reviewer_did_show_question.remove(self.on_show_question)
        reviewer_did_show_answer.remove(self.on_show_answer)
        reviewer_did_answer_card.remove(self.on_user_answer_card)
        super().closeEvent(event)

    def display_loading_animation(self, show):
        """Shows or hides the loading animation in the AI's response."""
        logger.debug(f"""
=== Loading Animation Event ===
Action: {'Show' if show else 'Hide'}
Current State: {mw.state}
Has last_response: {bool(self.last_response)}
Timestamp: {datetime.now().strftime('%H:%M:%S.%f')}
""")
        if show:
            loading_animation_html = f"""
            <div class="system-message-container">
                <div class="system-message">
                    <div class="loading-indicator">
                        <div class="loading-dots">
                            <span></span><span></span><span></span>
                        </div>
                    </div>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            logger.debug("Adding loading animation to chat")
            self.append_to_chat(loading_animation_html)
        else:
            logger.debug("Attempting to remove loading animation")
            script = """
            (function() {
                var loadingIndicators = document.querySelectorAll('.loading-indicator');
                if (loadingIndicators.length > 0) {
                    var lastLoadingIndicator = loadingIndicators[loadingIndicators.length - 1];
                    var messageContainer = lastLoadingIndicator.closest('.system-message-container');
                    if (messageContainer) {
                        messageContainer.parentNode.removeChild(messageContainer);
                        return true;
                    }
                }
                return false;
            })();
            """
            self.web_view.page().runJavaScript(
                script,
                lambda result: logger.debug(f"Loading animation removal {'successful' if result else 'failed'}")
            )

    def update_timer_display(self, elapsed_time):
        """Updates the elapsed time in the UI."""
        self.timer_label.setText(f"Elapsed time: {elapsed_time} seconds")

    def get_recommendation_class(self, recommendation):
        """Returns the CSS class for the recommendation."""
        recommendation_classes = {
            "Again": "recommendation-again",
            "Hard": "recommendation-hard",
            "Good": "recommendation-good",
            "Easy": "recommendation-easy"
        }
        return recommendation_classes.get(recommendation, "")

    def handle_response_error(self, error_message, error_detail):
        """Handles errors during response processing."""
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

    def _preprocess_json_string(self, json_str):
        """JSON 문자열을 파싱하기 전에 전처리합니다."""
        try:
            # ```json과 ``` 태그 제거
            if json_str.startswith('```json'):
                json_str = json_str[7:]
            if json_str.endswith('```'):
                json_str = json_str[:-3]
            
            # 문자열 앞뒤 공백 제거
            json_str = json_str.strip()
            
            return json_str
        except Exception as e:
            logger.error(f"JSON 전처리 중 오류: {str(e)}")
            return json_str

    def display_response(self, response_json):
        """Displays the LLM response in the webview."""
        try:
            self.display_loading_animation(False)
            processed_json = self._preprocess_json_string(response_json)
            
            try:
                response = json.loads(processed_json)
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 정규식으로 JSON 부분 추출 시도
                import re
                json_pattern = r'\{[^}]+\}'
                match = re.search(json_pattern, processed_json)
                if match:
                    response = json.loads(match.group(0))
                else:
                    raise
            
            evaluation = response.get("evaluation", "No evaluation")
            recommendation = response.get("recommendation", "No recommendation")
            answer = response.get("answer", "")
            reference = response.get("reference", "")
            self.last_response = response_json

            # 현재 모델 정보 가져오기
            settings = QSettings("LLM_response_evaluator", "Settings")
            provider_type = settings.value("providerType", "openai").lower()
            if provider_type == "openai":
                model_name = settings.value("modelName", "Unknown Model")
            else:  # gemini
                model_name = settings.value("geminiModel", "Unknown Model")
            
            recommendation_class = self.get_recommendation_class(recommendation)
            html_content = f"""
            <div class="system-message-container">
                <div class="model-info">{model_name}</div>
                <div class="system-message">
                    <h2>평가 결과</h2>
                    <div class="evaluation">{evaluation}</div>
                    <div class="recommendation {recommendation_class}">{recommendation}</div>
                    <div class="answer"><p style="white-space: pre-wrap;">{answer}</p></div>
                    <div class="reference"><p>{reference}</p></div>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(html_content)
        except Exception as e:
            self.handle_response_error("JSON 파싱 오류", str(e))
        except Exception as e:
            self.handle_response_error("예기치 않은 오류", str(e))

    def display_question_response(self, response_json):
        """Displays the response to an additional question."""
        self.display_loading_animation(False)
        try:
            processed_json = self._preprocess_json_string(response_json)
            
            try:
                response = json.loads(processed_json)
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 정규식으로 JSON 부분 추출 시도
                import re
                json_pattern = r'\{[^}]+\}'
                match = re.search(json_pattern, processed_json)
                if match:
                    response = json.loads(match.group(0))
                else:
                    raise

            if "error" in response:
                answer_html = self.get_error_html(response['error'])
            else:
                # 현재 모델 정보 가져오기
                settings = QSettings("LLM_response_evaluator", "Settings")
                provider_type = settings.value("providerType", "openai").lower()
                if provider_type == "openai":
                    model_name = settings.value("modelName", "Unknown Model")
                else:  # gemini
                    model_name = settings.value("geminiModel", "Unknown Model")
                
                recommendation = response.get("recommendation", "")
                recommendation_class = self.get_recommendation_class(recommendation)
                answer = response.get("answer", "답변 없음")
                answer_html = f"""
                <div class="system-message-container">
                    <div class="model-info">{model_name}</div>
                    <div class="system-message">
                        <h3>추가 답변</h3>
                        <span class="{recommendation_class}">{recommendation}</span>
                        <p>{self.markdown_to_html(answer)}</p>
                    </div>
                    <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
                </div>
                """
            self.append_to_chat(answer_html)
        except Exception as e:
            self.handle_response_error("추가 질문 처리 중 오류", str(e))

    def display_joke(self, response_json):
        """Displays the joke in the webview."""
        self.display_loading_animation(False)
        try:
            processed_json = self._preprocess_json_string(response_json)
            
            try:
                response = json.loads(processed_json)
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 정규식으로 JSON 부분 추출 시도
                import re
                json_pattern = r'\{[^}]+\}'
                match = re.search(json_pattern, processed_json)
                if match:
                    response = json.loads(match.group(0))
                else:
                    raise

            if "error" in response:
                joke_html = self.get_error_html(response['error'])
            else:
                # 현재 모델 정보 가져오기
                settings = QSettings("LLM_response_evaluator", "Settings")
                provider_type = settings.value("providerType", "openai").lower()
                if provider_type == "openai":
                    model_name = settings.value("modelName", "Unknown Model")
                else:  # gemini
                    model_name = settings.value("geminiModel", "Unknown Model")
                
                joke = response.get("joke", "농담 생성 실패")
                joke_html = f"""
                <div class="system-message-container">
                    <div class="model-info">{model_name}</div>
                    <div class="system-message">
                        <h3>재미있는 농담 😆</h3>
                        <p>{self.markdown_to_html(joke)}</p>
                    </div>
                    <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
                </div>
                """
            self.append_to_chat(joke_html)
        except Exception as e:
            logger.exception("Error displaying joke: %s", e)
            error_html = f"""
            <div class="system-message-container">
                <div class="system-message">
                    <p style='color: red;'>농담 표시 중 오류가 발생했습니다.</p>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(error_html)

    def display_edit_advice(self, response_json):
        """Displays the card edit advice in the webview."""
        self.display_loading_animation(False)

        try:
            processed_json = self._preprocess_json_string(response_json)
            
            try:
                response = json.loads(processed_json)
            except json.JSONDecodeError:
                # JSON 파싱 실패 시 정규식으로 JSON 부분 추출 시도
                import re
                json_pattern = r'\{[^}]+\}'
                match = re.search(json_pattern, processed_json)
                if match:
                    response = json.loads(match.group(0))
                else:
                    raise

            if "error" in response:
                advice_html = f"""
                <div class="system-message-container">
                    <div class="system-message">
                        <p style='color: red;'>오류: {response['error']}</p>
                    </div>
                    <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
                </div>
                """
            else:
                # 현재 모델 정보 가져오기
                settings = QSettings("LLM_response_evaluator", "Settings")
                provider_type = settings.value("providerType", "openai").lower()
                if provider_type == "openai":
                    model_name = settings.value("modelName", "Unknown Model")
                else:  # gemini
                    model_name = settings.value("geminiModel", "Unknown Model")
                
                edit_advice = response.get("edit_advice", "조언을 생성할 수 없습니다.")
                advice_html = f"""
                <div class="system-message-container">
                    <div class="model-info">{model_name}</div>
                    <div class="system-message">
                        <h3>카드 수정 조언 ✏️</h3>
                        <p>{self.markdown_to_html(edit_advice)}</p>
                    </div>
                    <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
                </div>
                """
            self.append_to_chat(advice_html)

        except Exception as e:
            logger.exception("Error displaying card edit advice: %s", e)
            error_html = f"""
            <div class="system-message-container">
                <div class="system-message">
                    <p style='color: red;'>카드 수정 조언 표시 중 오류가 발생했습니다: {str(e)}</p>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(error_html)

    def markdown_to_html(self, text):
        """Converts Markdown-style emphasis and line breaks to HTML tags."""
        if text is None:
            return ""
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        text = text.replace('\n', '<br>')
        return text

    def send_answer(self):
        """Submit and process user's answer"""
        user_answer = self.input_field.text().strip()
        if user_answer == "":
            return

        # 사용자 메시지 표시
        user_message_html = f"""
        <div class="user-message-container">
            <div class="user-message">
                <p>{user_answer}</p>
            </div>
            <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
        </div>
        """
        self.append_to_chat(user_message_html)

        # AI 응답 로딩 애니메이션 표시
        self.display_loading_animation(True)

        # Save current card ID
        current_card = mw.reviewer.card
        if current_card:
            self.last_evaluated_card_id = current_card.id

        self.bridge.receiveAnswer(user_answer)

        # Switch to the answer screen
        if mw.state == "review":
            mw.reviewer._showAnswer()

        # Clear the input field after submitting the answer
        self.input_field.clear()

    def show_joke(self):
        """Requests and displays a joke."""
        try:
            # 사용자 메시지 표시
            user_message_html = f"""
            <div class="user-message-container">
                <div class="user-message">
                    <p>농담해봐</p>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(user_message_html)

            # AI 응답 로딩 애니메이션 표시
            self.display_loading_animation(True)

            card_content, card_answers, card_ord = self.bridge.get_card_content()
            if card_content and card_answers:
                # 비동기로 처리
                QTimer.singleShot(0, lambda: self.bridge.process_joke_request(card_content, card_answers))
            else:
                raise Exception("카드 정보를 가져올 수 없습니다.")
        except Exception as e:
            logger.exception("Error showing joke: %s", e)
            self.display_loading_animation(False)
            error_html = f"""
            <div class="system-message-container">
                <div class="system-message">
                    <p style='color: red;'>농담 생성 중 오류가 발생했습니다: {str(e)}</p>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(error_html)

    def show_edit_advice(self):
        """Requests and displays card edit advice."""
        try:
            # 사용자 메시지 표시
            user_message_html = f"""
            <div class="user-message-container">
                <div class="user-message">
                    <p>카드 수정 관련 조언해주세요</p>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(user_message_html)

            # AI 응답 로딩 애니메이션 표시
            self.display_loading_animation(True)

            card_content, card_answers, card_ord = self.bridge.get_card_content()
            if card_content and card_answers:
                # 비동기로 처리
                QTimer.singleShot(0, lambda: self.bridge.process_edit_advice_request(card_content, card_answers))
            else:
                raise Exception("카드 정보를 가져올 수 없습니다.")
        except Exception as e:
            logger.exception("Error showing edit advice: %s", e)
            self.display_loading_animation(False)
            error_html = f"""
            <div class="system-message-container">
                <div class="system-message">
                    <p style='color: red;'>카드 수정 조언 생성 중 오류가 발생했습니다: {str(e)}</p>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(error_html)

    def handle_enter_key(self):
        """처리 빈 입력 필드에서 엔터키"""
        if self.is_processing:
            return
            
        user_input = self.input_field.text().strip()
        
        if not user_input and self.last_response:
            # Empty input with last response - follow LLM suggestion
            self.follow_llm_suggestion()
        elif user_input:
            if self.is_initial_answer:
                # First input for this card - handle as answer
                self.is_processing = True
                self.send_answer()
                self.is_initial_answer = False
                self.is_processing = False
            else:
                # Follow-up input - handle as question
                self.process_additional_question(user_input)
                
    def process_additional_question(self, question):
        """Process additional question within the current session"""
        if self.is_processing:
            logger.debug("Skipping question processing - already processing")
            return
            
        self.is_processing = True
        
        try:
            logger.debug(f"""
=== Processing Additional Question ===
Question: {question}
Current Card ID: {self.bridge.current_card_id}
Chat History Length: {len(self.bridge.conversation_history['messages'])}
""")
            
            # Display user question
            user_message_html = f"""
            <div class="user-message-container">
                <div class="user-message">
                    <p>{question}</p>
                </div>
                <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
            </div>
            """
            self.append_to_chat(user_message_html)
            
            # Show loading animation
            self.display_loading_animation(True)
            
            # Clear input field
            self.input_field.clear()
            
            def get_card_info():
                try:
                    return self.bridge.get_card_content()
                except Exception as e:
                    logger.error(f"Error getting card content: {e}")
                    return None, None, None

            # Process in next event loop iteration
            QTimer.singleShot(0, lambda: self._continue_question_processing(question, get_card_info()))
            
        except Exception as e:
            logger.exception("Error in process_additional_question: %s", e)
            self.display_loading_animation(False)
            self._show_error_message("질문 처리 중 오류가 발생했습니다.")
            self.is_processing = False

    def _continue_question_processing(self, question, card_info):
        """Continue processing the question after getting card info"""
        try:
            card_content, card_answers, card_ord = card_info
            if not card_content or not card_answers:
                raise Exception("카드 정보를 가져올 수 없습니다.")

            # Process question in background thread
            thread = threading.Thread(
                target=self._process_question_thread,
                args=(card_content, question, card_answers)
            )
            thread.daemon = True  # Make thread daemonic
            thread.start()

        except Exception as e:
            logger.exception("Error in _continue_question_processing: %s", e)
            self.display_loading_animation(False)
            self._show_error_message(str(e))
            self.is_processing = False

    def _process_question_thread(self, card_content, question, card_answers):
        """Process the question in a background thread"""
        try:
            self.bridge.process_question(card_content, question, card_answers)
        except Exception as e:
            logger.exception("Error in question processing thread: %s", e)
            QMetaObject.invokeMethod(
                self,
                "_show_error_message",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, str(e))
            )
        finally:
            QMetaObject.invokeMethod(
                self,
                "_finish_processing",
                Qt.ConnectionType.QueuedConnection
            )

    @pyqtSlot()
    def _finish_processing(self):
        """Reset processing state"""
        self.is_processing = False
        self.display_loading_animation(False)

    @pyqtSlot(str)
    def _show_error_message(self, message):
        """Show error message in chat"""
        error_html = f"""
        <div class="system-message-container">
            <div class="system-message">
                <p style='color: red;'>{message}</p>
            </div>
            <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
        </div>
        """
        self.append_to_chat(error_html)

    def follow_llm_suggestion(self):
        """LLM의 추천에 따라 난이도 버튼을 클릭하고 UI에 표시합니다."""
        try:
            logger.debug(f"""
=== Follow LLM Suggestion Start ===
Has last_response: {bool(self.last_response)}
Current State: {mw.state}
Timestamp: {datetime.now().strftime('%H:%M:%S.%f')}
""")
            if not self.last_response:
                logger.error("No LLM response available")
                return

            response = json.loads(self.last_response)
            recommendation = response.get("recommendation", "").strip()
            logger.debug(f"LLM recommendation: {recommendation}")

            if recommendation not in ["Again", "Hard", "Good", "Easy"]:
                logger.error(f"Unknown recommendation: {recommendation}")
                return

            difficulty_map = {
                "Again": 1,
                "Hard": 2,
                "Good": 3,
                "Easy": 4
            }
            ease = difficulty_map.get(recommendation)

            if ease is None:
                logger.error(f"Invalid recommendation: {recommendation}")
                return

            if mw.reviewer:
                # 난이도 메시지 생성
                current_time = datetime.now().strftime("%p %I:%M")
                self.last_difficulty_message = f"""
                <div class="system-message-container">
                    <div class="system-message">
                        <p>LLM의 추천에 따라 '{recommendation}' 난이도로 평가했습니다.</p>
                    </div>
                    <div class="message-time">{current_time}</div>
                </div>
                """
                logger.debug(f"""
=== Difficulty Message Set ===
Recommendation: {recommendation}
Message saved for next card
Will be displayed after card transition
""")
                
                # 난이도 선택 실행
                self._execute_answer_card(ease)

        except Exception as e:
            logger.exception(f"Error following LLM suggestion: {e}")

    def _execute_answer_card(self, ease):
        """난이도 선택을 실행합니다."""
        try:
            logger.debug(f"""
=== Execute Answer Card ===
Ease: {ease}
Timestamp: {datetime.now().strftime('%H:%M:%S.%f')}
This will trigger on_user_answer_card
""")
            mw.reviewer._answerCard(ease)
        except Exception as e:
            logger.exception(f"Error calling _answerCard: {e}")

    def show_button_clicked(self, recommendation):
        """Displays which button was clicked in the UI."""
        # 이 메서드는 더 이상 직접적인 메시지 출력을 하지 않음
        # 대신 follow_llm_suggestion에서 last_difficulty_message를 설정하고
        # on_show_question에서 표시하도록 함
        pass

    def append_to_chat(self, html_content):
        """Appends content to the chat container and scrolls to the bottom."""
        logger.debug(f"""
=== Append to Chat (Detailed) ===
Content Type: {self._identify_message_type(html_content)}
Content Preview: {html_content[:100]}...
WebView Ready: {self._is_webview_ready()}
Timestamp: {datetime.now().strftime('%H:%M:%S.%f')}
""")
        
        # 메시지 저장
        if self._identify_message_type(html_content) == "LLM Recommendation":
            self._saved_messages = [html_content]  # 난이도 메시지만 저장
        
        script = f"""
        (function() {{
            var chatContainer = document.querySelector('.chat-container');
            if (chatContainer) {{
                var div = document.createElement('div');
                div.innerHTML = `{html_content}`;
                chatContainer.appendChild(div);
                window.scrollTo(0, document.body.scrollHeight);
                return true;
            }}
            return false;
        }})();
        """
        self.web_view.page().runJavaScript(
            script,
            lambda result: logger.debug(f"Message append result: {'Success' if result else 'Failed'}")
        )

    def _is_webview_ready(self):
        """WebView가 준비되었는지 확인합니다."""
        return hasattr(self.web_view, 'page') and self.web_view.page() is not None

    def _identify_message_type(self, html_content):
        """메시지 타입을 식별합니다."""
        if "LLM의 추천에 따라" in html_content:
            return "LLM Recommendation"
        elif "카드 리뷰를 진행해주세요" in html_content:
            return "Review Prompt"
        elif "user-message" in html_content:
            return "User Message"
        elif "system-message" in html_content:
            return "System Message"
        return "Unknown Message Type"

    def clear_chat(self):
        """채팅 내용을 모두 지우고 새로운 시작 메시지만 표시"""
        caller_info = self._get_caller_info()
        logger.debug(f"""
=== Chat Clear Event ===
Triggered by: {caller_info}
Current State: {mw.state}
Has last_response: {bool(self.last_response)}
Has last_difficulty_message: {bool(self.last_difficulty_message)}
Timestamp: {datetime.now().strftime('%H:%M:%S.%f')}
""")
        script = """
        (function() {
            var chatContainer = document.querySelector('.chat-container');
            if (chatContainer) {
                chatContainer.innerHTML = '';
            }
        })();
        """
        self.web_view.page().runJavaScript(script)

    def _get_caller_info(self):
        """호출 스택 정보를 가져옵니다."""
        import traceback
        stack = traceback.extract_stack()
        # 현재 함수와 _get_caller_info를 제외한 호출자 정보 반환
        caller = stack[-3]  # -3 인덱스가 실제 호출자
        return f"{caller.filename.split('/')[-1]}:{caller.lineno} in {caller.name}"

    def on_webview_loaded(self):
        """웹뷰 로드 완료 시 호출되는 핸들러"""
        logger.debug(f"""
=== WebView Load Complete (Detailed) ===
Current State: {mw.state}
Is Initial Load: {not self.is_webview_initialized}
Has Difficulty Message: {bool(self.last_difficulty_message)}
Timestamp: {datetime.now().strftime('%H:%M:%S.%f')}
""")
        
        if not self.is_webview_initialized:
            self.is_webview_initialized = True
            if mw.state == "review":
                logger.debug("Initial webview load - showing review message")
                self.show_review_message()
            else:
                logger.debug("Initial webview load - showing default message")
                self.show_default_message()
        else:
            # WebView 재로드 시 마지막 난이도 메시지 복복원
            logger.debug("Restoring messages after webview reload")
            if self.last_difficulty_message:
                logger.debug("Restoring difficulty message")
                self.append_to_chat(self.last_difficulty_message)

    def _get_chat_content(self):
        """현재 채팅창의 내용을 가져옵니다."""
        script = """
        (function() {
            var chatContainer = document.querySelector('.chat-container');
            return chatContainer ? chatContainer.innerHTML : '';
        })();
        """
        self.web_view.page().runJavaScript(
            script,
            lambda result: logger.debug(f"Current chat content: {result[:100]}...")  # 처음 100자만 로깅
        )
