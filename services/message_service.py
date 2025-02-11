from typing import Optional, Dict, Any, List, Union, TypeVar, Protocol
from dataclasses import dataclass
from datetime import datetime
import logging
from enum import Enum, auto

logger = logging.getLogger(__name__)

class MessageType(Enum):
    SYSTEM = auto()
    USER = auto()
    ASSISTANT = auto()
    ERROR = auto()
    INFO = auto()

@dataclass
class Message:
    """메시지 데이터 클래스"""
    type: MessageType
    content: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None

class MessageService:
    """메시지 처리 서비스"""
    def __init__(self) -> None:
        self.messages: List[Message] = []
        self._setup_logging()

    def _setup_logging(self) -> None:
        """로깅 설정"""
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        logger.addHandler(handler)

    def add_message(
        self, 
        content: str, 
        msg_type: MessageType, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """새 메시지 추가"""
        try:
            message = Message(
                type=msg_type,
                content=content,
                timestamp=datetime.now(),
                metadata=metadata or {}
            )
            self.messages.append(message)
            logger.debug(f"Added message: {message}")
            return message
        except Exception as e:
            logger.error(f"Error adding message: {e}")
            raise

    def get_messages(
        self, 
        msg_type: Optional[MessageType] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> List[Message]:
        """메시지 조회"""
        try:
            filtered_messages = self.messages

            if msg_type:
                filtered_messages = [m for m in filtered_messages if m.type == msg_type]
            
            if start_time:
                filtered_messages = [m for m in filtered_messages if m.timestamp >= start_time]
            
            if end_time:
                filtered_messages = [m for m in filtered_messages if m.timestamp <= end_time]

            return filtered_messages
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
            return []

    def clear_messages(self, msg_type: Optional[MessageType] = None) -> None:
        """메시지 삭제"""
        try:
            if msg_type:
                self.messages = [m for m in self.messages if m.type != msg_type]
            else:
                self.messages.clear()
            logger.debug(f"Cleared messages: {msg_type if msg_type else 'all'}")
        except Exception as e:
            logger.error(f"Error clearing messages: {e}")
            raise

    def get_last_message(self, msg_type: Optional[MessageType] = None) -> Optional[Message]:
        """마지막 메시지 조회"""
        try:
            if msg_type:
                filtered = [m for m in reversed(self.messages) if m.type == msg_type]
                return filtered[0] if filtered else None
            return self.messages[-1] if self.messages else None
        except Exception as e:
            logger.error(f"Error getting last message: {e}")
            return None

    def format_message(self, message: Message) -> str:
        """메시지 포맷팅"""
        try:
            timestamp = message.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            return f"[{timestamp}] {message.type.name}: {message.content}"
        except Exception as e:
            logger.error(f"Error formatting message: {e}")
            return f"Error formatting message: {str(e)}"

    def get_conversation_history(
        self, 
        limit: Optional[int] = None,
        include_types: Optional[List[MessageType]] = None
    ) -> List[str]:
        """대화 기록 조회"""
        try:
            messages = self.messages
            if include_types:
                messages = [m for m in messages if m.type in include_types]
            if limit:
                messages = messages[-limit:]
            return [self.format_message(m) for m in messages]
        except Exception as e:
            logger.error(f"Error getting conversation history: {e}")
            return [] 