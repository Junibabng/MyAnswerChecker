# MyAnswerChecker 플러그인 기술 문서

## 📂 파일 구조
```
MyAnswerChecker/
├── __init__.py          # 애드온 초기화 및 메뉴 설정
├── main.py              # 메인 로직, 훅 설정, UI 통합
├── message.py           # 메시지 생성 및 관리 시스템
├── answer_checker_window.py # 채팅 인터페이스 및 이벤트 핸들링
├── bridge.py            # Python-JavaScript 통신 관리
├── providers.py         # AI 제공자(OpenAI, Gemini) 구현
├── build_package.py     # 애드온 패키지 빌드 스크립트
├── test_package.py      # 테스트 자동화 스크립트
├── meta.json           # 애드온 메타데이터
├── manifest.json       # 애드온 설정 및 의존성
└── MyAnswerChecker_debug.log # 디버그 로그 파일
```

## 🔄 호출 구조
1. **초기화 흐름**:
   `__init__.py` → `main.py` → `bridge.py` ↔ `providers.py`
   
2. **카드 리뷰 흐름**:
   `main.py` → `answer_checker_window.py` ↔ `message.py`
   ↕
   `bridge.py` ↔ `providers.py`

## 🪝 주요 훅(Hooks)
```python
reviewer_did_show_question    # 질문 표시 시
reviewer_did_show_answer     # 답변 표시 시
reviewer_did_answer_card     # 카드 답변 후
reviewer_will_end           # 리뷰 종료 시
reviewer_will_show_context_menu # 컨텍스트 메뉴 표시 시
webview_did_receive_js_message # JS 메시지 수신 시
```

## 🧩 핵심 컴포넌트

### 1. 메시지 시스템 (`message.py`)
```python
class MessageType(Enum):
    SYSTEM = "system"        # 시스템 알림
    USER = "user"           # 사용자 입력
    ERROR = "error"         # 에러 메시지
    LLM = "llm"            # AI 응답
    REVIEW = "review"       # 리뷰 결과
    INFO = "info"          # 정보 메시지
    QUESTION = "question"   # 현재 문제
    WELCOME = "welcome"     # 환영 메시지
    DIFFICULTY_RECOMMENDATION = "difficulty_recommendation" # 난이도 추천
```

### 2. 에러 처리 시스템
```python
class BridgeError:          # 기본 에러 클래스
class CardContentError:     # 카드 콘텐츠 관련 에러
class ResponseProcessingError: # 응답 처리 에러
class LLMProviderError:    # AI 제공자 관련 에러
class APIConnectionError:  # API 연결 에러
class InvalidAPIKeyError:  # API 키 검증 에러
```

### 3. AI 제공자 구현 (`providers.py`)
```python
class LLMProvider(ABC):
    # 지수 백오프 재시도 설정
    retry_config = {
        'max_retries': 3,
        'base_delay': 1,
        'max_delay': 8
    }
    
    @RetryWithExponentialBackoff()
    def call_api(self, system_message, user_message, temperature=0.2)
```

### 4. 브릿지 시스템 (`bridge.py`)
```python
class Bridge(QObject):
    # 시그널 정의
    sendResponse = pyqtSignal(str)
    sendQuestionResponse = pyqtSignal(str)
    stream_data_received = pyqtSignal(str, str, str)
    
    # 타이머 설정
    RESPONSE_TIMEOUT = 10  # seconds
    timer_interval = 500   # 0.5 seconds
    
    # 대화 컨텍스트 관리
    max_context_length = 10
```

## 🔧 성능 최적화

### 1. 메모리 관리
```python
# 주기적 가비지 컬렉션
self.gc_timer = QTimer(self)
self.gc_timer.timeout.connect(self.cleanup_old_messages)
self.gc_timer.start(300000)  # 5분마다 실행
```

### 2. 응답 최적화
- 스트리밍 응답 처리
- 응답 버퍼링 시스템
- 타임아웃 처리

### 3. 컨텍스트 관리
- 최대 대화 기록 제한 (10개)
- 자동 컨텍스트 정리
- 메모리 효율적인 저장

## ⚙️ 설치 및 설정

### 1. 요구사항
- Anki 2.1.50+
- Python 3.9+
- PyQt6

### 2. API 키 설정
1. Tools > Answer Checker > Settings
2. API 키 입력 (OpenAI 또는 Gemini)
3. 모델 선택 및 온도 설정

### 3. 디버그 로깅
- 로그 위치: `MyAnswerChecker_debug.log`
- 로그 레벨: DEBUG
- 로그 포맷: 타임스탬프, 파일명, 함수명, 메시지

### 4. 사용자 정의 옵션
- 모델 온도 조정 (0.0 ~ 1.0)
- 응답 타임아웃 설정
- 대화 기록 길이 제한
- UI 테마 설정

## 🛠 개발자 도구

### 1. 패키지 빌드
```bash
python build_package.py
```

### 2. 테스트 실행
```bash
python test_package.py
```

### 3. 디버그 모드
```python
# config.json에서 활성화
"debug_mode": true
```

## 🔒 보안 고려사항
1. API 키 암호화 저장
2. 민감 정보 로깅 제외
3. HTTPS 통신 강제
4. 입력 데이터 검증

> 전체 소스 코드 및 최신 업데이트: [GitHub 저장소 링크]

## 🔍 주요 기능 구현 방식

