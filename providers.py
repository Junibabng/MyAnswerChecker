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
    """LLM provider base exception class"""
    def __init__(self, message, help_text=None):
        super().__init__(message)
        self.help_text = help_text or "Please try again later."

class APIConnectionError(LLMProviderError):
    """API connection exception"""
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
    """API response processing exception"""
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
    """Invalid API key exception"""
    def __init__(self, message):
        help_text = "Please check your API key in Settings and ensure it is entered correctly."
        super().__init__("Invalid API key", help_text)

class RetryWithExponentialBackoff:
    """Exponential backoff retry decorator"""
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
                        f"API request attempt {retry_count + 1}/{self.max_retries}\n"
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
                        f"API call failed (attempt {retry_count}/{self.max_retries})\n"
                        f"Error: {str(e)}\n"
                        f"Delay: retrying in {delay} seconds"
                    )
                    time.sleep(delay)
                    
            return None
        return wrapper

class LLMProvider(ABC):
    """LLM service call base class"""
    def __init__(self):
        self.retry_config = {
            'max_retries': 3,
            'base_delay': 1,
            'max_delay': 8
        }

    @abstractmethod
    def call_api(self, system_message, user_message, temperature=0.2):
        """Call the LLM API and retrieve a response"""
        pass

    def _retry_with_exponential_backoff(self, func, *args, **kwargs):
        """Exponential backoff retry logic"""
        retry_count = 0
        last_error = None
        
        while retry_count < self.retry_config['max_retries']:
            try:
                logger.debug(
                    f"API request attempt {retry_count + 1}/{self.retry_config['max_retries']}\n"
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
                    raise APIConnectionError(f"API connection failed: {str(e)}")
                
                delay = min(self.retry_config['base_delay'] * (2 ** (retry_count - 1)), self.retry_config['max_delay'])
                logger.warning(
                    f"API call failed (attempt {retry_count}/{self.retry_config['max_retries']})\n"
                    f"Error: {str(e)}\n"
                    f"Delay: retrying in {delay} seconds"
                )
                time.sleep(delay)
        
        if last_error:
            raise APIConnectionError(f"Maximum retries exceeded: {str(last_error)}")
        return None

    def _make_api_request(self, headers, data, url=None):
        """Send an API request and retrieve a response"""
        try:
            if url is None:
                url = f"{self.base_url}/v1/chat/completions"
            
            logger.debug(
                "API request started:\n"
                f"URL: {url}\n"
                f"Headers: {headers}\n"
                f"Data: {data}"
            )
                
            response = requests.post(url, headers=headers, json=data, timeout=30)
            
            logger.debug(
                "API response received:\n"
                f"Status Code: {response.status_code}\n"
                f"Response Headers: {dict(response.headers)}"
            )
            
            if response.status_code == 401:
                logger.error(f"Authentication failed - API key issue: {response.text}")
                raise InvalidAPIKeyError("Invalid API key.")
            elif response.status_code == 429:
                logger.warning(f"Rate limit exceeded: {response.text}")
                raise APIConnectionError("API rate limit exceeded.")
            elif response.status_code == 500:
                logger.error(f"Server internal error: {response.text}")
                raise APIConnectionError("The AI server is experiencing a temporary issue.")
            elif response.status_code == 503:
                logger.error(f"Service unavailable: {response.text}")
                raise APIConnectionError("The AI server is temporarily unavailable.")
            elif response.status_code != 200:
                logger.error(
                    f"Unexpected status code: {response.status_code}\n"
                    f"Response: {response.text}"
                )
                raise APIConnectionError(f"AI server error (status code: {response.status_code})")
            
            response.raise_for_status()
            response_json = response.json()
            
            logger.debug(f"API response content: {response_json}")
            return response_json
            
        except requests.exceptions.Timeout as e:
            log_error(e, {'url': url, 'timeout': 30})
            raise APIConnectionError("The request timed out.")
        except requests.exceptions.ConnectionError as e:
            log_error(e, {'url': url})
            raise APIConnectionError("Unable to connect to the server.")
        except requests.exceptions.RequestException as e:
            log_error(e, {'url': url, 'response_text': getattr(e.response, 'text', None)})
            raise APIConnectionError("An error occurred during the request.")
        except ValueError as e:
            log_error(e, {'response_text': response.text})
            raise APIResponseError("Unable to process the response.")
        except Exception as e:
            log_error(e, {'url': url, 'response': locals().get('response')})
            raise

class OpenAIProvider(LLMProvider):
    """OpenAI API LLM provider"""
    def __init__(self, api_key, base_url, model_name):
        super().__init__()
        if not api_key:
            logger.error("API key not provided")
            raise InvalidAPIKeyError("API key was not provided.")
        
        logger.info(
            f"OpenAI provider initialized:\n"
            f"Model: {model_name}\n"
            f"Base URL: {base_url}"
        )
        
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.system_prompt = "You are a helpful assistant."

    def set_system_prompt(self, prompt):
        logger.debug(f"System prompt set: {prompt}")
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=0.2):
        """Call the LLM API and retrieve a response"""
        try:
            logger.debug(
                "API call preparation:\n"
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
                "Response generation started:\n"
                f"Model: {self.model_name}\n"
                f"Temperature: {temperature}\n"
                f"Message Count: {len(messages)}"
            )

            result = self._make_api_request(headers, payload)
            
            if not result.get('choices'):
                logger.error(f"Response missing choices field: {result}")
                raise APIResponseError("The AI could not generate a response.")
                
            response_content = result['choices'][0]['message']['content'].strip()
            logger.debug(f"Generated response: {response_content[:200]}...")
            
            return response_content
            
        except (KeyError, IndexError) as e:
            error_context = {
                'result': locals().get('result'),
                'model': self.model_name,
                'temperature': temperature
            }
            log_error(e, error_context)
            raise APIResponseError("The AI response is in an invalid format.")
        except Exception as e:
            error_context = {
                'model': self.model_name,
                'temperature': temperature,
                'message_count': len(messages)
            }
            log_error(e, error_context)
            raise APIConnectionError("An unexpected error occurred.")

