from typing import Dict, Any, Union
import logging
from .base import OpenAIProvider, GeminiProvider, LLMProvider, InvalidAPIKeyError

logger = logging.getLogger(__name__)

class ProviderFactoryError(Exception):
    """프로바이더 팩토리 관련 예외"""
    pass

def get_provider(config: Dict[str, Any]) -> LLMProvider:
    """
    설정에 따라 적절한 LLM 프로바이더를 생성합니다.
    
    Args:
        config: 프로바이더 설정이 담긴 딕셔너리
        
    Returns:
        LLMProvider: 생성된 프로바이더 인스턴스
        
    Raises:
        ProviderFactoryError: 알 수 없는 프로바이더 타입이나 설정 오류
        InvalidAPIKeyError: API 키가 없거나 잘못된 경우
    """
    try:
        provider_type = config.get("providerType", "openai").lower()
        temperature = float(config.get("temperature", 0.7))

        if provider_type == "openai":
            api_key = config.get("openaiApiKey", "")
            if not api_key:
                raise InvalidAPIKeyError("OpenAI API 키가 설정되지 않았습니다.")
                
            base_url = config.get("baseUrl", "https://api.openai.com")
            model = config.get("modelName", "gpt-4o-mini")
            
            logger.debug(f"OpenAI 프로바이더 생성 - Model: {model}")
            return OpenAIProvider(api_key, base_url, model, temperature)
            
        elif provider_type == "gemini":
            api_key = config.get("geminiApiKey", "")
            if not api_key:
                raise InvalidAPIKeyError("Gemini API 키가 설정되지 않았습니다.")
                
            model = config.get("geminiModel", "gemini-2.0-flash-exp")
            
            logger.debug(f"Gemini 프로바이더 생성 - Model: {model}")
            return GeminiProvider(api_key, model, temperature)
            
        else:
            logger.error(f"알 수 없는 프로바이더 타입: {provider_type}")
            raise ProviderFactoryError(f"지원하지 않는 프로바이더 타입: {provider_type}")
            
    except InvalidAPIKeyError:
        raise
    except Exception as e:
        logger.error(f"프로바이더 생성 중 오류 발생: {str(e)}")
        raise ProviderFactoryError(f"프로바이더 생성 실패: {str(e)}") 