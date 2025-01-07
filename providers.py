import requests
import logging
import os
from abc import ABC, abstractmethod

class LLMProvider(ABC):
    @abstractmethod
    def call_api(self, system_message, user_message, temperature=0.2):
        pass

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
        response = requests.post(f"{self.base_url}/v1/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()

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
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        result = response.json()

        # Gemini Flash Thinking 모델의 경우 사고 과정 제외
        if "flash-thinking" in self.model_name.lower():
            if result.get('candidates') and result['candidates'][0].get('content', {}).get('parts'):
                parts = result['candidates'][0]['content']['parts']
                # 첫 번째 부분(사고 과정)을 제외한 나머지 부분을 결합
                final_response = " ".join(part.get('text', '').strip() for part in parts[1:])
                return final_response.strip()
        
        # 일반 Gemini 모델의 경우 기존 처리 방식 유지
        return result['candidates'][0]['content']['parts'][0]['text'].strip()

    def stream_response(self, data_chunk):
        """스트리밍된 데이터 청크를 처리"""
        self.bridge._process_complete_response(data_chunk)