class GeminiProvider(LLMProvider):
    """Google Gemini API LLM provider"""
    def __init__(self, api_key, model_name="gemini-2.0-flash-exp"):
        super().__init__()
        if not api_key:
            logger.error("API key not provided")
            raise InvalidAPIKeyError("API key was not provided.")
            
        logger.info(
            f"Gemini provider initialized:\n"
            f"Model: {model_name}"
        )
            
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}"
        self.system_prompt = "You are a helpful assistant."

    def set_system_prompt(self, prompt):
        logger.debug(f"System prompt set: {prompt}")
        self.system_prompt = prompt

    def call_api(self, system_message, user_message, temperature=0.2):
        """Call the LLM API and retrieve a response"""
        try:
            logger.debug(
                "API call preparation:\n"
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
                }
            }

            logger.debug(
                "Response generation started:\n"
                f"URL: {url}\n"
                f"Temperature: {temperature}\n"
                f"Message Count: {len(messages)}"
            )

            result = self._make_api_request(headers, data, url)
            logger.debug(f"Raw API Response: {result}")
            
            if 'candidates' not in result:
                logger.error("Response missing candidates field")
                raise APIResponseError("The API response has no candidates field.")
                
            if not result['candidates']:
                logger.error("No valid candidate responses")
                raise APIResponseError("The API response has no valid candidates.")
                
            candidate = result['candidates'][0]
            
            if 'content' in candidate and 'parts' in candidate['content']:
                text = candidate['content']['parts'][0].get('text', '')
            elif 'text' in candidate:
                text = candidate['text']
            else:
                logger.error(f"Text not found in response: {candidate}")
                raise APIResponseError("Could not find text in the API response.")
            
            if not text.strip():
                logger.error("Empty response received")
                raise APIResponseError("The API returned an empty response.")
                
            logger.debug(f"Generated response: {text[:200]}...")
            return text
            
        except (KeyError, IndexError) as e:
            error_context = {
                'result': locals().get('result'),
                'url': url,
                'temperature': temperature
            }
            log_error(e, error_context)
            raise APIResponseError("The API response is in an invalid format.")
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