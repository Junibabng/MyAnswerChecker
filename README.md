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
reviewer_did_show_question  # 질문 표시 시
reviewer_did_show_answer     # 답변 표시 시
reviewer_did_answer_card     # 카드 답변 후
webview_did_receive_js_message # JS 메시지 수신 시
```

## 🧩 핵심 메서드 구현 방식

### 1. 메시지 관리 시스템 (`message.py`)
```python
class MessageManager:
    def create_question_message(content, model_name="Current Question")
    def create_review_message(recommendation)
    # 7가지 메시지 타입 지원
```

### 2. AI 통신 관리 (`bridge.py`)
```python
class Bridge(QObject):
    sendResponse = pyqtSignal(str)  # 실시간 스트리밍 구현
    def process_question(card_content, question, card_answers)
```

### 3. 채팅 인터페이스 관리 (`answer_checker_window.py`)
```python
class AnswerCheckerWindow(QDialog):
    def append_to_chat(message: Message)  # WebView 연동 메시지 렌더링
    def process_additional_question(question)  # 질문 처리 파이프라인
```

## 🔑 주요 상태 변수
```python
# answer_checker_window.py
self.last_response: str  # 마지막 AI 응답 저장
self.message_containers: dict  # 메시지 컨테이너 관리
self.is_webview_initialized: bool  # 웹뷰 상태 추적

# bridge.py
conversation_history = {
    'messages': [],  # 대화 기록 저장
    'current_card_id': int  # 현재 카드 컨텍스트
}
```

## 🌐 글로벌 변수
```python
bridge: Bridge  # Python-JS 브릿지 싱글톤
answer_checker_window: AnswerCheckerWindow  # UI 윈도우 인스턴스
mw.llm_addon_settings: dict  # Anki 메인 윈도우 설정 저장
```

## ✨ 최근 주요 개선사항
1. **메시지 시스템 중앙 집중화**:
   ```python
   # 기존
   create_llm_message("현재 문제", content)
   
   # 개선후
   create_question_message(content)  # MessageType.QUESTION 전용 처리
   ```

2. **확장 가능한 메시지 타입 시스템**:
   ```python
   class MessageType(Enum):
       QUESTION = "question"  # 신규 추가 타입
       REVIEW = "review"       # 리뷰 권장 메시지 전용
   ```

3. **에러 처리 강화**:
   ```python
   try:
       card_content = bridge.get_card_content()
   except CardContentError as e:
       show_error_message(e.help_text)  # 상황별 도움말 제공
   ```

4. **성능 개선**:
   ```python
   self.gc_timer = QTimer(self)  # 5분 주기 메모리 관리
   clear_message_containers_periodically()  # 오래된 메시지 자동 정리
   ```

## 🛠 사용자 정의 포인트
1. **새 메시지 타입 추가**:
   ```python
   # message.py
   class MessageType(Enum):
       CUSTOM = "custom"
   
   def create_custom_message(self, content):
       return Message(content, MessageType.CUSTOM)
   ```

2. **AI 제공자 확장**:
   ```python
   # providers.py
   class NewAIProvider(LLMProvider):
       def call_api(self, system_message, user_message):
           # 커스텀 구현
   ```

3. **스타일 커스터마이징**:
   ```css
   /* answer_checker_window.py - default_html */
   .question-message-container {
       border-left: 3px solid #3498db; /* 왼쪽 테두리 추가 */
   }
   ```
   
## ⚙️ 설치 및 사용
1. Anki 2.1.50+ 설치
2. `MyAnswerChecker` 폴더를 Anki 애드온 폴더에 복사
3. API 키 설정: Tools > Answer Checker > Settings
4. 리뷰 세션 시작: Tools > Answer Checker > Open

> 전체 소스 코드 및 최신 업데이트: [GitHub 저장소 링크]
