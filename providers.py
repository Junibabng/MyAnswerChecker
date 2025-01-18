import requests
import logging
import os
import time
import traceback
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)

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

class LLMProvider(ABC):
    """LLM 서비스 호출을 위한 추상 기본 클래스"""
    def __init__(self):
        self.retry_config = {
            'max_retries': 3,
            'base_delay': 1,
            'max_delay': 8
        }

    @abstractmethod
    def call_api(self, system_message, user_message, temperature=0.2):
        """LLM API를 호출하여 응답을 받아옵니다."""
        pass

    def _retry_with_exponential_backoff(self, func, *args, **kwargs):
        """지수 백오프를 사용한 재시도 로직"""
        retry_count = 0
        last_error = None
        
        while retry_count < self.retry_config['max_retries']:
            try:
                logger.debug(
                    f"API 요청 시도 {retry_count + 1}/{self.retry_config['max_retries']}\n"
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
                    'max_retries': self.retry_config['max_retries'],
                    'function': func.__name__,
                    'args': args,
                    'kwargs': kwargs
                }
                
                if retry_count == self.retry_config['max_retries']:
                    log_error(e, error_context)
                    raise APIConnectionError(f"API 연결 실패: {str(e)}")
                
                delay = min(self.retry_config['base_delay'] * (2 ** (retry_count - 1)), self.retry_config['max_delay'])
                logger.warning(
                    f"API 호출 실패 (시도 {retry_count}/{self.retry_config['max_retries']})\n"
                    f"Error: {str(e)}\n"
                    f"Delay: {delay}초 후 재시도"
                )
                time.sleep(delay)
        
        if last_error:
            raise APIConnectionError(f"최대 재시도 횟수 초과: {str(last_error)}")
        return None

    def _make_api_request(self, headers, data, url=None):
        """API 요청을 보내고 응답을 받아옵니다."""
        try:
            if url is None:
                url = f"{self.base_url}/v1/chat/completions"
            
            logger.debug(
                "API 요청 시작:\n"
                f"URL: {url}\n"
                f"Headers: {headers}\n"
                f"Data: {data}"
            )
                
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            logger.debug(
                "API 응답 수신:\n"
                f"Status Code: {response.status_code}\n"
                f"Response Headers: {dict(response.headers)}"
            )
            
            if response.status_code == 401:
                logger.error(f"인증 실패 - API 키 문제: {response.text}")
                raise InvalidAPIKeyError("API 키가 유효하지 않습니다.")
            elif response.status_code == 429:
                logger.warning(f"요청 한도 초과: {response.text}")
                raise APIConnectionError("API 요청 한도를 초과했습니다.")
            elif response.status_code == 500:
                logger.error(f"서버 내부 오류: {response.text}")
                raise APIConnectionError("AI 서버에 일시적인 문제가 발생했습니다.")
            elif response.status_code == 503:
                logger.error(f"서비스 불가: {response.text}")
                raise APIConnectionError("AI 서버가 일시적으로 응답하지 않습니다.")
            elif response.status_code != 200:
                logger.error(
                    f"예기치 않은 상태 코드: {response.status_code}\n"
                    f"Response: {response.text}"
                )
                raise APIConnectionError(f"AI 서버 오류 (상태 코드: {response.status_code})")
            
            response.raise_for_status()
            response_json = response.json()
            
            logger.debug(f"API 응답 내용: {response_json}")
            return response_json
            
        except requests.exceptions.Timeout as e:
            log_error(e, {'url': url, 'timeout': 30})
            raise APIConnectionError("요청 시간이 초과되었습니다.")
        except requests.exceptions.ConnectionError as e:
            log_error(e, {'url': url})
            raise APIConnectionError("서버에 연결할 수 없습니다.")
        except requests.exceptions.RequestException as e:
            log_error(e, {'url': url, 'response_text': getattr(e.response, 'text', None)})
            raise APIConnectionError(f"요청 중 오류가 발생했습니다.")
        except ValueError as e:
            log_error(e, {'response_text': response.text})
            raise APIResponseError("응답을 처리할 수 없습니다.")
        except Exception as e:
            log_error(e, {'url': url, 'response': locals().get('response')})
            raise

class OpenAIProvider(LLMProvider):
    """OpenAI API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, base_url, model_name):
        super().__init__()
        if not api_key:
            logger.error("API 키가 제공되지 않음")
            raise InvalidAPIKeyError("API 키가 제공되지 않았습니다.")
        
        logger.info(
            f"OpenAI 프로바이더 초기화:\n"
            f"Model: {model_name}\n"
            f"Base URL: {base_url}"
        )
        
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.system_prompt = "You are a helpful assistant."

    def set_system_prompt(self, prompt):
        logger.debug(f"시스템 프롬프트 설정: {prompt}")
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=0.2):
        """LLM API를 호출하여 응답을 받아옵니다."""
        try:
            logger.debug(
                "API 호출 준비:\n"
                f"System Message: {system_message}\n"
                f"Temperature: {temperature}"
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

    def generate_response(self, messages, temperature=0.7):
        try:
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

            logger.debug(
                "응답 생성 시작:\n"
                f"Model: {self.model_name}\n"
                f"Temperature: {temperature}\n"
                f"Message Count: {len(messages)}"
            )

            result = self._make_api_request(headers, payload)
            
            if not result.get('choices'):
                logger.error(f"응답에 choices 필드 없음: {result}")
                raise APIResponseError("AI가 응답을 생성하지 못했습니다.")
                
            response_content = result['choices'][0]['message']['content'].strip()
            logger.debug(f"생성된 응답: {response_content[:200]}...")
            
            return response_content
            
        except (KeyError, IndexError) as e:
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
                'message_count': len(messages)
            }
            log_error(e, error_context)
            raise APIConnectionError("예기치 않은 오류가 발생했습니다.")

class GeminiProvider(LLMProvider):
    """Google Gemini API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp"):
        super().__init__()
        if not api_key:
            logger.error("API 키가 제공되지 않음")
            raise InvalidAPIKeyError("API 키가 제공되지 않았습니다.")
            
        logger.info(
            f"Gemini 프로바이더 초기화:\n"
            f"Model: {model_name}"
        )
            
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}"
        self.system_prompt = "You are a helpful assistant."

    def set_system_prompt(self, prompt):
        logger.debug(f"시스템 프롬프트 설정: {prompt}")
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=0.2):
        """LLM API를 호출하여 응답을 받아옵니다."""
        try:
            logger.debug(
                "API 호출 준비:\n"
                f"System Message: {system_message}\n"
                f"Temperature: {temperature}"
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

    def generate_response(self, messages, temperature=0.7):
        try:
            url = f"{self.base_url}:generateContent?key={self.api_key}"
            
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

            logger.debug(
                "응답 생성 시작:\n"
                f"URL: {url}\n"
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