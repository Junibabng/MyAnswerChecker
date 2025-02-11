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
from .providers import LLMProvider, OpenAIProvider, GeminiProvider
import traceback
from .message import MessageType, Message
from .settings_manager import settings_manager
from .providers.provider_factory import get_provider
from aqt.qt import QSettings
from .auto_difficulty import extract_difficulty  # 재정의

# Logging setup
addon_dir = os.path.dirname(os.path.abspath(__file__))
log_file_path = os.path.join(addon_dir, 'MyAnswerChecker_debug.log')
os.makedirs(addon_dir, exist_ok=True)

# Create a logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Create a file handler
file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)

# Create formatters
debug_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s\n'
    'File: %(filename)s:%(lineno)d\n'
    'Function: %(funcName)s\n'
    'Message: %(message)s\n'
)

error_formatter = logging.Formatter(
    '\n=== Error Log ===\n'
    '%(asctime)s - %(name)s - %(levelname)s\n'
    'File: %(filename)s:%(lineno)d\n'
    'Function: %(funcName)s\n'
    'Message: %(message)s\n'
    'Stack Trace:\n%(stack_trace)s\n'
    '================\n'
)

class ErrorLogFilter(logging.Filter):
    """에러 로그에 스택 트레이스를 추가하는 필터"""
    def filter(self, record):
        if record.levelno >= logging.ERROR:
            record.stack_trace = traceback.format_stack()
        return True

# Add formatter and filter to handler
file_handler.setFormatter(debug_formatter)
file_handler.addFilter(ErrorLogFilter())

# Add the handler to the logger
logger.addHandler(file_handler)

def log_error(e, context=None):
    """상세한 에러 로깅을 위한 유틸리티 함수"""
    error_info = {
        'timestamp': datetime.now().isoformat(),
        'error_type': type(e).__name__,
        'error_message': str(e),
        'stack_trace': traceback.format_exc(),
        'context': context or {}
    }
    
    logger.error(
        "\n=== Error Details ===\n"
        f"Time: {error_info['timestamp']}\n"
        f"Type: {error_info['error_type']}\n"
        f"Message: {error_info['error_message']}\n"
        f"Context: {error_info['context']}\n"
        f"Stack Trace:\n{error_info['stack_trace']}\n"
        "===================="
    )
    return error_info

logger.info("Addon load start")

# Global bridge object
bridge = None
answer_checker_window = None

# Constants for difficulty levels
DIFFICULTY_AGAIN = "Again"
DIFFICULTY_HARD = "Hard"
DIFFICULTY_GOOD = "Good"
DIFFICULTY_EASY = "Easy"

class BridgeError(Exception):
    """Bridge 관련 기본 예외 클래스"""
    def __init__(self, message, help_text=None):
        super().__init__(message)
        self.help_text = help_text or "나중에 다시 시도해 주세요."

class CardContentError(BridgeError):
    """카드 콘텐츠 처리 관련 예외"""
    def __init__(self, message):
        help_texts = {
            "no_card": "다른 카드로 이동한 후 다시 시도해 주세요.",
            "empty": "카드 내용을 확인하고 필요한 내용을 추가해 주세요.",
            "no_field": "카드 템플릿을 확인하고 필요한 필드를 추가해 주세요."
        }
        
        if "현재 리뷰 중인 카드가 없습니다" in message:
            help_text = help_texts["no_card"]
        elif "비어있습니다" in message:
            help_text = help_texts["empty"]
        elif "필드가 없습니다" in message:
            help_text = help_texts["no_field"]
        else:
            help_text = "카드 내용을 확인하고 다시 시도해 주세요."
            
        super().__init__(message, help_text)

class ResponseProcessingError(BridgeError):
    """응답 처리 관련 예외"""
    def __init__(self, message):
        help_texts = {
            "json": "잠시 후 다시 시도해 주세요.",
            "fields": "다시 한 번 시도해 주세요. 문제가 계속되면 설정에서 다른 AI 모델을 선택해보세요."
        }
        
        if "JSON" in message:
            help_text = help_texts["json"]
        else:
            help_text = help_texts["fields"]
            
        super().__init__(message, help_text)

class LLMProviderError(BridgeError):
    """LLM 제공자 관련 에러"""
    def __init__(self, message):
        super().__init__(message, "LLM 서비스 설정을 확인해주세요.")

class InvalidAPIKeyError(BridgeError):
    """API 키 관련 에러"""
    def __init__(self, message):
        super().__init__(message, "API 키가 설정되지 않았습니다.")

