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

class Bridge(QObject):
    # Constants
    RESPONSE_TIMEOUT = 10  # seconds
    DEFAULT_TEMPERATURE = 0.2
    
    # Signal definitions
    sendResponse = pyqtSignal(str)
    sendQuestionResponse = pyqtSignal(str)
    sendJokeResponse = pyqtSignal(str)
    sendEditAdviceResponse = pyqtSignal(str)
    timer_signal = pyqtSignal(str)
    stream_data_received = pyqtSignal(str, str, str)
    model_info_changed = pyqtSignal()  # New signal for model info updates

    def __init__(self, parent=None):
        super().__init__(parent)
        self._initialize_attributes()
        self._setup_timer()
        self.update_llm_provider()
        self.partial_response = ""  # JSON 버퍼 추가

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
        error_html = "<p>Response time exceeded. Please try again.</p>"
        if answer_checker_window:
            answer_checker_window.web_view.setHtml(answer_checker_window.default_html + error_html)
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
            complete_json = self.partial_response + response_text
            response_json = json.loads(complete_json)
            self.partial_response = ""  # 성공적으로 로드되면 버퍼 초기화
            html_content = self._generate_response_html(response_json)
            if answer_checker_window:
                answer_checker_window.web_view.setHtml(answer_checker_window.default_html + html_content)
            return True
        except json.JSONDecodeError:
            # JSON이 완전하지 않으면 버퍼에 추가
            self.partial_response += response_text
            logger.warning("Incomplete JSON received, buffering...")
            return False
        except Exception:
            # 기타 예외 처리
            logger.exception("예기치 않은 오류")
            self._clear_request_data(request_id)

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
        
        # Update buffer
        self.response_buffer[request_id] += chunk
        wait_time = time.time() - self.response_wait_timers[request_id]
        
        # Handle timeout
        if wait_time > self.RESPONSE_TIMEOUT:
            self._handle_response_timeout(request_id, data_type)
            return
        
        # Process response based on type
        if data_type == "response":
            if self.is_complete_response(self.response_buffer[request_id]):
                if self._process_complete_response(self.response_buffer[request_id]):
                    self._clear_request_data(request_id)
        elif data_type in ["question", "joke", "edit_advice"]:
            if answer_checker_window:
                answer_checker_window.web_view.setHtml(
                    answer_checker_window.default_html + 
                    self.markdown_to_html(self.response_buffer[request_id])
                )

    def is_complete_response(self, response_text):
        """
        응답이 완전한 JSON을 포함하는지 확인합니다.
        
            response_text (str): 확인할 텍스트
            
        Returns:
            bool: 응답이 완전하면 True, 아니면 False
        """
        try:
            # 1. 예시 JSON과 설명 텍스트 제거
            response_text = re.sub(r'```json\s*{\s*"[^"]+"\s*:\s*"\.\.\."\s*[,}][\s\S]*?```', '', response_text)
            response_text = re.sub(r'\*\*.*?\*\*', '', response_text)
            response_text = re.sub(r'{{c\d+::.*?}}', '', response_text)
            
            # 2. JSON 찾기
            patterns = [
                # 완전한 코드 블록
                r'```(?:json)?\s*({[^{]*?"evaluation"\s*:\s*"[^"]*?"\s*,\s*"recommendation"\s*:\s*"(?:Again|Hard|Good|Easy)"\s*,\s*"answer"\s*:\s*"[^"]*?"\s*,\s*"reference"\s*:\s*"[^"]*?"\s*})\s*```',
                # 시작 코드 블록만 있는 경우
                r'```(?:json)?\s*({[^{]*?"evaluation"\s*:\s*"[^"]*?"\s*,\s*"recommendation"\s*:\s*"(?:Again|Hard|Good|Easy)"\s*,\s*"answer"\s*:\s*"[^"]*?"\s*,\s*"reference"\s*:\s*"[^"]*?"\s*})\s*$',
                # JSON만 있는 경우
                r'(?:^|\s)({[^{]*?"evaluation"\s*:\s*"[^"]*?"\s*,\s*"recommendation"\s*:\s*"(?:Again|Hard|Good|Easy)"\s*,\s*"answer"\s*:\s*"[^"]*?"\s*,\s*"reference"\s*:\s*"[^"]*?"\s*})'
            ]
            
            for pattern in patterns:
                matches = list(re.finditer(pattern, response_text, re.DOTALL))
                if matches:
                    # 마지막 매치 사용
                    cleaned_text = matches[-1].group(1).strip()
                    
                    # JSON 파싱
                    parsed_json = json.loads(cleaned_text)
                    
                    # 필수 필드 확인
                    required_fields = ["evaluation", "recommendation", "answer", "reference"]
                    if not all(field in parsed_json for field in required_fields):
                        logger.debug(f"Missing required fields in JSON: {parsed_json.keys()}")
                        continue
                    
                    # recommendation 값 검증
                    valid_recommendations = ["Again", "Hard", "Good", "Easy"]
                    if parsed_json["recommendation"] not in valid_recommendations:
                        logger.debug(f"Invalid recommendation value: {parsed_json['recommendation']}")
                        continue
                    
                    return True
            
            logger.debug("No valid JSON pattern found in response")
            return False
            
        except (json.JSONDecodeError, AttributeError, IndexError) as e:
            logger.debug(f"Response incomplete: {str(e)}")
            return False

    def update_llm_provider(self):
        settings = QSettings("LLM_response_evaluator", "Settings")
        provider_type = settings.value("providerType", "openai")
        self.temperature = float(settings.value("temperature", "0.2"))
        
        if provider_type == "openai":
            api_key = settings.value("openaiApiKey", "")
            base_url = settings.value("baseUrl", "https://api.openai.com")
            model_name = settings.value("modelName", "gpt-4o-mini")
            self.llm_provider = OpenAIProvider(api_key, base_url, model_name)
        elif provider_type == "gemini":
            api_key = settings.value("geminiApiKey", "")
            model_name = settings.value("geminiModel", "gemini-2.0-flash-exp")
            self.llm_provider = GeminiProvider(api_key, model_name)

        # Emit signal to update UI
        self.model_info_changed.emit()

    def call_llm_api(self, system_message, user_message_content, max_retries=3):
        """Calls the selected LLM API to get a response."""
        settings = QSettings("LLM_response_evaluator", "Settings")
        api_key = settings.value("apiKey", "")
        temperature = float(settings.value("temperature", "0.2"))

        if not api_key:
            return "API Key is not set."

        if not self.llm_provider:
            self.update_llm_provider()

        for attempt in range(max_retries):
            try:
                return self.llm_provider.call_api(system_message, user_message_content, temperature=temperature)
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
                    return
                self.current_card_id = current_card.id
                
            logger.debug("Received answer from JS: %s", user_answer)
            try:
                # 설정값 로깅 추가
                settings = QSettings("LLM_response_evaluator", "Settings")
                easy_threshold = int(settings.value("easyThreshold", "5"))
                good_threshold = int(settings.value("goodThreshold", "15"))
                hard_threshold = int(settings.value("hardThreshold", "50"))
                
                logger.debug(f"Current threshold settings - Easy: {easy_threshold}s, Good: {good_threshold}s, Hard: {hard_threshold}s")
                
                card_content, card_answers, card_ord = self.get_card_content()
                if not card_content:
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
                response = json.dumps({"evaluation": "Error occurred", "recommendation": "None", "answer": "", "reference": ""})
                self.sendResponse.emit(response)
        finally:
            self.is_processing = False

    def create_llm_message(self, card_content, card_answers, question, request_type):
        """Creates the message to be sent to the LLM API."""
        try:
            card = mw.reviewer.card
            note = card.note()
            model = note.model()
            model_type = model.get('type')

            settings = QSettings("LLM_response_evaluator", "Settings")
            easy_threshold = int(settings.value("easyThreshold", "5"))
            good_threshold = int(settings.value("goodThreshold", "15"))
            hard_threshold = int(settings.value("hardThreshold", "50"))
            elapsed_time = self.llm_data.get("elapsed_time")
            language = settings.value("language", "English")

            # Clean content
            soup_content = BeautifulSoup(card_content, 'html.parser')
            clean_content = soup_content.get_text()
            
            # Format answers as a comma-separated list
            formatted_answers = ", ".join(card_answers) if isinstance(card_answers, list) else str(card_answers)
            logger.debug(f"Formatted answers for LLM: {formatted_answers}")

            # Create common context data
            context_data = f"""
            Context about this Anki card:
            Card Content: {clean_content}
            Correct Answer(s): {formatted_answers}
            User's Previous Answer: {self.last_user_answer or 'Not available'}
            Time Taken: {self.last_elapsed_time or 'Not available'} seconds
            Previous Evaluation: {self.last_response.get('evaluation', 'Not available') if self.last_response else 'Not available'}
            Previous Recommendation: {self.last_response.get('recommendation', 'Not available') if self.last_response else 'Not available'}
            """

            # request_type별 특화된 프롬프트와 시스템 메시지
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

                    Please provide evaluation in JSON format:
                    {{
                        "evaluation": "Detailed assessment focusing on semantic accuracy and time",
                        "recommendation": "{DIFFICULTY_AGAIN}, {DIFFICULTY_HARD}, {DIFFICULTY_GOOD}, {DIFFICULTY_EASY}",
                        "answer": "The correct answer(s) and acceptable variations",
                        "reference": "Additional helpful information including standard forms"
                    }}
                    """
                },
                "question": {
                    "system": f"You are a helpful assistant. Always answer in {language}.",
                    "content": f"{context_data}\n\nAdditional Question: {question}\n\nBased on all this context, please provide a detailed answer to the additional question."
                },
                "joke": {
                    "system": f"You are a comedian. Always answer in {language}.",
                    "content": f"{context_data}\n\nBased on this context and especially considering how well the user performed, please create a funny and encouraging joke related to this card's content."
                },
                "edit_advice": {
                    "system": f"You are an Anki card editing expert. Always answer in {language}.",
                    "content": f"{context_data}\n\nBased on the user's performance and all available context, please provide detailed, actionable advice for improving this card."
                }
            }

            selected_type = type_specific_content.get(request_type, {
                "system": f"You are a helpful assistant. Always answer in {language}.",
                "content": "Invalid request type"
            })

            return selected_type["system"], selected_type["content"]
        except Exception as e:
            logger.exception("Error creating LLM message: %s", e)
            return "Error creating LLM message", "Error creating LLM message"

    def process_answer(self):
        """Calls the OpenAI API in a background thread to get the evaluation."""
        try:
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

            json_text = None
            max_attempts = 3
            for attempt in range(max_attempts):
                json_text = self.extract_json_from_text(response_text)
                if json_text:
                    logger.debug(f"JSON extraction successful (Attempt: {attempt + 1}): {json_text}")
                    break
                logger.debug(f"JSON extraction failed (Attempt: {attempt + 1})")
            
            if json_text:
                try:
                    response_json = json.loads(json_text)
                    evaluation = response_json.get("evaluation", "No evaluation")
                    recommendation = response_json.get("recommendation", "No recommendation")
                    
                    # Process answer as comma-separated list
                    answer = response_json.get("answer", "")
                    if answer:
                        # Remove bullet points and split by newlines or commas
                        answer_parts = []
                        for part in re.split(r'[,\n]', answer):
                            part = part.strip()
                            if part:
                                # Remove bullet points and other markers
                                part = re.sub(r'^[•\-\*]\s*', '', part)
                                answer_parts.append(part)
                        answer = ', '.join(answer_parts)
                    
                    reference = response_json.get("reference", "")
                    
                    # 응답, 사용자 답변, 소요 시간 저장
                    self.last_response = response_json
                    self.last_user_answer = self.llm_data.get("user_answer", "")
                    self.last_elapsed_time = self.llm_data.get("elapsed_time", "")
                    
                    response = json.dumps({
                        "evaluation": self.markdown_to_html(evaluation),
                        "recommendation": self.markdown_to_html(recommendation),
                        "answer": answer,
                        "reference": self.markdown_to_html(reference)
                    })
                    QMetaObject.invokeMethod(
                        self,
                        "sendResponse",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, response)
                    )
                except json.JSONDecodeError as e:
                    logger.error(f"Could not parse OpenAI response as JSON: {e}")
                    showInfo("Could not parse OpenAI response as JSON. Please try asking for the answer again.")
                    response = json.dumps({
                        "evaluation": "Parsing error",
                        "recommendation": None,
                        "answer": "",
                        "reference": ""
                    })
                    QMetaObject.invokeMethod(
                        self,
                        "sendResponse",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, response)
                    )
            else:
                logger.error("Could not find JSON pattern")
                showInfo("Could not find JSON pattern in OpenAI response. Please try asking for the answer again.")
                response = json.dumps({
                    "evaluation": "JSON pattern error",
                    "recommendation": None,
                    "answer": "",
                    "reference": ""
                })
                QMetaObject.invokeMethod(
                    self,
                    "sendResponse",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, response)
                )
        except Exception as e:
            logger.exception("Error processing OpenAI API: %s", e)
            response = json.dumps({
                "evaluation": "Error occurred",
                "recommendation": "None",
                "answer": "",
                "reference": ""
            })
            QMetaObject.invokeMethod(
                self,
                "sendResponse",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, response)
            )
        finally:
            self._clear_llm_data()

    def process_question(self, card_content, question, card_answers):
        """Generates an answer to an additional question."""
        try:
            logger.debug("=== Processing Additional Question ===")
            logger.debug(f"Question: {question}")
            logger.debug(f"Current context length: {len(self.conversation_history['messages'])}")
            
            # Update conversation history
            if self.current_card_id != self.conversation_history['current_card_id']:
                logger.debug("New card detected - clearing conversation history")
                self.conversation_history['messages'] = []
                self.conversation_history['card_context'] = {
                    'content': card_content,
                    'answers': card_answers
                }
                self.conversation_history['current_card_id'] = self.current_card_id
            
            # Add user question to history
            self.conversation_history['messages'].append({
                'role': 'user',
                'content': question
            })
            
            # Build conversation context
            context_messages = []
            if self.conversation_history['card_context']:
                context_messages.append(f"Card Content: {self.conversation_history['card_context']['content']}")
                context_messages.append(f"Correct Answer(s): {self.conversation_history['card_context']['answers']}")
            
            for msg in self.conversation_history['messages'][-self.max_context_length:]:
                context_messages.append(f"{msg['role'].title()}: {msg['content']}")
            
            context = "\n".join(context_messages)
            logger.debug(f"Built conversation context (truncated): {context[:200]}...")
            
            # Get response from LLM
            system_message = f"You are a helpful assistant. Previous conversation:\n{context}"
            response = self.call_llm_api(system_message, question)
            
            # Add assistant response to history
            self.conversation_history['messages'].append({
                'role': 'assistant',
                'content': response
            })
            
            # Emit response
            response_json = json.dumps({"answer": response})
            logger.debug(f"Sending response (truncated): {response[:200]}...")
            
            QMetaObject.invokeMethod(
                self,
                "sendQuestionResponse",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, response_json)
            )
            
        except Exception as e:
            logger.exception("Error processing additional question: %s", e)
            error_json = json.dumps({"error": str(e)})
            QMetaObject.invokeMethod(
                self,
                "sendQuestionResponse",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, error_json)
            )

    def clear_conversation_history(self):
        """Clears the conversation history"""
        logger.debug("Clearing conversation history")
        self.conversation_history = {
            'messages': [],
            'card_context': None,
            'current_card_id': None
        }

    def _get_chat_content(self):
        """Get formatted chat content for context"""
        messages = []
        for msg in self.conversation_history['messages']:
            messages.append(f"{msg['role'].title()}: {msg['content']}")
        return "\n".join(messages)

    def process_joke_request(self, card_content, card_answers):
        """Handles a joke generation request."""
        def thread_func():
            try:
                system_message, user_message_content = self.create_llm_message(
                    card_content, 
                    card_answers, 
                    None, 
                    "joke"
                )
                
                response = self.call_llm_api(system_message, user_message_content)
                response_json = json.dumps({"joke": response})
                
                QMetaObject.invokeMethod(
                    self,
                    "sendJokeResponse",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, response_json)
                )
            except Exception as e:
                logger.exception("Error generating joke: %s", e)
                error_json = json.dumps({"error": str(e)})
                QMetaObject.invokeMethod(
                    self,
                    "sendJokeResponse",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, error_json)
                )

        # 별도 스레드에서 실행
        thread = threading.Thread(target=thread_func)
        thread.start()

    def process_edit_advice_request(self, card_content, card_answers):
        """Handles a card edit advice request."""
        def thread_func():
            try:
                system_message, user_message_content = self.create_llm_message(
                    card_content, 
                    card_answers, 
                    None, 
                    "edit_advice"
                )
                
                response = self.call_llm_api(system_message, user_message_content)
                # edit_advice 키로 간단화된 응답 구조
                response_json = json.dumps({"edit_advice": response})
                
                QMetaObject.invokeMethod(
                    self,
                    "sendEditAdviceResponse",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, response_json)
                )
            except Exception as e:
                logger.exception("Error generating card edit advice: %s", e)
                error_json = json.dumps({"error": str(e)})
                QMetaObject.invokeMethod(
                    self,
                    "sendEditAdviceResponse",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, error_json)
                )

        thread = threading.Thread(target=thread_func)
        thread.start()

    def extract_json_from_text(self, text):
        """Extracts the last JSON part from the text."""
        try:
            # Remove code block markers and clean text
            text = self._clean_text(text)
            
            # Find and validate JSON
            json_str = self._find_valid_json(text)
            if json_str:
                return json_str
            
            return None
        except Exception as e:
            logger.error(f"Error in extract_json_from_text: {str(e)}")
            return None

    def _clean_text(self, text):
        """Clean text by removing code block markers"""
        return text.replace('```json', '').replace('```', '').strip()

    def _find_valid_json(self, text):
        """Find and validate JSON in text"""
        try:
            # 코드 블록 마커 제거
            text = re.sub(r'```json\s*|\s*```', '', text)
            
            # JSON 패턴 찾기
            patterns = [
                # 완전한 JSON 객체
                r'({[^{}]*"evaluation"\s*:[^{}]*"recommendation"\s*:[^{}]*"answer"\s*:[^{}]*"reference"\s*:[^{}]*})',
                # 중첩된 중괄호를 포함할 수 있는 더 일반적인 패턴
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
            
            # JSON을 찾지 못한 경우
            logger.error("No valid JSON pattern found in response")
            logger.debug(f"Raw text: {text[:200]}...")  # 처음 200자만 로깅
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
        """Validate required fields in parsed JSON"""
        required_fields = ["evaluation", "recommendation", "answer"]
        if not all(field in parsed_json for field in required_fields):
            logger.debug(f"Missing required fields in JSON: {parsed_json.keys()}")
            return False
        return True

    def get_card_content(self):
        """Returns the current card's content and answer."""
        try:
            card = mw.reviewer.card
            if not card:
                return None, None, None

            note = card.note()
            card_ord = card.ord
            model = note.model()
            model_type = model.get('type')

            if model_type == 1:  # Cloze card
                return self._process_cloze_card(note, card_ord)
            else:  # Basic card
                return self._process_basic_card(card)

        except Exception as e:
            logger.exception("Failed to get card content: %s", e)
            return None, None, None

    def _process_cloze_card(self, note, card_ord):
        """Process cloze card content and extract answer"""
        content = note.fields[0]
        clean_content = BeautifulSoup(content, 'html.parser').get_text()
        
        current_cloze_number = card_ord + 1
        cloze_pattern = re.compile(r'\{\{c' + str(current_cloze_number) + r'::(.*?)\}\}')
        matches = cloze_pattern.findall(content)
        
        if matches:
            card_answers = [matches[0]]
            logger.debug(f"Cloze card #{current_cloze_number} - Content: {clean_content}, Answer: {card_answers[0]}")
        else:
            card_answers = []
            logger.debug(f"No answer found for cloze #{current_cloze_number}")
        
        return clean_content, card_answers, card_ord

    def _process_basic_card(self, card):
        """Process basic card content and extract answer"""
        question = self._extract_question(card)
        card_answers = self._extract_answer(card)
        
        return question, card_answers, None

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
        text.replace('\n', '<br>')
        return text
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
