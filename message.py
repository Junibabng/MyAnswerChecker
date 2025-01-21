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

class Message:
    def __init__(
        self,
        content: str,
        message_type: MessageType,
        help_text: Optional[str] = None,
        model_name: Optional[str] = None
    ):
        self.content = content
        self.message_type = message_type
        self.help_text = help_text
        self.model_name = model_name
        self.timestamp = datetime.now()

    def to_html(self) -> str:
        """메시지를 HTML 형식으로 변환"""
        base_container_class = "message-container"
        base_message_class = "message"
        
        if self.message_type == MessageType.ERROR:
            container_html = f"""
            <div class="system-message-container error">
                <div class="system-message">
                    <p class="error-message" style="color: #e74c3c; margin-bottom: 8px;">{self.content}</p>
                    {f'<p class="help-text" style="color: #666; font-size: 0.9em;">{self.help_text}</p>' if self.help_text else ''}
                </div>
                <div class="message-time">{self.timestamp.strftime("%p %I:%M")}</div>
            </div>
            """
        elif self.message_type == MessageType.LLM:
            container_html = f"""
            <div class="system-message-container">
                <div class="model-info">{self.model_name or 'Unknown Model'}</div>
                <div class="system-message">
                    <p>{self.content}</p>
                </div>
                <div class="message-time">{self.timestamp.strftime("%p %I:%M")}</div>
            </div>
            """
        else:
            container_html = f"""
            <div class="{base_container_class} {self.message_type.value}-message-container">
                <div class="{base_message_class} {self.message_type.value}-message">
                    <p>{self.content}</p>
                </div>
                <div class="message-time">{self.timestamp.strftime("%p %I:%M")}</div>
            </div>
            """
        
        return container_html

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

def show_info(message: str):
    """정보 메시지를 표시"""
    showInfo(message) 