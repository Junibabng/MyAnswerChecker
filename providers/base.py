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
        self.help_text = help_text or "Please try again later."

class APIConnectionError(LLMProviderError):
    """API 연결 관련 예외"""
    def __init__(self, message):
        help_texts = {
            "timeout": "Please check your internet connection and try again.",
            "rate_limit": "You're being rate-limited. Please try again later.",
            "connection": "Please verify your internet connection."
        }
        
        if "시간이 초과" in message:
            help_text = help_texts["timeout"]
        elif "한도를 초과" in message:
            help_text = help_texts["rate_limit"]
        else:
            help_text = help_texts["connection"]
            
        super().__init__(f"Failed to connect to the AI server: {message}", help_text)

class APIResponseError(LLMProviderError):
    """API 응답 처리 관련 예외"""
    def __init__(self, message):
        help_texts = {
            "empty": "Please try again. If the issue persists, consider selecting a different AI model in Settings.",
            "format": "Please try again later. If the issue continues, consider selecting a different AI model in Settings."
        }
        
        if "빈 응답" in message:
            help_text = help_texts["empty"]
        else:
            help_text = help_texts["format"]
            
        super().__init__(f"Unable to process the AI response: {message}", help_text)

class InvalidAPIKeyError(LLMProviderError):
    """잘못된 API 키 관련 예외"""
    def __init__(self, message):
        help_text = "Please check your API key in Settings and ensure it is entered correctly."
        super().__init__("Invalid API key", help_text)

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
                        raise APIConnectionError(f"API connection failed: {str(e)}")
                    
                    delay = min(self.base_delay * (2 ** (retry_count - 1)), self.max_delay)
                    logger.warning(
                        f"API 호출 실패 (시도 {retry_count}/{self.max_retries})\n"
                        f"Error: {str(e)}\n"
                        f"Delay: retrying in {delay} seconds"
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
                    raise APIConnectionError(f"API connection failed: {str(e)}")
                
                delay = min(self.retry_config.base_delay * (2 ** (retry_count - 1)), self.retry_config.max_delay)
                logger.warning(
                    f"API 호출 실패 (시도 {retry_count}/{self.retry_config.max_retries})\n"
                    f"Error: {str(e)}\n"
                    f"Delay: retrying in {delay} seconds"
                )
                time.sleep(delay)
        
        if last_error:
            raise APIConnectionError(f"Exceeded maximum retry attempts: {str(last_error)}")
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
                raise ValueError("API URL is not specified.")

            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            return response

        except requests.exceptions.HTTPError as e:
            # 응답 본문을 포함하여 원인 파악을 돕기
            status = getattr(response, 'status_code', 'unknown')
            body = None
            try:
                body = response.text
            except Exception:
                body = None
            body_snippet = (body[:500] + '...') if (isinstance(body, str) and len(body) > 500) else body
            logger.error(f"HTTPError from API (status={status}) body={body_snippet}")
            if response.status_code == 401:
                raise InvalidAPIKeyError("Invalid API key")
            elif response.status_code == 429:
                raise APIConnectionError("API rate limit exceeded")
            else:
                raise APIConnectionError(f"HTTP error occurred: {str(e)} | Response body: {body_snippet}")

        except requests.exceptions.ConnectionError as e:
            raise APIConnectionError(f"Failed to connect to server: {str(e)}")

        except requests.exceptions.Timeout as e:
            raise APIConnectionError(f"Request timed out: {str(e)}")

        except requests.exceptions.RequestException as e:
            raise APIConnectionError(f"Error during API request: {str(e)}")

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
            raise InvalidAPIKeyError("API key was not provided.")
        
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

            model_lower = (self.model_name or "").lower()
            # gpt-5 계열(gpt-5, gpt-5-mini, gpt-5-nano)은 temperature 조정 미지원 → 1 고정
            if model_lower.startswith("gpt-5"):
                effective_temperature = 1
                logger.debug("Forcing temperature=1 for GPT-5 family model")
            else:
                effective_temperature = temperature

            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": self.system_prompt}
                ] + messages,
                "temperature": effective_temperature
            }

            # 주의: 일부 모델에서 비표준 파라미터는 400을 유발할 수 있으므로 비활성화
            # (필요시 설정으로 재도입)

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
                # 응답 본문 스니펫 로깅
                body_snippet = None
                try:
                    body_text = response.text
                    body_snippet = (body_text[:500] + '...') if len(body_text) > 500 else body_text
                except Exception:
                    pass
                logger.error(f"API returned non-200 status code: {response.status_code} body={body_snippet}")
                raise APIConnectionError(f"API returned status code {response.status_code}")

            result = response.json()
            
            # OpenAI API response format
            if isinstance(result, dict):
                if 'choices' in result and result['choices']:
                    content = result['choices'][0]['message']['content'].strip()
                    logger.debug(f"생성된 응답: {content[:200]}...")
                    return content
                    
            logger.error(f"Unexpected API response format: {result}")
            raise APIConnectionError("Invalid response format.")
            
        except (ValueError, KeyError, AttributeError) as e:
            error_context = {
                'result': locals().get('result'),
                'model': self.model_name,
                'temperature': temperature
            }
            log_error(e, error_context)
            raise APIResponseError("Invalid AI response format.")
        except Exception as e:
            error_context = {
                'model': self.model_name,
                'temperature': temperature,
                'message_count': len(messages) if 'messages' in locals() else 0
            }
            log_error(e, error_context)
            raise APIConnectionError("An unexpected error occurred.")

