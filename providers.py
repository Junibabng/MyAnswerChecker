import requests
import logging
import os
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

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
            while retry_count < self.max_retries:
                try:
                    return func(*args, **kwargs)
                except requests.exceptions.RequestException as e:
                    retry_count += 1
                    if retry_count == self.max_retries:
                        raise APIConnectionError(f"API 연결 실패: {str(e)}")
                    
                    delay = min(self.base_delay * (2 ** (retry_count - 1)), self.max_delay)
                    logger.warning(f"API 호출 실패 (시도 {retry_count}/{self.max_retries}). {delay}초 후 재시도...")
                    time.sleep(delay)
            return None
        return wrapper

class LLMProvider(ABC):
    """LLM 서비스 호출을 위한 추상 기본 클래스"""
    @abstractmethod
    def call_api(self, system_message, user_message, temperature=0.2):
        """LLM API를 호출하여 응답을 받아옵니다."""
        pass

    @RetryWithExponentialBackoff()
    def _make_api_request(self, headers, data, url=None):
        """API 요청을 보내고 응답을 받아옵니다."""
        try:
            if url is None:
                url = f"{self.base_url}/v1/chat/completions"
                
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            if response.status_code == 401:
                raise InvalidAPIKeyError("API 키가 유효하지 않습니다.")
            elif response.status_code == 429:
                raise APIConnectionError("API 요청 한도를 초과했습니다.")
            elif response.status_code == 500:
                raise APIConnectionError("AI 서버에 일시적인 문제가 발생했습니다.")
            elif response.status_code == 503:
                raise APIConnectionError("AI 서버가 일시적으로 응답하지 않습니다.")
            elif response.status_code != 200:
                raise APIConnectionError(f"AI 서버 오류 (상태 코드: {response.status_code})")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            raise APIConnectionError("요청 시간이 초과되었습니다.")
        except requests.exceptions.ConnectionError:
            raise APIConnectionError("서버에 연결할 수 없습니다.")
        except requests.exceptions.RequestException as e:
            raise APIConnectionError(f"요청 중 오류가 발생했습니다.")
        except ValueError as e:
            raise APIResponseError("응답을 처리할 수 없습니다.")

class OpenAIProvider(LLMProvider):
    """OpenAI API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, base_url, model_name):
        if not api_key:
            raise InvalidAPIKeyError("API 키가 제공되지 않았습니다.")
        
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.system_prompt = "You are a helpful assistant."

    def set_system_prompt(self, prompt):
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=0.2):
        """LLM API를 호출하여 응답을 받아옵니다."""
        messages = [
            {"role": "user", "content": user_message}
        ]
        return self.generate_response(messages, temperature)

    def generate_response(self, messages, temperature=0.7):
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

        try:
            result = self._make_api_request(headers, payload)
            if not result.get('choices'):
                raise APIResponseError("AI가 응답을 생성하지 못했습니다.")
            return result['choices'][0]['message']['content'].strip()
        except (KeyError, IndexError) as e:
            raise APIResponseError("AI 응답의 형식이 올바르지 않습니다.")
        except Exception as e:
            logger.exception("OpenAI API 호출 실패")
            raise APIConnectionError("예기치 않은 오류가 발생했습니다.")

class GeminiProvider(LLMProvider):
    """Google Gemini API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp"):
        if not api_key:
            raise InvalidAPIKeyError("API 키가 제공되지 않았습니다.")
            
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}"
        self.system_prompt = "You are a helpful assistant."

    def set_system_prompt(self, prompt):
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=0.2):
        """LLM API를 호출하여 응답을 받아옵니다."""
        messages = [
            {"role": "user", "content": user_message}
        ]
        return self.generate_response(messages, temperature)

    def generate_response(self, messages, temperature=0.7):
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
            }
        }

        try:
            response = self._make_api_request(headers, data, url)
            logger.debug("Raw API Response: %s", response)
            
            if 'candidates' not in response:
                raise APIResponseError("API 응답에 candidates가 없습니다.")
                
            if not response['candidates']:
                raise APIResponseError("API 응답에 유효한 후보가 없습니다.")
                
            candidate = response['candidates'][0]
            
            if 'content' in candidate and 'parts' in candidate['content']:
                text = candidate['content']['parts'][0].get('text', '')
            elif 'text' in candidate:
                text = candidate['text']
            else:
                raise APIResponseError("API 응답에서 텍스트를 찾을 수 없습니다.")
            
            if not text.strip():
                raise APIResponseError("API가 빈 응답을 반환했습니다.")
                
            return text
            
        except (KeyError, IndexError) as e:
            raise APIResponseError(f"예상치 못한 API 응답 형식: {str(e)}")
        except Exception as e:
            logger.exception("Gemini API 호출 실패")
            raise

    def stream_response(self, data_chunk):
        """스트리밍된 데이터 청크를 처리"""
        self.bridge._process_complete_response(data_chunk)