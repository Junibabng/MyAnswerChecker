import requests
import logging
import os
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime
import random
import re
from typing import Optional, Any, Dict, List, Generator, Callable, TypeVar, Union, cast, Protocol
import concurrent.futures
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

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

class LLMProviderError(Exception):
    """LLM 프로바이더 관련 기본 예외 클래스"""
    def __init__(self, message, help_text=None):
        super().__init__(message)
        self.help_text = help_text or "나중에 다시 시도해 주세요."

class APIConnectionError(LLMProviderError):
    """API 연결 관련 예외"""
    def __init__(self, message):
        help_texts = {
            "timeout": "인터넷 연결을 확인하고 다시 시도해 주세요.",
            "rate_limit": "잠시 후에 다시 시도해 주세요.",
            "connection": "인터넷 연결 상태를 확인해 주세요."
        }
        
        if "시간이 초과" in message:
            help_text = help_texts["timeout"]
        elif "한도를 초과" in message:
            help_text = help_texts["rate_limit"]
        else:
            help_text = help_texts["connection"]
            
        super().__init__(f"AI 서버 연결에 실패했습니다: {message}", help_text)

class APIResponseError(LLMProviderError):
    """API 응답 처리 관련 예외"""
    def __init__(self, message):
        help_texts = {
            "empty": "다시 한 번 시도해 주세요. 문제가 계속되면 설정에서 다른 AI 모델을 선택해보세요.",
            "format": "잠시 후 다시 시도해 주세요. 문제가 계속되면 설정에서 다른 AI 모델을 선택해보세요."
        }
        
        if "빈 응답" in message:
            help_text = help_texts["empty"]
        else:
            help_text = help_texts["format"]
            
        super().__init__(f"AI 응답을 처리할 수 없습니다: {message}", help_text)

class InvalidAPIKeyError(LLMProviderError):
    """잘못된 API 키 관련 예외"""
    def __init__(self, message):
        help_text = "설정 메뉴에서 API 키를 확인하고 올바르게 입력해 주세요."
        super().__init__("API 키가 올바르지 않습니다", help_text)

class RetryWithExponentialBackoff:
    """지수 백오프를 사용한 재시도 데코레이터"""
    def __init__(self, max_retries=3, base_delay=1, max_delay=8):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay

    def __call__(self, func):
        def wrapper(*args, **kwargs):
            retry_count = 0
            last_error = None
            
            while retry_count < self.max_retries:
                try:
                    logger.debug(
                        f"API 요청 시도 {retry_count + 1}/{self.max_retries}\n"
                        f"Function: {func.__name__}\n"
                        f"Args: {args}\n"
                        f"Kwargs: {kwargs}"
                    )
                    return func(*args, **kwargs)
                    
                except requests.exceptions.RequestException as e:
                    retry_count += 1
                    last_error = e
                    
                    error_context = {
                        'attempt': retry_count,
                        'max_retries': self.max_retries,
                        'function': func.__name__,
                        'args': args,
                        'kwargs': kwargs
                    }
                    
                    if retry_count == self.max_retries:
                        log_error(e, error_context)
                        raise APIConnectionError(f"API 연결 실패: {str(e)}")
                    
                    delay = min(self.base_delay * (2 ** (retry_count - 1)), self.max_delay)
                    logger.warning(
                        f"API 호출 실패 (시도 {retry_count}/{self.max_retries})\n"
                        f"Error: {str(e)}\n"
                        f"Delay: {delay}초 후 재시도"
                    )
                    time.sleep(delay)
                    
            return None
        return wrapper

@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 8.0

class APIResponse(Protocol):
    """API 응답을 위한 프로토콜"""
    status_code: int
    text: str
    json: Callable[[], Dict[str, Any]]

# Define TypeVar for generic type
T = TypeVar('T')

