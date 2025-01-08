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
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
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
        try:
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model_name)
            
            # 시스템 프롬프트와 메시지들을 결합
            combined_prompt = f"{self.system_prompt}\n\n"
            for message in messages:
                role = message.get("role", "user")
                content = message.get("content", "")
                combined_prompt += f"{role}: {content}\n"
            
            response = model.generate_content(
                combined_prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.exception("Error generating Gemini response: %s", e)
            raise

    def stream_response(self, data_chunk):
        """스트리밍된 데이터 청크를 처리"""
        self.bridge._process_complete_response(data_chunk)