### 1. 메시지 처리 시스템
```python
class MessageManager:
    def create_message(self, content: str, message_type: MessageType) -> Message:
        """메시지 객체 생성 및 HTML 변환"""
        message = Message(
            content=content,
            message_type=message_type,
            timestamp=datetime.now()
        )
        return self.add_message(message)

    def _get_message_content(self) -> str:
        """메시지 타입별 HTML 템플릿 생성"""
        if self.message_type == MessageType.WELCOME:
            return self._create_welcome_template()
        elif self.message_type == MessageType.QUESTION:
            return self._create_question_template()
        # ... 기타 메시지 타입 처리
```

### 2. AI 응답 처리 파이프라인
```python
class Bridge:
    async def process_question(self, card_content: str, user_question: str) -> str:
        """
        1. 카드 컨텍스트 설정
        2. 프롬프트 생성
        3. AI 호출
        4. 응답 스트리밍
        5. 난이도 추천
        """
        try:
            context = self._prepare_context(card_content)
            prompt = self._create_prompt(context, user_question)
            response = await self._get_ai_response(prompt)
            await self._stream_response(response)
            return self._process_recommendation(response)
        except BridgeError as e:
            self._handle_error(e)

    def _prepare_context(self, card_content: str) -> dict:
        """카드 컨텍스트 준비"""
        return {
            'content': card_content,
            'timestamp': time.time(),
            'card_id': self.current_card_id,
            'previous_answers': self._get_previous_answers()
        }
```

### 3. 난이도 평가 시스템
```python
class DifficultyEvaluator:
    THRESHOLDS = {
        'AGAIN': 0.3,    # 30% 이하 이해도
        'HARD': 0.6,     # 30-60% 이해도
        'GOOD': 0.8,     # 60-80% 이해도
        'EASY': 1.0      # 80% 이상 이해도
    }

    def evaluate(self, llm_response: str) -> str:
        """응답 분석 및 난이도 추천"""
        understanding_level = self._analyze_response(llm_response)
        return self._get_recommendation(understanding_level)

    def _analyze_response(self, response: str) -> float:
        """응답 이해도 분석"""
        keywords = self._extract_keywords(response)
        accuracy = self._calculate_accuracy(keywords)
        confidence = self._assess_confidence(response)
        return (accuracy * 0.7 + confidence * 0.3)
```

## 📊 주요 상태 변수

### 1. 브릿지 컴포넌트
```python
class Bridge:
    # 응답 관리
    response_buffer: Dict[str, str] = {}  # 스트리밍 응답 버퍼
    last_response: Optional[str] = None   # 마지막 완성된 응답
    
    # 컨텍스트 관리
    conversation_history: List[Dict] = []  # 대화 기록
    current_card_id: Optional[int] = None  # 현재 카드 ID
    
    # 상태 플래그
    is_processing: bool = False  # 처리 중 상태
    is_streaming: bool = False   # 스트리밍 중 상태
    
    # 설정값
    max_retries: int = 3        # 최대 재시도 횟수
    timeout: int = 10           # 응답 대기 시간
```

### 2. UI 컴포넌트
```python
class AnswerCheckerWindow:
    # UI 상태
    is_webview_ready: bool = False     # WebView 초기화 상태
    is_chat_visible: bool = False      # 채팅창 표시 상태
    
    # 메시지 컨테이너
    message_containers: Dict[str, Any] = {
        'question': None,    # 현재 질문
        'answer': None,      # 사용자 답변
        'feedback': None,    # AI 피드백
        'history': []        # 이전 대화
    }
    
    # 설정값
    font_size: int = 14
    theme: str = 'light'
    auto_scroll: bool = True
```

### 3. AI 제공자
```python
class LLMProvider:
    # API 설정
    api_key: str                # API 키
    base_url: str              # API 엔드포인트
    model_name: str            # 사용 모델
    
    # 요청 설정
    temperature: float = 0.2   # 응답 다양성
    max_tokens: int = 1000     # 최대 토큰 수
    
    # 재시도 설정
    retry_count: int = 0       # 현재 재시도 횟수
    backoff_factor: float = 2  # 재시도 간격 증가율
```

## 🎯 핵심 메서드

### 1. 카드 처리
```python
def process_card(self, card: Card) -> None:
    """
    카드 처리 메인 로직
    1. 카드 데이터 추출
    2. 컨텍스트 설정
    3. UI 업데이트
    4. AI 분석 요청
    """
    card_data = self._extract_card_data(card)
    self._set_context(card_data)
    self._update_ui(card_data)
    self._request_analysis(card_data)
```

### 2. 응답 스트리밍
```python
async def stream_response(self, response_stream: AsyncIterator) -> str:
    """
    응답 스트리밍 처리
    1. 청크 수신
    2. 버퍼 업데이트
    3. UI 업데이트
    4. 완성된 응답 반환
    """
    buffer = []
    async for chunk in response_stream:
        processed_chunk = self._process_chunk(chunk)
        buffer.append(processed_chunk)
        await self._update_ui_with_chunk(processed_chunk)
    return ''.join(buffer)
```

### 3. 에러 처리
```python
def handle_error(self, error: Exception) -> None:
    """
    에러 처리 및 복구
    1. 에러 로깅
    2. 사용자 알림
    3. 상태 복구
    4. 재시도 결정
    """
    self._log_error(error)
    self._notify_user(error)
    self._restore_state()
    self._decide_retry(error)
```