class GeminiProvider(LLMProvider):
    """Gemini API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp", temperature=0.7):
        super().__init__()
        if not api_key:
            logger.error("API 키가 제공되지 않음")
            raise InvalidAPIKeyError("API key is required.")
            
        # API 키 리스트 생성 및 초기화
        self.api_keys = [key.strip() for key in api_key.split(',') if key.strip()]
        if not self.api_keys:
            raise InvalidAPIKeyError("No valid API keys found.")
            
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
                        "parts": [{"text": f"{message['content']}\n"}]
                    }
                ],
                "system_instruction":{"parts":[{"text": f"{self.system_prompt}\n\n"}]},
                "tools": [
                    {
                        "googleSearch":{}
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

            response = self._make_api_request(headers, data, url)
            result = response.json()  # Response 객체에서 JSON 데이터 추출
            logger.debug(f"Raw API Response: {result}")  # JSON 데이터 로깅
            
            if 'candidates' not in result:
                logger.error("응답에 candidates 필드 없음")
                raise APIResponseError("The API response has no candidates field.")
                
            if not result['candidates']:
                logger.error("유효한 후보 응답 없음")
                raise APIResponseError("The API response has no valid candidates.")
                
            candidate = result['candidates'][0]
            
            if 'content' in candidate and 'parts' in candidate['content']:
                # 모든 parts의 텍스트를 결합
                text = ''.join(part.get('text', '') for part in candidate['content']['parts'])
                
                # groundingMetadata에서 검색 링크 추출 및 추가
                if 'groundingMetadata' in candidate:
                    metadata = candidate['groundingMetadata']
                    if 'groundingChunks' in metadata:
                        links = []
                        for chunk in metadata['groundingChunks']:
                            if 'web' in chunk and 'uri' in chunk['web']:
                                title = chunk['web'].get('title', chunk['web']['uri'])
                                links.append(f"\n\nReference link: [{title}]({chunk['web']['uri']})")
                        if links:
                            text += '\n\n---' + ''.join(links)
                            
            elif 'text' in candidate:
                text = candidate['text']
            else:
                logger.error(f"응답에서 텍스트를 찾을 수 없음: {candidate}")
                raise APIResponseError("Could not find text in the API response.")
            
            if not text.strip():
                logger.error("빈 응답 수신")
                raise APIResponseError("The API returned an empty response.")
                
            logger.debug(f"생성된 응답: {text[:200]}...")
            return text
            
        except (KeyError, IndexError) as e:
            error_context = {
                'result': locals().get('result'),
                'url': url,
                'temperature': temperature
            }
            log_error(e, error_context)
            raise APIResponseError("Invalid API response format.")
        except Exception as e:
            error_context = {
                'url': url,
                'temperature': temperature,
                'message_count': len(messages)
            }
            log_error(e, error_context)
            raise APIConnectionError("An unexpected error occurred.")

    def stream_response(self, data_chunk):
        """스트리밍된 데이터 청크를 처리"""
        self.bridge._process_complete_response(data_chunk)