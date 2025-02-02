import logging
from providers.base import OpenAIProvider, GeminiProvider

logger = logging.getLogger(__name__)

def get_provider(config):
    provider_type = config.get("providerType", "openai")
    if provider_type.lower() == "openai":
        api_key = config.get("openaiApiKey", "")
        base_url = config.get("baseUrl", "https://api.openai.com")
        model = config.get("modelName", "gpt-4o-mini")
        temperature = config.get("temperature", 0.7)
        return OpenAIProvider(api_key, base_url, model, temperature)
    elif provider_type.lower() == "gemini":
        api_key = config.get("geminiApiKey", "")
        model = config.get("geminiModel", "gemini-2.0-flash-exp")
        temperature = config.get("temperature", 0.7)
        return GeminiProvider(api_key, model, temperature)
    else:
        logger.error("Unknown provider type: %s", provider_type)
        raise ValueError(f"Unknown provider type: {provider_type}") 