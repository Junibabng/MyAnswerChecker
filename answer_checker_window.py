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
import uuid  # UUID 추가
from .message import MessageManager, Message, MessageType
from typing import Optional

logger = logging.getLogger(__name__)

class AnswerCheckerWindow(QDialog):
    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setWindowTitle("MyAnswerChecker")
        self.setGeometry(300, 300, 800, 600)
        self.layout = QVBoxLayout(self)
        self.last_response = None
        self.is_webview_initialized = False
        self.is_webview_loading = False
        self.initialization_lock = threading.Lock()
        self.initialization_event = threading.Event()
        self._saved_messages = []  # 저장된 메시지 초기화
        self.last_difficulty_message = None
        self.last_question_time = 0
        self.message_containers = {}
        
        # 가비지 컬렉션 타이머 설정
        self.gc_timer = QTimer(self)
        self.gc_timer.timeout.connect(self.clear_message_containers_periodically)
        self.gc_timer.start(300000)  # 5분마다 실행
        
        self.input_label = QLabel("Enter your answer:")
        self.input_field = QLineEdit()
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_answer)
        
        self.timer_label = QLabel("Elapsed time: 0 seconds") 
        self.layout.addWidget(self.timer_label)

        self.web_view = QWebEngineView()
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.web_view)

        self.layout.addWidget(self.scroll_area)

        # 버튼 레이아웃
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.send_button)
        
        # 입력 필드와 버튼을 포함하는 레이아웃
        input_layout = QHBoxLayout()
        input_layout.addWidget(self.input_field)
        input_layout.addLayout(button_layout)
        self.layout.addLayout(input_layout)

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
            align-items: stretch;
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
            min-width: 200px;
            max-width: 75%;
            word-wrap: break-word;
            font-size: 14px;
            line-height: 1.4;
            align-self: flex-start;
        }

        .user-message-container {
            align-items: flex-end;
            align-self: flex-end;
            width: 100%;
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
            min-width: 200px;
            max-width: 75%;
        }

        .system-message-container {
            align-items: flex-start;
            align-self: flex-start;
            width: 100%;
            display: flex;
            flex-direction: column;
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
            min-width: 200px;
            width: auto;
            max-width: 75%;
            align-self: flex-start;
        }

        .system-message h3 {
            margin: 0 0 8px 0;
            font-size: 15px;
            color: #333;
            white-space: normal;
        }

        .system-message p {
            margin: 0 0 8px 0;
            line-height: 1.5;
            white-space: normal;
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

        /* 웰컴 메시지 스타일 추가 */
        .welcome-message {
            background-color: #f8f9fa;
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            text-align: center;
        }
        .welcome-message h3 {
            color: #2c3e50;
            margin-bottom: 12px;
        }

        /* 시스템 메시지 컨테이너 스타일 확인 */
        .system-message-container.question {
            border-left: 4px solid #3498db !important;
            background-color: #f8f9fa !important;
            margin: 15px 0 !important;
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
        gui_hooks.reviewer_did_show_question.remove(self.on_prepare_card)
        gui_hooks.reviewer_did_show_question.append(self.on_prepare_card)

        self.is_initial_answer = True
        self.is_processing = False
        self.message_manager = MessageManager()

    def initialize_webview(self):
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

    def _check_webview_state(self):
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
                    self.initialization_event.set()
                logger.info("WebView 초기화 완료")
                
                # 웰컴 메시지 표시 (기존 코드 대체)
                welcome_message = self.message_manager.create_welcome_message()
                self.append_to_chat(welcome_message)
                
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

    def _is_webview_ready(self):
        """WebView가 사용 가능한 상태인지 확인"""
        return self.is_webview_initialized and not self.is_webview_loading

    def wait_for_webview_ready(self, timeout=10):
        """WebView 초기화 완료를 기다림"""
        return self.initialization_event.wait(timeout)

    def append_to_chat(self, message: Message):
        """채팅창에 메시지를 추가합니다."""
        if not self._check_webview_state():
            return
            
        html_content = message.to_html()
        script = """
        (function() {
            var chatContainer = document.querySelector('.chat-container');
            if (chatContainer) {
                var div = document.createElement('div');
                div.innerHTML = `%s`;
                chatContainer.appendChild(div);
                window.scrollTo(0, document.body.scrollHeight);
                return true;
            }
            return false;
        })();
        """ % html_content
        
        self.web_view.page().runJavaScript(
            script,
            lambda result: logger.debug(f"Message append result: {'Success' if result else 'Failed'}")
        )

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
        review_msg = self.message_manager.create_review_message("기본 권장값")
        self.append_to_chat(review_msg)

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
            # 중복 이벤트 체크만 수행하고 실제 카드 내용 처리는 on_prepare_card에서 수행

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
        if not self._check_webview_state():
            return

        logger.debug(f"""
=== Loading Animation Event ===
Action: {'Show' if show else 'Hide'}
Current State: {mw.state}
Has last_response: {bool(self.last_response)}
Timestamp: {datetime.now().strftime('%H:%M:%S.%f')}
""")
        if show:
            loading_message = self.message_manager.create_system_message(
                '<div class="loading-indicator"><div class="loading-dots">'
                '<span></span><span></span><span></span></div></div>'
            )
            self.append_to_chat(loading_message)
        else:
            # 로딩 애니메이션 제거 스크립트
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
        """Displays the LLM response in the webview."""
        if not self._check_webview_state():
            logger.debug("Queuing response for later display")
            self._saved_messages.append({"type": "response", "content": response_json})
            return

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
            
            # Message 객체 생성
            response_message = self.message_manager.create_llm_message(
                content=f"""
                <h2>평가 결과</h2>
                <div class="evaluation">{evaluation}</div>
                <div class="recommendation {self.get_recommendation_class(recommendation)}">{recommendation}</div>
                <div class="answer"><p style="white-space: pre-wrap;">{answer}</p></div>
                <div class="reference"><p>{reference}</p></div>
                """,
                model_name=model_name
            )
            self.append_to_chat(response_message)
            
        except Exception as e:
            self.handle_response_error("JSON 파싱 오류", str(e))

    def display_question_response(self, response_json):
        """Displays the response to an additional question."""
        if not self._check_webview_state():
            logger.debug("Queuing question response for later display")
            self._saved_messages.append({"type": "question", "content": response_json})
            return

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
                error_message = self.message_manager.create_error_message(response['error'])
                self.append_to_chat(error_message)
            else:
                # 현재 모델 정보 가져오기
                settings = QSettings("LLM_response_evaluator", "Settings")
                provider_type = settings.value("providerType", "openai").lower()
                if provider_type == "openai":
                    model_name = settings.value("modelName", "Unknown Model")
                else:  # gemini
                    model_name = settings.value("geminiModel", "Unknown Model")
                
                recommendation = response.get("recommendation", "")
                answer = response.get("answer", "답변 없음")
                
                # Message 객체 생성
                answer_message = self.message_manager.create_llm_message(
                    content=f"""
                    <h3>추가 답변</h3>
                    <span class="{self.get_recommendation_class(recommendation)}">{recommendation}</span>
                    <p>{self.markdown_to_html(answer)}</p>
                    """,
                    model_name=model_name
                )
                self.append_to_chat(answer_message)
                
        except Exception as e:
            self.handle_response_error("추가 질문 처리 중 오류", str(e))

    def display_joke(self):
        """Requests and displays a joke."""
        pass

    def display_edit_advice(self):
        """Requests and displays card edit advice."""
        pass

    def show_joke(self):
        """Requests and displays a joke."""
        pass

    def show_edit_advice(self):
        """Requests and displays card edit advice."""
        pass

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

        # 사용자 메시지를 Message 객체로 생성
        user_message = Message(
            content=user_answer,
            message_type=MessageType.USER
        )
        self.append_to_chat(user_message)

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
            
            # Display user question as Message object
            user_message = Message(
                content=question,
                message_type=MessageType.USER
            )
            self.append_to_chat(user_message)
            
            # Show loading animation
            self.display_loading_animation(True)
            
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
            self.display_loading_animation(False)
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
        self.display_loading_animation(False)

    @pyqtSlot(str)
    def _show_error_message(self, message):
        """Show error message in chat"""
        error_message = self.message_manager.create_error_message(message)
        self.append_to_chat(error_message)

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
                self.last_difficulty_message = self.message_manager.create_system_message(
                    f"LLM의 추천에 따라 <span class='recommendation {self.get_recommendation_class(recommendation)}'>{recommendation}</span> 난이도로 평가했습니다."
                )
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
        self.web_view.page().runJavaScript("""
            document.querySelector('.chat-container').innerHTML = '';
        """)
        # 필요한 경우 웰컴 메시지 추가
        welcome_message = self.message_manager.create_welcome_message()
        self.append_to_chat(welcome_message)

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

    def on_prepare_card(self, card):
        """카드 준비 시 호출되는 핸들러"""
        if self.isVisible():
            try:
                logger.debug("=== Preparing card ===")
                card_content, _, _ = self.bridge.get_card_content()
                logger.debug(f"Card content: {card_content[:50]}...")  # 내용 일부 로깅
                
                question_message = self.message_manager.create_question_message(
                    content=self.markdown_to_html(card_content)
                )
                logger.debug(f"Generated message HTML: {question_message.to_html()[:200]}...")
                
                self.clear_chat()
                # clear_chat 후 콜백으로 메시지 추가
                def delayed_append():
                    self.append_to_chat(question_message)
                
                QTimer.singleShot(300, delayed_append)  # 0.3초 딜레이 추가
            except Exception as e:
                self.show_error_message(f"카드 로드 실패: {str(e)}")