class Bridge(QObject):
    # Constants
    RESPONSE_TIMEOUT = 10  # seconds
    DEFAULT_TEMPERATURE = 0.2
    
    # Signal definitions
    sendResponse = pyqtSignal(str)
    sendQuestionResponse = pyqtSignal(str)
    timer_signal = pyqtSignal(str)
    stream_data_received = pyqtSignal(str, str, str)
    model_info_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._initialize_attributes()
        self._setup_timer()
        
        # 설정 매니저에 옵저버로 등록
        settings_manager.add_observer(self)
        
        # 초기 설정 로드
        settings = settings_manager.load_settings()
        self.update_config(settings)
        
        self.partial_response = ""
        self._answer_checker_window = None  # 추가: AnswerCheckerWindow 참조 저장
        logger.info("Bridge initialized")

    def _initialize_attributes(self):
        """Initialize all instance attributes"""
        self.llm_data = {}
        self.last_response = None
        self.last_user_answer = None
        self.last_elapsed_time = None
        self.timer_start_time = None
        self.elapsed_time = None
        self.llm_provider = None
        self.response_buffer = {}
        self.response_wait_timers = {}
        self.conversation_history = {
            'messages': [],
            'card_context': None,
            'current_card_id': None
        }
        self.max_context_length = 10  # 최대 대화 기록 수
        self.current_card_id = None    # Add this line
        self.is_processing = False      # Add this line

    def _setup_timer(self):
        """Setup timer with configurations"""
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_timer)
        self.timer_interval = 500  # 0.5 seconds
        self.timer.setInterval(self.timer_interval)

    def _handle_response_timeout(self, request_id, data_type="response"):
        """Handle timeout for responses"""
        logger.error(f"Response timeout for {data_type} request {request_id}")
        error_message = "응답 시간이 초과되었습니다."
        help_text = "인터넷 연결을 확인하고 다시 시도해 주세요."
        
        error_html = f"""
        <div class="system-message-container error">
            <div class="system-message">
                <p class="error-message" style="color: #e74c3c; margin-bottom: 8px;">{error_message}</p>
                <p class="help-text" style="color: #666; font-size: 0.9em;">{help_text}</p>
            </div>
            <div class="message-time">{datetime.now().strftime("%p %I:%M")}</div>
        </div>
        """
        
        if answer_checker_window:
            answer_checker_window.web_view.setHtml(answer_checker_window.default_html + error_html)
            answer_checker_window.display_loading_animation(False)
        self._clear_request_data(request_id)

    def _clear_request_data(self, request_id):
        """Clear request related data"""
        if request_id in self.response_buffer:
            del self.response_buffer[request_id]
        if request_id in self.response_wait_timers:
            del self.response_wait_timers[request_id]

    def _process_complete_response(self, response_text):
        """완전한 응답을 처리하고 UI를 업데이트"""
        try:
            # 로딩 애니메이션 숨기기
            if answer_checker_window:
                answer_checker_window.display_loading_animation(False)
                
            logger.debug(f"응답 처리 시작:\n{response_text[:200]}...")
            
            # 코드 블록 마커 제거
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response_text)
            
            # JSON 객체를 찾기 위한 정규식 패턴
            json_pattern = r'\{(?:[^{}]|{[^{}]*})*\}'
            
            # 모든 JSON 객체 찾기
            json_matches = list(re.finditer(json_pattern, cleaned_response, re.DOTALL))
            
            # 마지막 매치부터 역순으로 검사
            json_str = None
            response_json = None
            
            for match in reversed(json_matches):
                try:
                    json_str = match.group(0)
                    data = json.loads(json_str)
                    
                    # recommendation 필드가 있고 값이 유효한지 확인
                    if "recommendation" in data:
                        recommendation = data["recommendation"].strip()
                        valid_recommendations = [DIFFICULTY_AGAIN, DIFFICULTY_HARD, DIFFICULTY_GOOD, DIFFICULTY_EASY]
                        
                        if recommendation in valid_recommendations:
                            response_json = data
                            logger.debug(f"유효한 난이도 추출 성공: {recommendation}")
                            break
                        else:
                            logger.debug(f"유효하지 않은 난이도 값: {recommendation}")
                            continue
                            
                except json.JSONDecodeError:
                    logger.debug("유효하지 않은 JSON 형식, 다음 매치 시도")
                    continue
                except Exception as e:
                    logger.debug(f"JSON 처리 중 오류 발생: {str(e)}")
                    continue
            
            if not json_str or not response_json:
                logger.error("유효한 JSON을 찾을 수 없습니다.")
                raise ResponseProcessingError("응답 형식이 올바르지 않습니다.")
            
            # 응답 텍스트에서 JSON 부분 제거
            display_text = cleaned_response.replace(json_str, "").strip()
            
            # JSON 부분이 제거된 텍스트가 있으면 마크다운 변환
            if display_text:
                processed_content = self.markdown_to_html(display_text)
            else:
                processed_content = "평가가 완료되었습니다."
            
            if self._answer_checker_window:
                html_content = self._generate_response_html(response_json)
                self._answer_checker_window.web_view.setHtml(self._answer_checker_window.default_html + html_content)
                logger.info("UI 업데이트 완료")
            return True
            
        except json.JSONDecodeError as e:
            logger.warning(
                "불완전한 JSON 응답:\n"
                f"Current Buffer: {self.partial_response[:200]}...\n"
                f"New Text: {response_text[:200]}..."
            )
            self.partial_response += response_text
            return False
            
        except ResponseProcessingError as e:
            log_error(e, {
                'response_text': response_text,
                'partial_response': self.partial_response
            })
            self._show_error_message(str(e))
            self.partial_response = ""
            return True

    def _generate_response_html(self, response_json):
        """Generate HTML content from response JSON"""
        evaluation = response_json.get("evaluation", "No evaluation")
        recommendation = response_json.get("recommendation", "No recommendation")
        answer = response_json.get("answer", "")
        reference = response_json.get("reference", "")
        
        return f"""
        <h2>Evaluation Results</h2>
        <p class="evaluation"><strong>Evaluation:</strong> {self.markdown_to_html(evaluation)}</p>
        <p class="recommendation"><strong>Recommendation:</strong> {self.markdown_to_html(recommendation)}</p>
        <div class="answer"><strong>Answer:</strong> <p>{self.markdown_to_html(answer)}</p></div>
        <div class="reference"><strong>Reference:</strong> <p>{self.markdown_to_html(reference)}</p></div>
        """

    @pyqtSlot(str, str, str)
    def update_response_chunk(self, chunk, request_id, data_type):
        """Updates the response in the webview with a chunk of data."""
        logger.debug(f"Received chunk for {request_id}: {chunk}")
        
        # Initialize buffer and timer if needed
        if request_id not in self.response_buffer:
            self.response_buffer[request_id] = ""
            self.response_wait_timers[request_id] = time.time()
            # 새로운 메시지 컨테이너 생성
            if answer_checker_window:
                answer_checker_window.create_message_container(request_id)
                answer_checker_window.display_loading_animation(True)
        
        # Update buffer
        self.response_buffer[request_id] += chunk
        wait_time = time.time() - self.response_wait_timers[request_id]
        
        # Handle timeout
        if wait_time > self.RESPONSE_TIMEOUT:
            self._handle_response_timeout(request_id, data_type)
            if answer_checker_window:
                answer_checker_window.display_loading_animation(False)
            return
        
        # 실시간으로 청크 업데이트
        if answer_checker_window:
            answer_checker_window.update_message_chunk(request_id, chunk, data_type)
        
        # Process complete response
        if data_type == "response":
            if self.is_complete_response(self.response_buffer[request_id]):
                if self._process_complete_response(self.response_buffer[request_id]):
                    self._clear_request_data(request_id)
                    if answer_checker_window:
                        answer_checker_window.display_loading_animation(False)
        elif data_type in ["question", "joke", "edit_advice"]:
            try:
                # JSON 파싱 시도
                response_json = json.loads(self.response_buffer[request_id])
                if answer_checker_window:
                    answer_checker_window.finalize_message(request_id, response_json, data_type)
                    answer_checker_window.display_loading_animation(False)
                self._clear_request_data(request_id)
            except json.JSONDecodeError:
                # 아직 완성되지 않은 JSON이면 계속 누적
                pass

    def is_complete_response(self, response_text):
        """
        응답이 완전한지, 즉 유효한 recommendation을 포함한 JSON이 있는지 확인합니다.
        """
        try:
            # 코드 블록 마커 제거
            cleaned_response = re.sub(r'```json\s*|\s*```', '', response_text)
            
            # JSON 객체를 찾기 위한 정규식 패턴
            json_pattern = r'\{(?:[^{}]|{[^{}]*})*\}'
            
            # 모든 JSON 객체 찾기
            json_matches = list(re.finditer(json_pattern, cleaned_response, re.DOTALL))
            
            # 마지막 매치부터 역순으로 검사
            for match in reversed(json_matches):
                try:
                    json_str = match.group(0)
                    data = json.loads(json_str)
                    
                    # recommendation 필드가 있고 값이 유효한지 확인
                    if "recommendation" in data:
                        recommendation = data["recommendation"].strip()
                        valid_recommendations = [DIFFICULTY_AGAIN, DIFFICULTY_HARD, DIFFICULTY_GOOD, DIFFICULTY_EASY]
                        
                        if recommendation in valid_recommendations:
                            logger.debug(f"유효한 난이도 추출 성공: {recommendation}")
                            return True
                        else:
                            logger.debug(f"유효하지 않은 난이도 값: {recommendation}")
                            continue
                            
                except json.JSONDecodeError:
                    logger.debug("유효하지 않은 JSON 형식, 다음 매치 시도")
                    continue
                except Exception as e:
                    logger.debug(f"JSON 처리 중 오류 발생: {str(e)}")
                    continue
            
            logger.debug("유효한 난이도 추천을 찾을 수 없습니다.")
            return False
            
        except Exception as e:
            logger.error(f"응답 완성 여부 확인 중 오류 발생: {str(e)}")
            return False

    def update_llm_provider(self, settings=None):
        """Update LLM provider with the given or current settings"""
        if settings is None:
            settings = settings_manager.load_settings()
        provider_type = settings.get("providerType", "openai").lower()

        self.system_prompt = settings.get("systemPrompt", "You are a helpful assistant.")

        def mask_key(key):
            return f"****...{key[-4:]}" if key and len(key) > 4 else "[키 없음]"

        openai_key = settings.get("openaiApiKey", "")
        gemini_key = settings.get("geminiApiKey", "")

        logger.debug(f"""=== LLM 프로바이더 업데이트 ===
• 현재 제공자: {provider_type}
• OpenAI 키: {mask_key(openai_key)}
• Gemini 키: {mask_key(gemini_key)}
• 시스템 프롬프트: {self.system_prompt[:50]}...
=============================""")

        try:
            self.llm_provider = get_provider(settings)

            if hasattr(self.llm_provider, 'set_system_prompt'):
                self.llm_provider.set_system_prompt(self.system_prompt)

            logger.info(f"LLM Provider changed to {provider_type}")

        except Exception as e:
            logger.error(f"Error updating LLM provider: {str(e)}")
            self._show_error_message(f"모델 변경 실패: {str(e)}")

    def call_llm_api(self, system_message, user_message_content, max_retries=3):
        """Calls the selected LLM API to get a response."""
        if not self.llm_provider:
            self.update_llm_provider()

        for attempt in range(max_retries):
            try:
                return self.llm_provider.call_api(system_message, user_message_content)
            except requests.exceptions.RequestException as e:
                logger.error(f"Error calling LLM API (Attempt {attempt + 1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    return f"Error occurred while calling LLM API. ({e})"
                time.sleep(1)
            except Exception as e:
                logger.exception("Unexpected error calling LLM API: %s", e)
                return "An unexpected error occurred while calling LLM API."

    def start_timer(self):
        """Starts the timer."""
        self.timer_start_time = datetime.now()
        self.timer.start()
        logger.debug("Timer started")

    def stop_timer(self):
        """Stops the timer and returns the elapsed time."""
        if self.timer.isActive():
            self.timer.stop()
            elapsed_seconds = (datetime.now() - self.timer_start_time).total_seconds()
            self.elapsed_time = int(elapsed_seconds)
            logger.debug(f"Timer stopped. Elapsed time: {self.elapsed_time} seconds")
            return self.elapsed_time
        return None

    def update_timer(self):
        """Updates the timer based on real time."""
        if self.timer_start_time:
            elapsed_seconds = (datetime.now() - self.timer_start_time).total_seconds()
            self.timer_signal.emit(str(int(elapsed_seconds)))

    @pyqtSlot(str)
    def receiveAnswer(self, user_answer):
        """Processes the user's answer received from JavaScript and sends a response."""
        if self.is_processing:
            return
            
        self.is_processing = True
        try:
            current_card = mw.reviewer.card
            if current_card:
                if self.current_card_id == current_card.id:
                    # Skip evaluation if we've already evaluated this card
                    self.is_processing = False
                    if answer_checker_window:
                        answer_checker_window.display_loading_animation(False)
                    return
                self.current_card_id = current_card.id
                
            logger.debug("Received answer from JS: %s", user_answer)
            try:
                # 설정값 로깅 추가
                settings = settings_manager.load_settings()
                easy_threshold = int(settings.get("easyThreshold", "5"))
                good_threshold = int(settings.get("goodThreshold", "15"))
                hard_threshold = int(settings.get("hardThreshold", "50"))
                
                logger.debug(f"Current threshold settings - Easy: {easy_threshold}s, Good: {good_threshold}s, Hard: {hard_threshold}s")
                
                card_content, card_answers, card_ord = self.get_card_content()
                if not card_content:
                    if answer_checker_window:
                        answer_checker_window.display_loading_animation(False)
                    showInfo("Could not retrieve card information.")
                    response = json.dumps({"evaluation": "Card info error", "recommendation": "None", "answer": "", "reference": ""})
                    self.sendResponse.emit(response)
                    return

                # 타이머 정지 및 경과 시간 확인
                elapsed_time = self.stop_timer()
                logger.debug(f"Elapsed time for this answer: {elapsed_time}s")
                
                self.last_elapsed_time = elapsed_time
                self.last_user_answer = user_answer
                
                self.llm_data = {
                    "card_content": card_content,
                    "card_answers": card_answers,
                    "user_answer": user_answer,
                    "elapsed_time": elapsed_time,
                    "card_ord": card_ord
                }
                
                thread = threading.Thread(target=self.process_answer)
                thread.start()
            except Exception as e:
                logger.exception("Error processing receiveAnswer: %s", e)
                if answer_checker_window:
                    answer_checker_window.display_loading_animation(False)
                response = json.dumps({"evaluation": "Error occurred", "recommendation": "None", "answer": "", "reference": ""})
                self.sendResponse.emit(response)
        finally:
            self.is_processing = False

    def create_llm_message(self, card_content, card_answers, question, request_type):
        """Creates the message to be sent to the LLM API."""
        try:
            # Obtain card content etc.
            card = mw.reviewer.card
            note = card.note()
            model = note.model()
            model_type = model.get('type')
            
            settings = settings_manager.load_settings()
            easy_threshold = int(settings.get("easyThreshold", 5))
            good_threshold = int(settings.get("goodThreshold", 15))
            hard_threshold = int(settings.get("hardThreshold", 50))
            elapsed_time = self.llm_data.get("elapsed_time")
            language = settings.get("language", "English")
            
            # Ensure system prompt is up-to-date
            current_system_prompt = settings.get("systemPrompt", "You are a helpful assistant.")
            if current_system_prompt != self.system_prompt:
                self.system_prompt = current_system_prompt
                if hasattr(self.llm_provider, 'set_system_prompt'):
                    self.llm_provider.set_system_prompt(self.system_prompt)
            
            # Clean content
            soup_content = BeautifulSoup(card_content, 'html.parser')
            clean_content = soup_content.get_text()
            
            formatted_answers = ", ".join(card_answers) if isinstance(card_answers, list) else str(card_answers)
            logger.debug(f"Formatted answers for LLM: {formatted_answers}")
            
            # 이전 대화 내용 가져오기
            conversation_context = []
            if self.conversation_history['messages']:
                conversation_context.append("\nPrevious conversation:")
                for msg in self.conversation_history['messages'][-self.max_context_length:]:
                    conversation_context.append(f"{msg['role'].title()}: {msg['content']}")
            
            # Create common context data
            context_data = f"""
            Context about this Anki card:
            Card Content: {clean_content}
            Correct Answer(s): {formatted_answers}
            User's Answer: {self.llm_data.get('user_answer', 'Not available')}
            Time Taken: {elapsed_time or 'Not available'} seconds
            Previous Evaluation: Not available
            Previous Recommendation: Not available
            {''.join(conversation_context)}
            """

            type_specific_content = {
                "answer": {
                    "system": f"You are a helpful assistant. Always answer in {language}.",
                    "content": f"""
                        Evaluate the user's answer to an Anki card and recommend one of the following options: '{DIFFICULTY_AGAIN}', '{DIFFICULTY_HARD}', '{DIFFICULTY_GOOD}', or '{DIFFICULTY_EASY}'.

                        Your evaluation should include:
                            - An assessment of the semantic accuracy of the user's answer
                            - Consideration of the time taken to answer
                            - The correct answer and its variations
                            - Additional reference information to help the user understand

                        Evaluation Criteria:
                            1. Content Accuracy:
                                Essential Meaning Assessment:
                                    - Focus on whether the user's answer captures the core meaning
                                    - Accept synonyms and alternative expressions that convey the same idea
                                    - Allow for common variations in language use
                                    - Accept informal or colloquial forms if they clearly convey the same meaning
                                    {f"- For the {self.llm_data.get('card_ord', 0) + 1}th blank, assess meaning equivalence while being mindful of context" if model_type == 1 else ""}

                                Acceptable Variations:
                                    - Minor spelling or typing errors if meaning is clear
                                    - Grammatical variations that preserve the core meaning
                                    - Colloquial or informal expressions that match the meaning
                                    - Regional language variations if semantically equivalent

                                Strictly Incorrect Cases:
                                    - Answers that change or negate the intended meaning
                                    - Completely unrelated or irrelevant responses
                                    - Overly vague answers that don't demonstrate understanding

                            2. Response Time:
                                - Only consider time for semantically correct answers
                                - Time thresholds for difficulty levels:
                                    - Easy: < {easy_threshold} seconds
                                    - Good: {easy_threshold} - {good_threshold} seconds
                                    - Hard: ≥ {good_threshold} seconds
                                    - Auto-Again: > {hard_threshold} seconds

                        Recommendation Guidelines:
                            {DIFFICULTY_AGAIN}:
                                Recommend if:
                                    - The answer fails to convey the essential meaning
                                    - The response is unrelated or changes the core concept
                                    - Time exceeds {hard_threshold} seconds (regardless of correctness)
                                    - The answer is too vague to demonstrate understanding

                            {DIFFICULTY_HARD}:
                                Recommend if:
                                    - The answer correctly conveys the meaning
                                    - Response time ≥ {good_threshold} seconds
                                    - Shows understanding but took significant time to recall

                            {DIFFICULTY_GOOD}:
                                Recommend if:
                                    - The answer correctly conveys the meaning
                                    - Response time between {easy_threshold} and {good_threshold} seconds
                                    - Demonstrates good understanding with reasonable recall speed

                            {DIFFICULTY_EASY}:
                                Recommend if:
                                    - The answer correctly conveys the meaning
                                    - Response time < {easy_threshold} seconds
                                    - Shows quick and confident recall

                        Additional Guidelines:
                            Language Variations:
                                - Accept common synonyms (e.g., 'gonna' for 'going to')
                                - Allow for dialectal variations if meaning is preserved
                                - Consider context when evaluating informal expressions
                                - Recognize alternative grammatical forms

                            Feedback Approach:
                                - Acknowledge correct meaning even if form differs
                                - Provide standard form for reference when variations used
                                - Include constructive guidance for improvement
                                - Explain why variations are acceptable when relevant

                            Multiple Answers:
                                - All essential concepts must be present
                                - Accept equivalent expressions for each concept
                                - Consider context for meaning assessment
                                - Allow for variation in expression order

                        Example Applications:
                            1. Variation in Form:
                                User Answer: "gonna"
                                Correct Answer: "going to"
                                Evaluation: Correct (same meaning, informal variation)
                                Recommendation: Based on time + "Consider standard form 'going to'"

                            2. Semantic Equivalence:
                                User Answer: "will not"
                                Correct Answer: "won't"
                                Evaluation: Correct (semantically equivalent expression)
                                Recommendation: Based on time + "Alternative expression accepted"

                            3. Incorrect Meaning:
                                User Answer: "will"
                                Correct Answer: "won't"
                                Evaluation: Incorrect (opposite meaning)
                                Recommendation: {DIFFICULTY_AGAIN}

                        **Data Provided:**
                            Card Content: {clean_content}
                            Correct Answer(s): {formatted_answers}
                            User's Answer: {self.llm_data.get("user_answer", "Not available")}
                            Time Taken: {elapsed_time} seconds

                        A difficulty recommendation string must be included exactly at the very end of the final answer as follows:
                        {{
                            "recommendation": "Again|Hard|Good|Easy"
                        }}
                        """
                },
                "question": {
                    "system": f"You are a helpful assistant. Always answer in {language}.",
                    "content": f"{context_data}\n\nAdditional Question: {question}\n\nBased on all this context and previous conversation, please provide a detailed answer to the additional question."
                },
                "joke": {
                    "system": f"You are a comedian. Always answer in {language}.",
                    "content": f"{context_data}\n\nBased on this context, previous conversation, and especially considering how well the user performed, please create a funny and encouraging joke related to this card's content."
                },
                "edit_advice": {
                    "system": f"You are an Anki card editing expert. Always answer in {language}.",
                    "content": f"{context_data}\n\nBased on the user's performance, previous conversation, and all available context, please provide detailed, actionable advice for improving this card."
                }
            }

            # 현재 메시지를 대화 기록에 추가 (for request types other than answer)
            if request_type != "answer":
                if question:
                    self.conversation_history['messages'].append({
                        'role': 'user',
                        'content': question
                    })

            selected_type = type_specific_content.get(request_type, {
                "system": f"You are a helpful assistant. Always answer in {language}.",
                "content": "Invalid request type"
            })

            return selected_type["system"], selected_type["content"]
        except Exception as e:
            logger.exception("Error creating LLM message: %s", e)
            return "Error creating LLM message", "Error creating LLM message"

    def process_answer(self):
        """Calls the LLM API in a background thread to get the evaluation."""
        try:
            # If card changed, reset conversation history
            card = mw.reviewer.card
            if card and card.id != self.current_card_id:
                self.current_card_id = card.id
                self.clear_conversation_history()
            
            # Add user's answer to conversation history
            self.conversation_history['messages'].append({
                'role': 'user',
                'content': f"Answer: {self.llm_data.get('user_answer', 'Not available')}"
            })

            system_message, user_message_content = self.create_llm_message(
                self.llm_data["card_content"], 
                self.llm_data["card_answers"], 
                None, 
                "answer"
            )
            
            logger.debug(f"LLM Input - Card content: {self.llm_data['card_content']}")
            logger.debug(f"LLM Input - Card answers: {self.llm_data['card_answers']}")
            logger.debug(f"LLM Input - User answer: {self.llm_data['user_answer']}")
            
            response_text = self.call_llm_api(system_message, user_message_content)
            logger.debug(f"LLM Raw Response: {response_text}")
            
            # Store the raw response
            self.last_response = response_text

            # Extract recommendation and create difficulty message
            recommendation = self.extract_difficulty(response_text)
            if recommendation:
                logger.debug(f"추출된 난이도 추천: {recommendation}")
                
                if self._answer_checker_window:
                    # Create and display difficulty message
                    difficulty_message = self._answer_checker_window.message_manager.create_difficulty_message(recommendation)
                    self._answer_checker_window.append_to_chat(difficulty_message)
                    self._answer_checker_window.last_difficulty_message = difficulty_message
                    
                    # Execute automatic difficulty evaluation
                    self._answer_checker_window.follow_llm_suggestion()
                else:
                    logger.warning("Answer Checker Window is not available for displaying difficulty message")

            QMetaObject.invokeMethod(
                self,
                "sendResponse",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, response_text)
            )
        except Exception as e:
            logger.exception("Error processing OpenAI API: %s", e)
            error_response = json.dumps({
                "evaluation": "Error occurred",
                "recommendation": "None",
                "answer": "",
                "reference": ""
            })
            self.last_response = error_response
            QMetaObject.invokeMethod(
                self,
                "sendResponse",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, error_response)
            )
        finally:
            self._clear_llm_data()

    def process_question(self, card_content, question, card_answers):
        """Generates an answer to an additional question."""
        try:
            logger.debug("=== Processing Additional Question ===")
            logger.debug(f"Question: {question}")
            
            # 사용자 질문을 대화 기록에 추가
            self.conversation_history['messages'].append({
                'role': 'user',
                'content': question
            })
            
            system_message, user_message_content = self.create_llm_message(
                card_content,
                card_answers,
                question,
                "question"
            )
            
            # LLM 응답 받기
            response = self.call_llm_api(system_message, user_message_content)
            
            # LLM 응답을 대화 기록에 추가
            self.conversation_history['messages'].append({
                'role': 'assistant',
                'content': response
            })
            
            # 응답 직접 전송
            logger.debug(f"Sending response (truncated): {response[:200]}...")
            
            QMetaObject.invokeMethod(
                self,
                "sendQuestionResponse",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, response)
            )
            
        except Exception as e:
            logger.exception("Error processing additional question: %s", e)
            if answer_checker_window:
                answer_checker_window.display_loading_animation(False)
            QMetaObject.invokeMethod(
                self,
                "sendQuestionResponse",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, str(e))
            )

    def extract_json_from_text(self, text):
        """Extracts the last JSON part from the text."""
        try:
            # Remove code block markers and clean text
            text = self._clean_text(text)
            
            # Try to find JSON block with code block markers first
            json_match = re.search(r'```(?:json)?\s*({[\s\S]*?})\s*```', text)
            if json_match:
                try:
                    json_str = json_match.group(1)
                    json_str = self._normalize_json_string(json_str)
                    parsed = json.loads(json_str)
                    if self._validate_json_fields(parsed):
                        return json_str
                except:
                    pass

            # If that fails, try to find any JSON-like structure
            try:
                # Find the last occurrence of a JSON-like structure
                json_matches = list(re.finditer(r'{[\s\S]*?}', text))
                if json_matches:
                    for match in reversed(json_matches):
                        try:
                            json_str = match.group(0)
                            json_str = self._normalize_json_string(json_str)
                            parsed = json.loads(json_str)
                            if self._validate_json_fields(parsed):
                                return json_str
                        except:
                            continue
            except:
                pass
            
            return None
        except Exception as e:
            logger.error(f"Error in extract_json_from_text: {str(e)}")
            return None

    def _clean_text(self, text):
        """Clean text by removing code block markers and normalizing whitespace"""
        # 코드 블록 마커 제거
        text = re.sub(r'```json\s*|\s*```', '', text)
        # 마크다운 포 제거
        text = re.sub(r'\*\*.*?\*\*', '', text)
        text = re.sub(r'{{c\d+::.*?}}', '', text)
        # 줄바꿈 및 백 정규화
        text = text.replace('\n', ' ').replace('\r', '')
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _find_valid_json(self, text):
        """Find and validate JSON in text with improved pattern matching"""
        try:
            text = self._clean_text(text)
            
            # 통합된 JSON 패턴
            patterns = [
                # 엄격한 패턴 (필드 순서 지정)
                r'({[^{}]*?"evaluation"\s*:\s*"[^"]*?"\s*,\s*"recommendation"\s*:\s*"(?:Again|Hard|Good|Easy)"\s*,\s*"answer"\s*:\s*"(?:[^"\\]|\\.)*"\s*,\s*"reference"\s*:\s*"(?:[^"\\]|\\.)*"\s*})',
                # 유연한 패턴 (필드 순서 무관)
                r'({(?:[^{}]|{[^{}]*})*"evaluation"\s*:\s*"(?:[^"\\]|\\.)*".*?"recommendation"\s*:\s*"(?:Again|Hard|Good|Easy)".*?"answer"\s*:\s*"(?:[^"\\]|\\.)*".*?"reference"\s*:\s*"(?:[^"\\]|\\.)*".*?})',
                # 가장 유연한 패턴 (마지막 시도)
                r'({(?:[^{}]|{[^{}]*})*})'
            ]
            
            for pattern in patterns:
                matches = list(re.finditer(pattern, text, re.DOTALL))
                
                for match in reversed(matches):  # 마지막 매치부터 시도
                    try:
                        json_str = self._normalize_json_string(match.group(1))
                        parsed = json.loads(json_str)
                        
                        if self._validate_json_fields(parsed):
                            logger.debug(f"Valid JSON found: {json_str[:100]}...")
                            return json_str
                            
                    except json.JSONDecodeError as e:
                        logger.debug(f"JSON decode error in match: {str(e)}")
                        continue
                    except Exception as e:
                        logger.debug(f"Unexpected error processing JSON match: {str(e)}")
                        continue
            
            logger.error("No valid JSON pattern found in response")
            logger.debug(f"Raw text: {text[:200]}...")
            return None

        except Exception as e:
            logger.error(f"Error in _find_valid_json: {str(e)}")
            return None

    def _normalize_json_string(self, json_str):
        """Normalize JSON string by handling quotes and escapes"""
        try:
            # 따옴표 정규화
            json_str = re.sub(r"'([^']*)':", r'"\1":', json_str)  # 키값의 따옴표
            json_str = re.sub(r':\s*\'([^\']*?)\'([,}])', r':"\1"\2', json_str)  # 값의 따옴표
            
            # 이스케이프 문자 처리
            json_str = json_str.replace("\\'", "'")
            json_str = json_str.replace('\\"', '"')
            
            # 줄바꿈 문자 제거
            json_str = json_str.replace('\n', ' ').replace('\r', '')
            
            # 연속된 공백 제거
            json_str = re.sub(r'\s+', ' ', json_str)
            
            return json_str.strip()
        except Exception as e:
            logger.error(f"Error normalizing JSON string: {str(e)}")
            return json_str

    def _validate_json_fields(self, parsed_json):
        """Validate required fields in parsed JSON with improved validation"""
        try:
            # 필수 필드 통일
            required_fields = ["evaluation", "recommendation", "answer", "reference"]
            if not all(field in parsed_json for field in required_fields):
                logger.debug(f"Missing required fields in JSON: {parsed_json.keys()}")
                return False
            
            # recommendation 값 검증
            valid_recommendations = ["Again", "Hard", "Good", "Easy"]
            if parsed_json["recommendation"] not in valid_recommendations:
                logger.debug(f"Invalid recommendation value: {parsed_json['recommendation']}")
                return False
            
            # 필드 값이 비있지 않은지 확인
            if not all(parsed_json[field].strip() for field in required_fields):
                logger.debug("Empty required fields found")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error in _validate_json_fields: {str(e)}")
            return False

    def get_card_content(self):
        """현재 카드의 내용을 가져옵니다."""
        try:
            logger.debug("카드 콘텐츠 조회 시작")
            
            if not mw.reviewer or not mw.reviewer.card:
                logger.error("현재 리뷰 중인 카드가 없음")
                raise CardContentError("현재 리뷰 중인 카드가 없습니다.")

            card = mw.reviewer.card
            note = card.note()
            card_ord = card.ord
            
            logger.debug(
                f"카드 정보:\n"
                f"Card ID: {card.id}\n"
                f"Note ID: {note.id}\n"
                f"Card Type: {note.model()['name']}\n"
                f"Card Ordinal: {card_ord}"
            )

            # 카드 타입에 따른 처리
            if note.model()['name'] == "Cloze":
                logger.debug("Cloze 카드 처리 시작")
                return self._process_cloze_card(note, card_ord)
            else:
                logger.debug("기본 카드 처리 시작")
                return self._process_basic_card(card)

        except CardContentError as e:
            log_error(e, {
                'card_id': getattr(mw.reviewer.card, 'id', None),
                'note_type': getattr(note, 'model', lambda: {})().get('name') if 'note' in locals() else None
            })
            self._show_error_message(str(e))
            return None, None, None
            
        except Exception as e:
            log_error(e, {
                'card_id': getattr(mw.reviewer.card, 'id', None),
                'note_type': getattr(note, 'model', lambda: {})().get('name') if 'note' in locals() else None,
                'card_ord': locals().get('card_ord')
            })
            self._show_error_message(f"카드 콘텐츠 처리 중 오류가 발생했습니다: {str(e)}")
            return None, None, None

    def _process_cloze_card(self, note, card_ord):
        """Cloze 카드 처리"""
        try:
            if 'Text' not in note:
                raise CardContentError("Cloze 카드에 'Text' 필드가 없습니다.")

            text = note['Text']
            soup = BeautifulSoup(text, 'html.parser')
            
            # 불필요한 태그 제거
            self._remove_tags(soup, ['script', 'style'])
            self._remove_fsrs_status(soup)
            
            # 현재 카드의 cloze 번호에 해당하는 정답 추출
            cloze_pattern = re.compile(r'{{c' + str(card_ord + 1) + r'::(.*?)}}')
            matches = cloze_pattern.findall(text)
            if not matches:
                raise CardContentError(f"Cloze {card_ord + 1} 빈칸을 찾을 수 없습니다.")
            
            # 전체 내용은 그대로 유지
            content = soup.get_text(separator=' ', strip=True)
            if not content:
                raise CardContentError("카드 내용이 비어있습니다.")

            # 현재 cloze의 정답만 반환
            answers = [match.strip() for match in matches]
            
            return content, answers, card_ord

        except CardContentError:
            raise
        except Exception as e:
            raise CardContentError(f"Cloze 카드 처리 중 오류가 발생했습니다: {str(e)}")

    def _process_basic_card(self, card):
        """기본 카드 처리"""
        try:
            question = self._extract_question(card)
            answers = self._extract_answer(card)
            
            if not question.strip():
                raise CardContentError("질문 내용이 비어있습니다.")
            if not answers:
                raise CardContentError("답변 내용이 비어있습니다.")

            return question, answers, card.ord

        except CardContentError:
            raise
        except Exception as e:
            raise CardContentError(f"기본 카드 처리 중 오류가 발생했습니다: {str(e)}")

    def _extract_question(self, card):
        """Extract question from basic card"""
        question_soup = BeautifulSoup(card.q(), 'html.parser')
        self._remove_tags(question_soup, ['style', 'script'])
        return question_soup.get_text(separator=' ', strip=True)

    def _extract_answer(self, card):
        """Extract answer from basic card"""
        answer_soup = BeautifulSoup(card.a(), 'html.parser')
        self._remove_tags(answer_soup, ['style', 'script'])
        self._remove_fsrs_status(answer_soup)
        
        hr_tag = answer_soup.find('hr', id='answer')
        if hr_tag:
            return self._extract_answer_after_hr(hr_tag)
        
        return self._extract_all_text(answer_soup)

    def _remove_tags(self, soup, tags):
        """Remove specified tags from BeautifulSoup object"""
        for tag in soup.find_all(tags):
            tag.decompose()

    def _remove_fsrs_status(self, soup):
        """Remove FSRS status from BeautifulSoup object"""
        fsrs_status = soup.find('span', id='FSRS_status')
        if fsrs_status:
            fsrs_status.decompose()

    def _extract_answer_after_hr(self, hr_tag):
        """Extract answer text after hr tag"""
        answer_text = []
        current = hr_tag.next_sibling
        
        while current:
            if isinstance(current, str):
                text = current.strip()
                if text:
                    answer_text.append(text)
            elif current.name not in ['style', 'script', 'div']:
                text = current.get_text(strip=True)
                if text:
                    answer_text.append(text)
            current = current.next_sibling
        
        return [' '.join(answer_text)] if answer_text else []

    def _extract_all_text(self, soup):
        """Extract all text from soup"""
        all_text = []
        for text in soup.stripped_strings:
            text = text.strip()
            if text and not text.isspace():
                all_text.append(text)
        return [' '.join(all_text)] if all_text else []

    def _clear_llm_data(self):
        """Clears llm_data."""
        self.llm_data = {}
        self.elapsed_time = None

    def markdown_to_html(self, text):
        """Converts Markdown-style emphasis and line breaks to HTML tags."""
        if text is None:
            return ""
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        text = text.replace('\n', '<br>')
        return text

    def clear_conversation_history(self):
        """Clears the conversation history"""
        logger.debug("Clearing conversation history")
        self.conversation_history = {
            'messages': [],
            'card_context': None,
            'current_card_id': None
        }
        self.last_response = None
        self.last_user_answer = None
        self.last_elapsed_time = None

    def _show_error_message(self, message):
        """에러 메시지를 UI에 표시"""
        try:
            logger.debug(f"에러 메시지 표시 시작: {message}")
            
            if isinstance(message, (BridgeError, LLMProviderError)):
                error_message = str(message)
                help_text = message.help_text
                logger.debug(f"예외 타입: {type(message).__name__}, 도움말: {help_text}")
            else:
                error_message = str(message)
                help_text = "나중에 다시 시도해 주세요."
                logger.debug("일반 에러 메시지 처리")

            if answer_checker_window:
                answer_checker_window.show_error_message(error_message, help_text)
                logger.info("에러 메시지 UI 업데이트 완료")
                
        except Exception as e:
            log_error(e, {'original_message': message})
            logger.error(f"에러 메시지 표시 중 오류 발생: {str(e)}")
            if answer_checker_window:
                answer_checker_window.show_error_message(
                    "오류가 발생했습니다. 나중에 다시 시도해 주세요."
                )
                logger.info("기본 에러 메시지 UI 업데이트 완료")

    def handle_response_error(self, error_message, error_detail):
        """Handles errors during response processing"""
        logger.error(f"{error_message}: {error_detail}")
        if answer_checker_window:
            answer_checker_window.show_error_message(error_message)
        QTimer.singleShot(0, lambda: showInfo(error_message))

    def update_config(self, new_settings):
        """Update bridge configuration with new settings"""
        try:
            # Update thresholds
            self.easy_threshold = int(new_settings.get("easyThreshold", 5))
            self.good_threshold = int(new_settings.get("goodThreshold", 40))
            self.hard_threshold = int(new_settings.get("hardThreshold", 60))
            
            self.system_prompt = new_settings.get("systemPrompt", "You are a helpful assistant.")
            
            # Update the LLM provider using the new settings
            self.update_llm_provider(new_settings)
            
            # Clear conversation history for fresh start
            self.clear_conversation_history()
            
            logger.info(f"설정이 성공적으로 업데이트되었습니다. (제공자: {new_settings.get('providerType', 'openai')})")
            
        except Exception as e:
            logger.error(f"설정 업데이트 중 오류 발생: {str(e)}")
            raise

    def extract_difficulty(self, llm_response: str) -> str:
        """
        LLM 응답에서 난이도 추천을 추출합니다.
        
        Args:
            llm_response (str): LLM의 전체 응답 텍스트
            
        Returns:
            str: 추출된 난이도 값 ("Again", "Hard", "Good", "Easy" 중 하나)
                 추출 실패 시 빈 문자열 반환
        """
        try:
            if not llm_response:
                logging.error("LLM 응답이 비어있습니다.")
                return ""
            
            logging.debug(f"LLM 응답 처리 시작:\n{llm_response[:200]}...")
            
            # JSON 블록을 찾기 위한 정규식
            pattern = r'\{[^{]*"recommendation"\s*:\s*"([^"]+)"[^}]*\}\s*$'
            match = re.search(pattern, llm_response, re.DOTALL)
            
            if match:
                recommendation = match.group(1).strip()
                logging.debug(f"추출된 난이도: {recommendation}")
                
                # 유효한 난이도 값인지 확인
                valid_recommendations = ["Again", "Hard", "Good", "Easy"]
                if recommendation in valid_recommendations:
                    return recommendation
                else:
                    logging.error(f"잘못된 난이도 값: {recommendation}")
            else:
                logging.error("추천 JSON 블록을 찾을 수 없습니다.")
                logging.debug(f"응답의 마지막 부분:\n{llm_response[-200:]}")
            
            return ""
            
        except Exception as e:
            logging.error(f"난이도 추출 중 오류 발생: {str(e)}")
            return ""

    def get_last_response(self) -> str:
        """마지막 LLM 응답을 반환합니다."""
        return self.last_response

    def get_elapsed_time(self) -> float:
        """답변에 걸린 시간을 반환합니다."""
        return self.elapsed_time if self.elapsed_time is not None else 0.0

    def set_answer_checker_window(self, window):
        """AnswerCheckerWindow 참조를 설정합니다."""
        self._answer_checker_window = window
        logger.debug("Answer Checker Window reference set")

logger.info("Bridge initialized")

def showInfo(message):
    """에러 메시지 표시를 위한 래퍼 함수"""
    try:
        from aqt.utils import showInfo as anki_showInfo
        if mw.thread() != QThread.currentThread():
            QTimer.singleShot(0, lambda: anki_showInfo(message))
        else:
            anki_showInfo(message)
    except Exception as e:
        logger.error(f"Error showing info dialog: {str(e)}")
