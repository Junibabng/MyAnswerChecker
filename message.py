from datetime import datetime
from enum import Enum
from typing import Optional
import logging
from aqt.utils import showInfo

logger = logging.getLogger(__name__)

class MessageType(Enum):
    SYSTEM = "system"
    USER = "user"
    ERROR = "error"
    LLM = "llm"
    REVIEW = "review"
    INFO = "info"
    QUESTION = "question"
    WELCOME = "welcome"
    DIFFICULTY_RECOMMENDATION = "difficulty_recommendation"

class Message:
    def __init__(
        self,
        content: str,
        message_type: MessageType,
        help_text: Optional[str] = None,
        model_name: Optional[str] = None,
        additional_classes: Optional[list] = None
    ):
        self.content = content
        self.message_type = message_type
        self.help_text = help_text
        self.model_name = model_name
        self.timestamp = datetime.now()
        self.additional_classes = additional_classes

    def to_html(self) -> str:
        """메시지를 HTML 형식으로 변환"""
        base_container_class = "message-container"
        base_message_class = "message"
        
        # 모든 메시지 타입에 대한 공통 템플릿
        container_html = f"""
        <div class="{base_container_class} {self.message_type.value}-message-container">
            {f'<div class="model-info">{self.model_name}</div>' if self.model_name else ''}
            <div class="{base_message_class} {self.message_type.value}-message">
                {self._get_message_content()}
            </div>
            <div class="message-time">{self.timestamp.strftime("오후 %I:%M")}</div>
        </div>
        """
        return container_html

    def _get_message_content(self) -> str:
        """메시지 타입에 따른 내용 생성"""
        if self.message_type == MessageType.WELCOME:
            return f"""
            <h3>✏️ Answer Checker</h3>
            <p>카드 리뷰를 진행해주세요. 답변을 입력하고 Enter 키를 누르거나 Send 버튼을 클릭하세요.</p>
            """
        
        elif self.message_type == MessageType.QUESTION:
            return f"""<div class="question-content">{self.content}</div>"""
        
        elif self.message_type == MessageType.DIFFICULTY_RECOMMENDATION:
            return self.content
        
        elif self.message_type == MessageType.ERROR:
            error_content = f'<p class="error-message">{self.content}</p>'
            if self.help_text:
                error_content += f'<p class="help-text">{self.help_text}</p>'
            return error_content
        
        else:
            return f"<p>{self.content}</p>"

class MessageManager:
    def __init__(self):
        self.messages = []
        
    def add_message(self, message: Message) -> str:
        """새 메시지를 추가하고 HTML을 반환"""
        self.messages.append(message)
        return message.to_html()
        
    def create_error_message(self, error_content: str, help_text: Optional[str] = None) -> Message:
        """에러 메시지 생성"""
        return Message(
            content=error_content,
            message_type=MessageType.ERROR,
            help_text=help_text
        )
        
    def create_system_message(self, content: str) -> Message:
        """시스템 메시지 생성"""
        return Message(
            content=content,
            message_type=MessageType.SYSTEM
        )
        
    def create_llm_message(self, content: str, model_name: str) -> Message:
        """LLM 메시지 생성"""
        return Message(
            content=content,
            message_type=MessageType.LLM,
            model_name=model_name
        )

    def create_info_message(self, content: str) -> Message:
        """정보 메시지 생성"""
        return Message(
            content=content,
            message_type=MessageType.INFO
        )
        
    def create_question_message(self, content: str, model_name: str = "Current Question") -> Message:
        """문제 표시용 메시지 생성"""
        return Message(
            content=content,
            message_type=MessageType.QUESTION,
            model_name=model_name
        )
        
    def create_review_message(self, recommendation: str) -> Message:
        """리뷰 권장 메시지 생성"""
        return Message(
            content=f"Recommended review interval: {recommendation}",
            message_type=MessageType.DIFFICULTY_RECOMMENDATION
        )
        
    def create_welcome_message(self):
        """웰컴 메시지 생성"""
        welcome_content = """
        <h3>✏️ Answer Checker</h3>
        <p style='color: #666; font-size: 0.9em;'>
            카드 리뷰를 진행해주세요. 답변을 입력하고 Enter 키를 누르거나 Send 버튼을 클릭하세요.
        </p>
        """
        return Message(
            content=welcome_content,
            message_type=MessageType.WELCOME,
            additional_classes=["welcome-message"]
        )
        
    def clear_messages(self):
        """모든 메시지 초기화"""
        self.messages.clear()

    def handle_response_error(self, error_message: str, error_detail: Optional[str] = None) -> str:
        """에러 응답 처리"""
        error_msg = self.create_error_message(
            error_content=error_message,
            help_text=error_detail
        )
        return self.add_message(error_msg)

    def process_complete_response(self, response_text: str, model_name: str) -> str:
        """완료된 응답 처리"""
        response_msg = self.create_llm_message(
            content=response_text,
            model_name=model_name
        )
        return self.add_message(response_msg)

    def create_difficulty_message(self, recommendation: str) -> Message:
        """난이도 추천 메시지 생성"""
        return Message(
            content=f"LLM의 추천에 따라 <span class='recommendation {self.get_recommendation_class(recommendation)}'>{recommendation}</span> 난이도로 평가했습니다.",
            message_type=MessageType.DIFFICULTY_RECOMMENDATION,
            additional_classes=["difficulty-message"]
        )

    @staticmethod
    def get_recommendation_class(recommendation: str) -> str:
        """추천 유형에 따른 CSS 클래스 반환"""
        return {
            "Again": "recommendation-again",
            "Hard": "recommendation-hard",
            "Good": "recommendation-good",
            "Easy": "recommendation-easy"
        }.get(recommendation, "")

def show_info(message: str):
    """정보 메시지를 표시"""
    showInfo(message) 