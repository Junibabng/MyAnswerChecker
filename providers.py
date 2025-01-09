import requests
import logging
import os
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

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
                except (requests.exceptions.RequestException, ConnectionError) as e:
                    retry_count += 1
                    if retry_count == self.max_retries:
                        raise e
                    
                    delay = min(self.base_delay * (2 ** (retry_count - 1)), self.max_delay)
                    logger.warning(f"API call failed (attempt {retry_count}/{self.max_retries}). Retrying in {delay}s...")
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
        if url is None:
            url = f"{self.base_url}/v1/chat/completions"
            
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()

class OpenAIProvider(LLMProvider):
    """OpenAI API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, base_url, model_name):
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
            return result['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.exception("OpenAI API call failed: %s", e)
            raise

class GeminiProvider(LLMProvider):
    """Google Gemini API를 사용하는 LLM 프로바이더"""
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp"):
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

        # 시스템 프롬프트와 사용자 메시지 결합
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
            logger.debug("Raw API Response: %s", response)  # 전체 응답 로깅
            
            # Gemini API 응답 구조 처리
            if 'candidates' in response and len(response['candidates']) > 0:
                candidate = response['candidates'][0]
                
                # 다양한 응답 구조 처리
                if 'content' in candidate and 'parts' in candidate['content']:
                    text = candidate['content']['parts'][0].get('text', '')
                elif 'text' in candidate:
                    text = candidate['text']
                else:
                    logger.error("No text found in response: %s", candidate)
                    raise ValueError("No text content in API response")
                
                if not text.strip():  # 빈 응답 체크
                    logger.warning("Empty response received from API")
                    return "죄송합니다. 응답을 생성하는 데 문제가 발생했습니다. 다시 시도해주세요."
                    
                return text
            else:
                logger.error("Unexpected response structure: %s", response)
                raise ValueError("Invalid response structure from Gemini API")
                
        except Exception as e:
            logger.exception("Error generating Gemini response: %s", e)
            raise

    def stream_response(self, data_chunk):
        """스트리밍된 데이터 청크를 처리"""
        self.bridge._process_complete_response(data_chunk)