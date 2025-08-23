"""
LLM 프로바이더 패키지

이 패키지는 다양한 LLM(Large Language Model) 서비스를 위한 프로바이더를 제공합니다.
현재 지원되는 프로바이더:
- OpenAI
- Gemini

모든 프로바이더는 LLMProvider 기본 클래스를 구현합니다.
"""

from typing import List, Type

from .base import (
    LLMProvider,
    OpenAIProvider,
    GeminiProvider,
    APIConnectionError,
    APIResponseError,
    InvalidAPIKeyError,
    LLMProviderError
)

from .provider_factory import get_provider, ProviderFactoryError

__all__: List[str] = [
    'LLMProvider',
    'OpenAIProvider',
    'GeminiProvider',
    'get_provider',
    'APIConnectionError',
    'APIResponseError',
    'InvalidAPIKeyError',
    'LLMProviderError',
    'ProviderFactoryError'
]

# Available provider types
PROVIDER_TYPES: List[str] = ['openai', 'gemini']

# Provider class mapping
PROVIDER_CLASSES: dict[str, Type[LLMProvider]] = {
    'openai': OpenAIProvider,
    'gemini': GeminiProvider
} 