class LLMProvider(ABC):
    """LLM 서비스 호출을 위한 추상 기본 클래스"""
    def __init__(self) -> None:
        self.retry_config: RetryConfig = RetryConfig()
        self.thread_pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=3)
        self._setup_logging()

    def _setup_logging(self) -> None:
        """로깅 설정"""
        logger.setLevel(logging.DEBUG)
        file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s\n'
            'File: %(filename)s:%(lineno)d\n'
            'Function: %(funcName)s\n'
            'Message: %(message)s\n'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    @abstractmethod
    def call_api(self, system_message: str, user_message: str, temperature: float = 0.2) -> str:
        """LLM API를 호출하여 응답을 받아옵니다."""
        pass

    def _retry_with_exponential_backoff(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """지수 백오프를 사용한 재시도 로직"""
        retry_count = 0
        last_error: Optional[Exception] = None
        
        while retry_count < self.retry_config.max_retries:
            try:
                logger.debug(
                    f"API 요청 시도 {retry_count + 1}/{self.retry_config.max_retries}\n"
                    f"Function: {func.__name__}\n"
                    f"Args: {args}\n"
                    f"Kwargs: {kwargs}"
                )
                return func(*args, **kwargs)
                
            except requests.exceptions.RequestException as e:
                retry_count += 1
                last_error = e
                
                error_context = {
                    'attempt': retry_count,
                    'max_retries': self.retry_config.max_retries,
                    'function': func.__name__,
                    'args': args,
                    'kwargs': kwargs
                }
                
                if retry_count == self.retry_config.max_retries:
                    log_error(e, error_context)
                    raise APIConnectionError(f"API 연결 실패: {str(e)}")
                
                delay = min(self.retry_config.base_delay * (2 ** (retry_count - 1)), self.retry_config.max_delay)
                logger.warning(
                    f"API 호출 실패 (시도 {retry_count}/{self.retry_config.max_retries})\n"
                    f"Error: {str(e)}\n"
                    f"Delay: {delay}초 후 재시도"
                )
                time.sleep(delay)
        
        if last_error:
            raise APIConnectionError(f"최대 재시도 횟수 초과: {str(last_error)}")
        return cast(T, None)

    def _make_api_request(
        self, 
        headers: Dict[str, str], 
        data: Dict[str, Any], 
        url: Optional[str] = None
    ) -> APIResponse:
        """API 요청을 보내고 응답을 받아옵니다."""
        try:
            if url is None:
                raise ValueError("API URL이 지정되지 않았습니다.")

            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            return response

        except requests.exceptions.HTTPError as e:
            if response.status_code == 401:
                raise InvalidAPIKeyError("API 키가 올바르지 않습니다")
            elif response.status_code == 429:
                raise APIConnectionError("API 호출 한도를 초과했습니다")
            else:
                raise APIConnectionError(f"HTTP 오류 발생: {str(e)}")

        except requests.exceptions.ConnectionError as e:
            raise APIConnectionError(f"서버 연결 실패: {str(e)}")

        except requests.exceptions.Timeout as e:
            raise APIConnectionError(f"요청 시간 초과: {str(e)}")

        except requests.exceptions.RequestException as e:
            raise APIConnectionError(f"API 요청 중 오류 발생: {str(e)}")

    def _execute_async(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> Future[T]:
        """비동기 작업 실행"""
        return self.thread_pool.submit(func, *args, **kwargs)

    def cleanup(self) -> None:
        """리소스 정리"""
        self.thread_pool.shutdown(wait=True)

class OpenAIProvider(LLMProvider):
    """OpenAI API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, base_url, model, temperature=0.7):
        super().__init__()
        if not api_key:
            logger.error("API 키가 제공되지 않음")
            raise InvalidAPIKeyError("API 키가 제공되지 않았습니다.")
        
        logger.info(
            f"OpenAI 프로바이더 초기화:\n"
            f"Model: {model}\n"
            f"Temperature: {temperature}\n"
            f"Base URL: {base_url}"
        )
        
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model
        self.temperature = temperature
        self.system_prompt = "You are a helpful assistant."

    def set_system_prompt(self, prompt):
        logger.debug(f"시스템 프롬프트 설정: {prompt}")
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=None):
        """LLM API를 호출하여 응답을 받아옵니다."""
        try:
            logger.debug(
                "API 호출 준비:\n"
                f"System Message: {system_message}\n"
                f"Temperature: {temperature if temperature is not None else self.temperature}"
            )
            
            messages = [
                {"role": "user", "content": user_message}
            ]
            
            return self._retry_with_exponential_backoff(
                self.generate_response,
                messages,
                temperature
            )
            
        except Exception as e:
            log_error(e, {
                'system_message': system_message,
                'temperature': temperature
            })
            raise

    def generate_response(self, messages, temperature=None):
        """API 응답을 생성하고 처리합니다."""
        try:
            # temperature가 None이면 클래스의 temperature 값 사용
            if temperature is None:
                temperature = self.temperature
                
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }

            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": self.system_prompt}
                ] + messages,
                "temperature": temperature
            }

            # URL 생성
            url = f"{self.base_url}/v1/chat/completions"
            # URL 마스킹 처리
            masked_url = re.sub(r'(key=)([^&]+)', r'\1****', url) if 'key=' in url else url
            
            logger.debug(
                "응답 생성 시작:\n"
                f"Model: {self.model_name} (Endpoint: {masked_url})\n"
                f"Temperature: {temperature}\n"
                f"Message Count: {len(messages)}"
            )

            response = self._make_api_request(headers, payload, url)
            
            # 응답 처리
            if response.status_code != 200:
                logger.error(f"API returned non-200 status code: {response.status_code}")
                raise APIConnectionError(f"API returned status code {response.status_code}")

            result = response.json()
            
            # OpenAI API response format
            if isinstance(result, dict):
                if 'choices' in result and result['choices']:
                    content = result['choices'][0]['message']['content'].strip()
                    logger.debug(f"생성된 응답: {content[:200]}...")
                    return content
                    
            logger.error(f"Unexpected API response format: {result}")
            raise APIConnectionError("응답 형식이 올바르지 않습니다.")
            
        except (ValueError, KeyError, AttributeError) as e:
            error_context = {
                'result': locals().get('result'),
                'model': self.model_name,
                'temperature': temperature
            }
            log_error(e, error_context)
            raise APIResponseError("AI 응답의 형식이 올바르지 않습니다.")
        except Exception as e:
            error_context = {
                'model': self.model_name,
                'temperature': temperature,
                'message_count': len(messages) if 'messages' in locals() else 0
            }
            log_error(e, error_context)
            raise APIConnectionError("예기치 않은 오류가 발생했습니다.")

class GeminiProvider(LLMProvider):
    """Gemini API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp", temperature=0.7):
        super().__init__()
        if not api_key:
            logger.error("API 키가 제공되지 않음")
            raise InvalidAPIKeyError("API 키가 필요합니다.")
            
        # API 키 리스트 생성 및 초기화
        self.api_keys = [key.strip() for key in api_key.split(',') if key.strip()]
        if not self.api_keys:
            raise InvalidAPIKeyError("유효한 API 키가 없습니다.")
            
        # 사용할 API 키 순서 초기화
        self.api_key_queue = []
        self._refresh_api_key_queue()
            
        logger.info(
            f"Gemini 프로바이더 초기화:\n"
            f"Model: {model_name}\n"
            f"Temperature: {temperature}\n"
            f"API Keys Count: {len(self.api_keys)}"
        )
            
        self.model_name = model_name
        self.temperature = temperature
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        self.system_prompt = None

    def _refresh_api_key_queue(self):
        """API 키 큐를 새로 생성하고 무작위로 섞습니다."""
        self.api_key_queue = self.api_keys.copy()
        random.shuffle(self.api_key_queue)
        # 각 API 키의 마지막 4자리 로깅
        key_list = [f"...{key[-4:]}" if len(key) > 4 else "****" for key in self.api_key_queue]
        logger.info(f"=== API 키 큐 새로 생성됨 (총 {len(self.api_key_queue)}개) ===")
        logger.info(f"새로운 API 키 순서: {', '.join(key_list)}")

    def _get_next_api_key(self):
        """다음 사용할 API 키를 가져옵니다."""
        if not self.api_key_queue:
            self._refresh_api_key_queue()
        api_key = self.api_key_queue.pop()
        # API 키의 마지막 4자리만 로깅
        masked_key = f"...{api_key[-4:]}" if len(api_key) > 4 else "****"
        logger.info(f"=== API 키 사용 ===")
        logger.info(f"Current API Key: {masked_key}")
        logger.info(f"남은 키: {len(self.api_key_queue)}개")
        return api_key

    def set_system_prompt(self, prompt):
        logger.debug(f"시스템 프롬프트 설정: {prompt}")
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=None):
        """LLM API를 호출하여 응답을 받아옵니다."""
        try:
            logger.info("=== API 호출 시작 ===")
            messages = [{"role": "user", "content": user_message}]
            
            # API 키 선택 및 응답 생성
            current_api_key = self._get_next_api_key()
            response = self.generate_response(messages, temperature, current_api_key)
            
            logger.info("=== API 호출 완료 ===")
            return response
            
        except Exception as e:
            logger.error(f"=== API 호출 실패 ===\n{str(e)}")
            raise

    def generate_response(self, messages, temperature=None, api_key=None):
        try:
            if api_key is None:
                api_key = self._get_next_api_key()
                
            # temperature가 None이면 클래스의 temperature 값 사용
            if temperature is None:
                temperature = self.temperature
                
            url = f"{self.base_url}/{self.model_name}:generateContent?key={api_key}"
            
            headers = {
                "Content-Type": "application/json"
            }

            combined_message = f"{self.system_prompt}\n\n"
            for message in messages:
                combined_message += f"{message['content']}\n"

            data = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": combined_message}]
                    }
                ],
                "generationConfig": {
                    "temperature": temperature,
                    "topK": 40,
                    "topP": 0.95,
                    "maxOutputTokens": 8192,
                    "responseMimeType": "text/plain"
                },
                "safetySettings": [
                    {
                        "category": "HARM_CATEGORY_HARASSMENT",
                        "threshold": "OFF"
                    },
                    {
                        "category": "HARM_CATEGORY_HATE_SPEECH",
                        "threshold": "OFF"
                    },
                    {
                        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                        "threshold": "OFF"
                    },
                    {
                        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                        "threshold": "OFF"
                    },
                    {
                        "category": "HARM_CATEGORY_CIVIC_INTEGRITY",
                        "threshold": "OFF"
                    }
                ]
            }

            # URL 마스킹 처리
            masked_url = re.sub(r'(key=)([^&]+)', r'\1****', url) if 'key=' in url else url
            
            logger.debug(
                "응답 생성 시작:\n"
                f"URL: {masked_url}\n"
                f"Temperature: {temperature}\n"
                f"Message Count: {len(messages)}"
            )

            result = self._make_api_request(headers, data, url)
            logger.debug(f"Raw API Response: {result}")
            
            if 'candidates' not in result:
                logger.error("응답에 candidates 필드 없음")
                raise APIResponseError("API 응답에 candidates가 없습니다.")
                
            if not result['candidates']:
                logger.error("유효한 후보 응답 없음")
                raise APIResponseError("API 응답에 유효한 후보가 없습니다.")
                
            candidate = result['candidates'][0]
            
            if 'content' in candidate and 'parts' in candidate['content']:
                text = candidate['content']['parts'][0].get('text', '')
            elif 'text' in candidate:
                text = candidate['text']
            else:
                logger.error(f"응답에서 텍스트를 찾을 수 없음: {candidate}")
                raise APIResponseError("API 응답에서 텍스트를 찾을 수 없습니다.")
            
            if not text.strip():
                logger.error("빈 응답 수신")
                raise APIResponseError("API가 빈 응답을 반환했습니다.")
                
            logger.debug(f"생성된 응답: {text[:200]}...")
            return text
            
        except (KeyError, IndexError) as e:
            error_context = {
                'result': locals().get('result'),
                'url': url,
                'temperature': temperature
            }
            log_error(e, error_context)
            raise APIResponseError("API 응답의 형식이 올바르지 않습니다.")
        except Exception as e:
            error_context = {
                'url': url,
                'temperature': temperature,
                'message_count': len(messages)
            }
            log_error(e, error_context)
            raise APIConnectionError("예기치 않은 오류가 발생했습니다.")

    def stream_response(self, data_chunk):
        """스트리밍된 데이터 청크를 처리"""
        self.bridge._process_complete_response(data_chunk)