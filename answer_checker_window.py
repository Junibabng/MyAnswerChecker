from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QHBoxLayout, QInputDialog, QDoubleSpinBox, QSpinBox, QComboBox, QGroupBox, QWidget, QSizePolicy
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QTimer, Qt, QThread, QMetaObject, Q_ARG, pyqtSlot, pyqtSignal
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
import uuid  # UUID 추가
from .message import MessageManager, Message, MessageType
from typing import Optional, Any, Dict, List
from .settings_manager import settings_manager
from .auto_difficulty import extract_difficulty
from anki.cards import Card
from aqt.reviewer import Reviewer

logger = logging.getLogger(__name__)

class AnswerCheckerWindow(QDialog):
    # 시그널 정의 추가
    message_rendered = pyqtSignal(str)  # 메시지 렌더링 완료 시그널
    
    def __init__(self, bridge: Any, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.bridge = bridge
        self.setWindowTitle("MyAnswerChecker")
        self.setGeometry(300, 300, 800, 600)
        self.layout = QVBoxLayout(self)
        
        # 최소 창 크기 설정
        self.setMinimumSize(400, 300)
        
        # 타이머 라벨
        self.timer_label = QLabel("Elapsed time: 0 seconds")
        self.timer_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.layout.addWidget(self.timer_label)

        # WebView 설정
        self.web_view = QWebEngineView()
        self.web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.layout.addWidget(self.web_view)

        # 입력 필드와 버튼을 포함하는 컨테이너 위젯
        input_container = QWidget()
        input_container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        self.input_field = QLineEdit()
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_answer)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.send_button)
        
        self.layout.addWidget(input_container)

        self.last_response = None
        self.is_webview_initialized = False
        self.is_webview_loading = False
        self.initialization_lock = threading.Lock()
        self.initialization_event = threading.Event()
        self._saved_messages = []  # 저장된 메시지 초기화
        self.last_difficulty_message = None
        self.last_question_time = 0
        self.message_containers = {}
        self.message_queue = []  # 메시지 큐 추가
        self.is_webview_ready = False  # WebView 준비 상태 추가
        
        # 가비지 컬렉션 타이머 설정
        self.gc_timer = QTimer(self)
        self.gc_timer.timeout.connect(self.clear_message_containers_periodically)
        self.gc_timer.start(300000)  # 5분마다 실행
        
        self.bridge.sendResponse.connect(self.display_response)
        self.bridge.sendQuestionResponse.connect(self.display_question_response)
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
            height: 100vh;
            box-sizing: border-box;
        }

        .chat-container {
            flex: 1 1 auto;
            overflow-y: scroll;
            padding: 10px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            max-width: 800px;
            width: 100%;
            margin: 0 auto;
            scroll-behavior: smooth;
            box-sizing: border-box;
            min-height: 0;
        }

        .chat-container::-webkit-scrollbar {
            width: 8px;
        }

        .chat-container::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.1);
            border-radius: 4px;
        }

        .chat-container::-webkit-scrollbar-thumb {
            background: rgba(0, 0, 0, 0.2);
            border-radius: 4px;
        }

        .chat-container::-webkit-scrollbar-thumb:hover {
            background: rgba(0, 0, 0, 0.3);
        }

        .message-container {
            width: 100%;
            max-width: 100%;
            word-wrap: break-word;
            margin: 8px 0;
        }

        .message {
            position: relative;
            padding: 14px 18px;
            border-radius: 12px;
            max-width: 85%;
            background-color: #ffffff;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            margin-left: 16px;
        }

        .user-message {
            background-color: #ffeb33;
            margin-left: auto;
            margin-right: 16px;
        }

        .welcome-message {
            background-color: #ffffff;
        }

        .welcome-message h3 {
            margin: 0 0 8px 0;
            color: #333;
            font-size: 16px;
        }

        .question-message {
            background-color: #ffffff;
        }

        .question-message h3 {
            margin: 0 0 8px 0;
            color: #333;
            font-size: 15px;
        }

        .difficulty-recommendation-message {
            background-color: #ffffff;
        }

        .model-info {
            font-size: 12px;
            color: #666;
            margin-bottom: 4px;
            margin-left: 16px;
        }

        .message-time {
            font-size: 11px;
            color: #8e8e8e;
            margin-top: 4px;
            margin-left: 16px;
        }

        .user-message-container .message-time {
            margin-right: 16px;
            text-align: right;
        }

        .recommendation {
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: bold;
            color: white;
        }

        .recommendation-again {
            background-color: #ff4444;  /* 빨간색 */
            color: white;
            border-radius: 4px;
            padding: 4px 8px;
            display: inline-block;
        }

        .recommendation-hard {
            background-color: #ff9933;  /* 주황색 */
            color: white;
            border-radius: 4px;
            padding: 4px 8px;
            display: inline-block;
        }

        .recommendation-good {
            background-color: #44cc44;  /* 초록색 */
            color: white;
            border-radius: 4px;
            padding: 4px 8px;
            display: inline-block;
        }

        .recommendation-easy {
            background-color: #3399ff;  /* 파란색 */
            color: white;
            border-radius: 4px;
            padding: 4px 8px;
            display: inline-block;
        }

        /* 난이도 메시지 컨테이너 스타일 */
        .difficulty-recommendation-message {
            background-color: #ffffff;
            padding: 12px 16px;
            border-radius: 12px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
            margin: 8px 0;
        }

        .error-message {
            color: #e74c3c;
            margin-bottom: 8px;
        }

        .help-text {
            color: #666;
            font-size: 0.9em;
        }

        /* 로딩 애니메이션 스타일 */
        .loading-spinner {
            padding: 10px;
            text-align: center;
        }
        
        .typing-indicator {
            display: inline-flex;
            align-items: center;
            margin-bottom: 8px;
        }
        
        .typing-indicator span {
            height: 8px;
            width: 8px;
            background: #90949c;
            border-radius: 50%;
            margin: 0 2px;
            display: inline-block;
            animation: bounce 1.3s linear infinite;
        }
        
        .typing-indicator span:nth-child(2) { animation-delay: 0.15s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.3s; }
        
        .loading-text {
            color: #90949c;
            font-size: 0.9em;
            margin-top: 4px;
        }
        
        @keyframes bounce {
            0%, 60%, 100% { transform: translateY(0); }
            30% { transform: translateY(-4px); }
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
        reviewer_did_show_question.append(self.show_question_)
        reviewer_did_show_answer.append(self.show_answer_)
        reviewer_did_answer_card.append(self.user_answer_card_)
        gui_hooks.reviewer_did_show_question.remove(self.prepare_card_)
        gui_hooks.reviewer_did_show_question.append(self.prepare_card_)

        self.is_initial_answer = True
        self.is_processing = False
        self.message_manager = MessageManager()
        
        # 웰컴 메시지 표시 여부를 추적하는 플래그 추가
        self.welcome_message_shown = False

        # 시그널 연결
        self.message_rendered.connect(self._on_message_rendered)

    def initialize_webview(self) -> None:
        """WebView 초기화 및 설정"""
        try:
            with self.initialization_lock:
                if self.is_webview_loading or self.is_webview_initialized:
                    return
                
                self.is_webview_loading = True
                
            channel = QWebChannel(self.web_view)
            self.web_view.page().setWebChannel(channel)
            channel.registerObject("bridge", self.bridge)
            
            self.web_view.loadFinished.connect(self._on_webview_load_finished)
            self.web_view.setHtml(self.default_html)
            
            logger.info("WebView 초기화 시작됨")
        except Exception as e:
            logger.error(f"WebView 초기화 중 오류 발생: {str(e)}")
            self.is_webview_loading = False
            self.initialization_event.clear()
            raise

    def _check_webview_state(self) -> bool:
        """WebView의 상태를 확인하고 필요한 경우 초기화를 시도합니다."""
        try:
            with self.initialization_lock:
                if not self.is_webview_initialized and not self.is_webview_loading:
                    logger.debug("WebView not initialized, starting initialization")
                    self.initialize_webview()
                    return self.wait_for_webview_ready()
                elif self.is_webview_loading:
                    logger.debug("WebView is currently loading")
                    return self.wait_for_webview_ready()
                return True
        except Exception as e:
            logger.error(f"WebView 상태 확인 중 오류: {str(e)}")
            return False

    def _on_webview_load_finished(self, ok):
        """WebView 로드 완료 핸들러"""
        try:
            if ok:
                with self.initialization_lock:
                    self.is_webview_initialized = True
                    self.is_webview_loading = False
                    self.is_webview_ready = True
                    self.initialization_event.set()
                logger.info("WebView 초기화 완료")
                
                # 큐에 있는 메시지들 처리
                self._process_message_queue()
                
                # 웰컴 메시지는 첫 로드에만 표시
                if not self.welcome_message_shown:
                    welcome_message = self.message_manager.create_welcome_message()
                    self.append_to_chat(welcome_message)
                    self.welcome_message_shown = True
                
                # 저장된 메시지 처리
                self._process_saved_messages()
                
                # 입력 필드에 포커스
                self.input_field.setFocus()
            else:
                logger.error("WebView 로드 실패")
                self.is_webview_loading = False
                self.initialization_event.clear()
                self.show_error_message("WebView 초기화에 실패했습니다.")
        except Exception as e:
            logger.error(f"WebView 로드 완료 처리 중 오류: {str(e)}")
            self.is_webview_loading = False
            self.initialization_event.clear()
            self.show_error_message(f"WebView 초기화 중 오류가 발생했습니다: {str(e)}")

    def _process_message_queue(self):
        """큐에 있는 메시지들을 처리"""
        while self.message_queue:
            message = self.message_queue.pop(0)
            self.append_to_chat(message)

    def _is_webview_ready(self):
        """WebView가 사용 가능한 상태인지 확인"""
        return self.is_webview_initialized and not self.is_webview_loading

    def wait_for_webview_ready(self, timeout=10):
        """WebView 초기화 완료를 기다림"""
        return self.initialization_event.wait(timeout)

    def append_to_chat(self, message: Message):
        """채팅창에 메시지를 추가"""
        if not self.is_webview_ready:
            logger.debug("WebView not ready, queueing message")
            self.message_queue.append(message)
            return
        
        html_content = message.to_html()
        script = """
        (function() {
            var chatContainer = document.querySelector('.chat-container');
            if (chatContainer) {
                var div = document.createElement('div');
                div.innerHTML = `%s`;
                chatContainer.appendChild(div);
                
                // 스크롤 애니메이션 추가
                chatContainer.scrollTo({
                    top: chatContainer.scrollHeight,
                    behavior: 'smooth'
                });
                
                // 메시지 ID를 반환하여 렌더링 완료를 추적
                return div.firstChild.id || 'message-' + Date.now();
            }
            return null;
        })();
        """ % html_content
        
        self.web_view.page().runJavaScript(
            script,
            lambda result: self._handle_message_rendered(result, message)
        )

    def _handle_message_rendered(self, message_id: str, message: Message):
        """메시지 렌더링 완료 처리"""
        if message_id:
            logger.debug(f"Message rendered with ID: {message_id}")
            self.message_rendered.emit(message_id)
        else:
            logger.error("Failed to render message")

    @pyqtSlot(str)
    def _on_message_rendered(self, message_id: str):
        """메시지 렌더링 완료 시 호출되는 슬롯"""
        logger.debug(f"Message render completed: {message_id}")
        if hasattr(self, '_pending_loading_animation') and self._pending_loading_animation:
            self.display_loading_animation(True)
            self._pending_loading_animation = False

    def _process_saved_messages(self):
        """저장된 메시지들을 처리합니다."""
        if not self._saved_messages:
            return

        logger.debug(f"Processing {len(self._saved_messages)} saved messages")
        
        for message_data in self._saved_messages:
            if isinstance(message_data, dict):
                msg_type = message_data.get("type")
                content = message_data.get("content")
                
                if msg_type == "response":
                    self.display_response(content)
                elif msg_type == "question":
                    self.display_question_response(content)
            elif isinstance(message_data, Message):
                # Message 객체는 직접 표시
                self.append_to_chat(message_data)
        
        # 처리 완료된 메시지 초기화
        self._saved_messages = []

    def show_default_message(self):
        """기본 메시지를 표시합니다."""
        pass  # 초기 로드 시 _on_initial_load에서 처리하므로 여기서는 아무것도 하지 않습니다.

    def show_review_message(self):
        """리뷰 메시지를 표시합니다."""
        # 마지막 LLM 응답에서 난이도 추천 추출
        last_response = self.bridge.get_last_response()
        if last_response:
            recommendation = self.bridge.extract_difficulty(last_response)
            if recommendation:
                review_msg = self.message_manager.create_review_message(recommendation)
                self.append_to_chat(review_msg)
            else:
                logger.error("난이도 추천을 찾을 수 없습니다.")
        else:
            logger.error("LLM 응답을 찾을 수 없습니다.")

    def show_question_(self, card: Card) -> None:
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
            # 중복 이벤트 체크만 수행하고 실제 카드 내용 처리는 on_prepare_card에서 수행

    def show_answer_(self, card: Card) -> None:
        """Called when an answer is shown."""
        if self.isVisible():
            pass

    def user_answer_card_(self, reviewer: Reviewer, card: Card, ease: int) -> None:
        """카드 답변 시 호출되는 핸들러"""
        if self.isVisible():
            logger.debug(f"""
=== User Answer Card Event ===
Card ID: {card.id}
Ease: {ease}
Time: {datetime.now().strftime('%H:%M:%S.%f')}
""")
            if self.last_difficulty_message:
                self.message_queue = [self.last_difficulty_message]  # 큐를 새로 생성하고 마지막 메시지만 포함
                logger.debug("Difficulty message set for next card")
            # Clear conversation only if this is the initial answer
            if self.is_initial_answer:
                self.bridge.clear_conversation_history()
                self.clear_chat()
            # Always clear the input field and set focus
            self.input_field.clear()
            self.input_field.setFocus()
            # Reset is_initial_answer to True for next card if it was the initial answer, else keep the conversation
            self.is_initial_answer = True

    def closeEvent(self, event):
        """Clean up when window is closed."""
        reviewer_did_show_question.remove(self.show_question_)
        reviewer_did_show_answer.remove(self.show_answer_)
        reviewer_did_answer_card.remove(self.user_answer_card_)
        self.bridge.set_answer_checker_window(None)  # Bridge의 window 참조 제거
        super().closeEvent(event)

    def display_loading_animation(self, show):
        """Shows or hides the loading animation in the AI's response."""
        if not self.is_webview_ready:
            logger.debug("WebView not ready, skipping loading animation")
            return

        script = """
        (function() {
            var chatContainer = document.querySelector('.chat-container');
            var loadingId = 'loading-animation';
            var existingLoader = document.getElementById(loadingId);
            
            if (%s) {
                if (!existingLoader) {
                    var loaderHtml = `
                        <div id="${loadingId}" class="message-container">
                            <div class="message">
                                <div class="loading-spinner">
                                    <div class="typing-indicator">
                                        <span></span>
                                        <span></span>
                                        <span></span>
                                    </div>
                                    <div class="loading-text">답변을 생성하고 있습니다...</div>
                                </div>
                            </div>
                        </div>
                    `;
                    var div = document.createElement('div');
                    div.innerHTML = loaderHtml;
                    chatContainer.appendChild(div);
                    chatContainer.scrollTo({
                        top: chatContainer.scrollHeight,
                        behavior: 'smooth'
                    });
                }
            } else if (existingLoader) {
                existingLoader.remove();
            }
            return true;
        })();
        """ % ('true' if show else 'false')
        
        self.web_view.page().runJavaScript(
            script,
            lambda result: logger.debug(f"Loading animation {'shown' if show else 'hidden'}: {result}")
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
        error_msg = self.message_manager.create_error_message(
            f"{error_message}: {error_detail}"
        )
        self.append_to_chat(error_msg)
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
        """Displays the LLM response in the webview as plain text."""
        if not self._check_webview_state():
            logger.debug("Queuing response for later display")
            self._saved_messages.append({"type": "response", "content": response_json})
            return

        try:
            self.display_loading_animation(False)
            
            # JSON 객체 찾기
            json_match = re.search(r'({[^{}]*"recommendation"[^{}]*})', response_json)
            if not json_match:
                logger.error("No JSON object found in response")
                self.show_error_message("응답 형식이 올바르지 않습니다.")
                return

            try:
                json_str = json_match.group(1)
                parsed_json = json.loads(json_str)
            except json.JSONDecodeError:
                logger.error("Invalid JSON format")
                self.show_error_message("응답을 처리할 수 없습니다.")
                return

            # 응답 텍스트에서 JSON 부분 제거
            display_text = response_json.replace(json_str, "").strip()
            
            # JSON 부분이 제거된 텍스트가 있으면 마크다운 변환
            if display_text:
                processed_content = self.markdown_to_html(display_text)
            else:
                processed_content = "평가가 완료되었습니다."

            self.last_response = response_json

            settings = settings_manager.load_settings()
            provider_type = settings.get("providerType", "openai").lower()
            if provider_type == "openai":
                model_name = settings.get("modelName", "Unknown Model")
            else:
                model_name = settings.get("geminiModel", "Unknown Model")

            response_message = self.message_manager.create_llm_message(
                content=processed_content,
                model_name=model_name
            )
            self.append_to_chat(response_message)
        except Exception as e:
            self.handle_response_error("Display response error", str(e))

    def display_question_response(self, response_text):
        """Displays the response to an additional question as plain text."""
        if not self._check_webview_state():
            logger.debug("Queuing question response for later display")
            self._saved_messages.append({"type": "question", "content": response_text})
            return

        self.display_loading_animation(False)
        try:
            # Apply markdown conversion to preserve line breaks
            processed_content = self.markdown_to_html(response_text)
            self.last_response = response_text

            settings = settings_manager.load_settings()
            provider_type = settings.get("providerType", "openai").lower()
            if provider_type == "openai":
                model_name = settings.get("modelName", "Unknown Model")
            else:
                model_name = settings.get("geminiModel", "Unknown Model")

            answer_message = self.message_manager.create_llm_message(
                content=processed_content,
                model_name=model_name
            )
            self.append_to_chat(answer_message)
        except Exception as e:
            self.handle_response_error("Display question response error", str(e))

    def markdown_to_html(self, text):
        """Converts Markdown-style emphasis and line breaks to HTML tags."""
        if text is None:
            return ""
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        text = text.replace('\n', '<br>')
        return text

    def send_answer(self):
        """Submit and process user's answer"""
        if not self._check_webview_state():
            self.show_error_message("답변 확인 창을 초기화 중입니다. 잠시만 기다려주세요...")
            return

        user_answer = self.input_field.text().strip()
        if user_answer == "":
            return

        # 로딩 애니메이션 표시 대기 설정
        self._pending_loading_animation = True

        # 사용자 메시지를 생성하고 표시
        user_message = Message(
            content=user_answer,
            message_type=MessageType.USER
        )
        self.append_to_chat(user_message)

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
            
            # 로딩 애니메이션 표시 대기 설정
            self._pending_loading_animation = True
            
            # Display user question as Message object
            user_message = Message(
                content=question,
                message_type=MessageType.USER
            )
            self.append_to_chat(user_message)
            
            # Clear input field
            self.input_field.clear()
            
            # Get card info in background
            QTimer.singleShot(0, lambda: self._continue_question_processing(question, self.bridge.get_card_content()))
            
        except Exception as e:
            logger.exception("Error in process_additional_question: %s", e)
            self.display_loading_animation(False)
            self.show_error_message("질문 처리 중 오류가 발생했습니다.")
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
            self.show_error_message(str(e))
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

    @pyqtSlot(str)
    def _show_error_message(self, message):
        """Show error message in chat"""
        error_message = self.message_manager.create_error_message(message)
        self.append_to_chat(error_message)

    def follow_llm_suggestion(self) -> None:
        """LLM의 난이도 추천에 따라 자동으로 난이도를 평가합니다."""
        try:
            logging.debug("난이도 평가 시작")
            
            # 마지막 LLM 응답 확인
            last_response = self.bridge.get_last_response()
            if not last_response:
                logging.error("난이도 평가를 위한 LLM 응답이 없습니다.")
                self._show_error_message("난이도 평가를 위한 LLM 응답이 없습니다.")
                return

            # 난이도 추천 추출
            recommendation = self.bridge.extract_difficulty(last_response)
            if not recommendation:
                logging.error("유효한 난이도 평가 결과를 찾을 수 없습니다.")
                self._show_error_message("유효한 난이도 평가 결과를 찾을 수 없습니다.")
                return

            # 유효한 난이도 값 확인
            valid_recommendations = ["Again", "Hard", "Good", "Easy"]
            if recommendation not in valid_recommendations:
                logging.error(f"잘못된 난이도 값: {recommendation}")
                return

            logging.debug(f"난이도 평가 실행: {recommendation}")
            
            # 현재 리뷰어 가져오기
            reviewer = mw.reviewer
            if not reviewer:
                logging.error("리뷰어를 찾을 수 없습니다.")
                return

            # 난이도에 따른 ease 값 매핑
            ease_mapping = {
                "Again": 1,
                "Hard": 2,
                "Good": 3,
                "Easy": 4
            }

            # 난이도 평가 실행
            ease = ease_mapping.get(recommendation)
            if ease:
                reviewer._answerCard(ease)
                logging.info(f"난이도 평가 완료: {recommendation} (ease: {ease})")
            
        except Exception as e:
            error_msg = f"난이도 평가 중 오류가 발생했습니다: {str(e)}"
            logging.error(error_msg)
            self._show_error_message(error_msg)

    def show_button_clicked(self, recommendation):
        """Displays which button was clicked in the UI."""
        # 이 메서드는 더 이상 직접적인 메시지 출력을 하지 않음
        # 대신 follow_llm_suggestion에서 last_difficulty_message를 설정하고
        # on_show_question에서 표시하도록 함
        pass

    def show_error_message(self, error_content: str, help_text: Optional[str] = None):
        """에러 메시지를 표시합니다."""
        message = self.message_manager.create_error_message(error_content, help_text)
        self.append_to_chat(message)

    def show_system_message(self, content: str):
        """시스템 메시지를 표시합니다."""
        message = self.message_manager.create_system_message(content)
        self.append_to_chat(message)

    def show_llm_message(self, content: str, model_name: str):
        """LLM 메시지를 표시합니다."""
        message = self.message_manager.create_llm_message(content, model_name)
        self.append_to_chat(message)

    def clear_chat(self):
        """채팅 내용을 모두 지우고 새로운 시작 메시지만 표시"""
        if not self.is_webview_ready:
            logger.debug("WebView not ready, skipping clear_chat")
            return
        
        self.web_view.page().runJavaScript("""
            document.querySelector('.chat-container').innerHTML = '';
        """)
        
        # 메시지 큐 초기화 (마지막 난이도 메시지만 유지)
        if self.last_difficulty_message:
            self.message_queue = [self.last_difficulty_message]
        else:
            self.message_queue = []
        
        # 웰컴 메시지는 첫 리뷰에만 표시
        if not self.welcome_message_shown:
            welcome_message = self.message_manager.create_welcome_message()
            self.append_to_chat(welcome_message)
            self.welcome_message_shown = True
        
        # 난이도 메시지가 있으면 추가 (큐에서 하나만 처리)
        if self.message_queue:
            self.append_to_chat(self.message_queue[0])

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

    def create_message_container(self, request_id=None):
        """메시지 컨테이너를 생성하고 초기화합니다."""
        # request_id가 없는 경우 UUID 생성
        if request_id is None:
            request_id = str(uuid.uuid4())
            
        if request_id in self.message_containers:
            logger.debug(f"Container already exists for request_id: {request_id}, reusing existing container")
            # 기존 컨테이너가 완료 상태인 경우 새로운 컨테이너로 교체
            if self.message_containers[request_id]['is_complete']:
                logger.debug(f"Existing container is complete, creating new container for request_id: {request_id}")
                self.message_containers[request_id] = {
                    'content': '',
                    'created_at': datetime.now(),
                    'is_complete': False,
                    'container_id': f"message-container-{request_id}"  # DOM에서 사용할 고유 ID
                }
        else:
            logger.debug(f"Creating new container with UUID: {request_id}")
            self.message_containers[request_id] = {
                'content': '',
                'created_at': datetime.now(),
                'is_complete': False,
                'container_id': f"message-container-{request_id}"  # DOM에서 사용할 고유 ID
            }
        
        return self.message_containers[request_id]

    def clear_message_containers_periodically(self):
        """30분 이상 경과된 메시지 컨테이너를 정리합니다."""
        current_time = datetime.now()
        containers_to_remove = []
        
        for request_id, container in self.message_containers.items():
            time_diff = current_time - container['created_at']
            if time_diff.total_seconds() > 1800:  # 30분 (1800초)
                containers_to_remove.append(request_id)
        
        for request_id in containers_to_remove:
            del self.message_containers[request_id]
            logger.info(f"Removed old message container with request_id: {request_id}")

    def prepare_card_(self, card: Card) -> None:
        """카드 준비 시 호출되는 핸들러"""
        if not self.isVisible():
            return
            
        try:
            logger.debug("=== Preparing card ===")
            
            # 이전 카드와 동일한지 확인
            if hasattr(self, 'last_card_id') and self.last_card_id == card.id:
                logger.debug("Skipping duplicate card preparation")
                return
                
            self.last_card_id = card.id
            
            # WebView 상태 확인
            if not self._check_webview_state():
                logger.debug("WebView not ready, scheduling delayed preparation")
                QTimer.singleShot(500, lambda: self.prepare_card_(card))
                return
                
            card_content, _, _ = self.bridge.get_card_content()
            if not card_content:
                logger.error("Failed to get card content")
                return
                
            logger.debug(f"Card content: {card_content[:50]}...")
            
            question_message = self.message_manager.create_question_message(
                content=self.markdown_to_html(card_content)
            )
            logger.debug(f"Generated message HTML: {question_message.to_html()[:200]}...")
            
            # 채팅창 초기화 및 메시지 표시
            def show_messages():
                self.clear_chat()
                self.append_to_chat(question_message)
                
                # 이전 난이도 메시지가 있으면 표시
                if self.last_difficulty_message:
                    QTimer.singleShot(100, lambda: self.append_to_chat(self.last_difficulty_message))
                
                # 입력 필드에 포커스
                self.input_field.setFocus()
            
            # 적절한 딜레이 후 메시지 표시
            QTimer.singleShot(300, show_messages)
            
        except Exception as e:
            logger.exception("Error in prepare_card_: %s", str(e))
            self.show_error_message(f"카드 로드 실패: {str(e)}")

    def process_answer(self, answer_text: str) -> None:
        """사용자 답변을 처리하고 LLM에 전송합니다."""
        try:
            if not answer_text.strip():
                return

            # 답변 시간 기록
            self.bridge.stop_timer()
            elapsed_time = self.bridge.get_elapsed_time()
            
            # 사용자 답변 메시지 생성 및 표시
            user_message = self.message_manager.create_user_message(content=answer_text)
            self.append_to_chat(user_message)
            
            # 로딩 애니메이션 표시
            self.display_loading_animation(True)
            
            # LLM 응답 처리
            card_content, correct_answers, card_ord = self.bridge.get_card_content()
            if not card_content or not correct_answers:
                self.show_error_message("카드 내용을 가져올 수 없습니다.")
                self.display_loading_animation(False)
                return

            # LLM에 요청 보내기
            self.bridge.llm_data = {
                "card_content": card_content,
                "user_answer": answer_text,
                "correct_answers": correct_answers,
                "elapsed_time": elapsed_time,
                "card_ord": card_ord
            }
            
            # 답변 처리 시작
            thread = threading.Thread(target=self.bridge.process_answer)
            thread.start()

        except Exception as e:
            error_msg = f"답변 처리 중 오류 발생: {str(e)}"
            logging.error(error_msg)
            self.show_error_message(error_msg)
            self.display_loading_animation(False)
