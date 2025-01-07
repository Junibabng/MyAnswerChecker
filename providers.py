import requests
import logging
import os
import time
from abc import ABC, abstractmethod

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
    @abstractmethod
    def call_api(self, system_message, user_message, temperature=0.2):
        pass

    @RetryWithExponentialBackoff()
    def _make_api_request(self, headers, data, url=None):
        """Make API request with exponential backoff retry"""
        if url is None:
            url = f"{self.base_url}/v1/chat/completions"
            
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        return response.json()

class OpenAIProvider(LLMProvider):
    def __init__(self, api_key, base_url, model_name):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name

    def call_api(self, system_message, user_message, temperature=0.2):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        data = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ],
            "temperature": temperature
        }
        try:
            result = self._make_api_request(headers, data)
            return result['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.exception("OpenAI API call failed: %s", e)
            raise

class GeminiProvider(LLMProvider):
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp"):
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def call_api(self, system_message, user_message, temperature=0.2):
        headers = {
            "Content-Type": "application/json"
        }
        
        data = {
            "contents": [{
                "role": "user",
                "parts": [{
                    "text": user_message
                }]
            }],
            "systemInstruction": {
                "role": "user",
                "parts": [{
                    "text": system_message
                }]
            },
            "generationConfig": {
                "temperature": temperature,
                "topK": 40,
                "topP": 0.95,
                "maxOutputTokens": 8192,
                "responseMimeType": "text/plain"
            }
        }
        
        url = f"{self.base_url}/models/{self.model_name}:generateContent?key={self.api_key}"
        
        try:
            result = self._make_api_request(headers, data, url)
            # Gemini Flash Thinking 모델의 경우 사고 과정 제외
            if "flash-thinking" in self.model_name.lower():
                if result.get('candidates') and result['candidates'][0].get('content', {}).get('parts'):
                    parts = result['candidates'][0]['content']['parts']
                    # 첫 번째 부분(사고 과정)을 제외한 나머지 부분을 결합
                    final_response = " ".join(part.get('text', '').strip() for part in parts[1:])
                    return final_response.strip()
            # 일반 Gemini 모델의 경우 기존 처리 방식 유지
            return result['candidates'][0]['content']['parts'][0]['text'].strip()
        except Exception as e:
            logger.exception("Gemini API call failed: %s", e)
            raise

    def stream_response(self, data_chunk):
        """스트리밍된 데이터 청크를 처리"""
        self.bridge._process_complete_response(data_chunk)