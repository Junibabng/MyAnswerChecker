# MyAnswerChecker

MyAnswerChecker는 Anki 사용자를 위한 답변 평가 플러그인입니다. LLM(Large Language Model)을 활용하여 사용자의 답변을 자동으로 평가하고, 학습 난이도를 추천해주는 기능을 제공합니다.

## 기능

- 사용자의 답변을 LLM을 통해 자동으로 평가
- 답변의 정확도에 따른 학습 난이도 추천 (Again, Hard, Good, Easy)
- 실시간 채팅 형식의 인터페이스
- 답변 시간 측정 및 표시
- 다양한 LLM 제공자 지원 (OpenAI GPT, Google Gemini 등)

## 시스템 요구사항

- Anki 2.1.50 이상
- Python 3.9 이상
- PyQt6
- 인터넷 연결

## 설치

1. Anki 애드온 관리자를 통해 설치
2. 필요한 패키지 설치:
   ```bash
   pip install -r requirements.txt
   ```

## 디렉토리 구조

```
MyAnswerChecker/
├── libs/                  # 외부 라이브러리 파일들
├── providers/            # LLM 제공자 관련 모듈
├── __pycache__/         # Python 캐시 파일
├── .git/                # Git 버전 관리
├── main.py              # 메인 프로그램 파일
├── bridge.py            # Python-JavaScript 브릿지
├── answer_checker_window.py  # 메인 UI 창
├── auto_difficulty.py   # 난이도 자동 추천
├── message.py           # 메시지 처리
├── settings_manager.py  # 설정 관리
├── __init__.py         # 패키지 초기화
├── requirements.txt     # 필요한 패키지 목록
├── manifest.json       # 애드온 메타데이터
├── meta.json          # Anki 애드온 메타데이터
└── LICENSE            # 라이선스 정보
```

## 설정

1. 애드온 설정에서 LLM 제공자 선택 (OpenAI 또는 Google Gemini)
2. API 키 입력
3. 필요한 경우 기타 설정 조정 (온도, 난이도 임계값 등)

## 사용 방법

1. Anki에서 카드 학습 중 "Answer Checker" 메뉴 선택
2. 답변 입력 창에 답변 입력
3. LLM이 답변을 평가하고 난이도 추천
4. 추천된 난이도에 따라 카드 학습 진행

## 주의사항

- API 키는 안전하게 보관하세요
- 인터넷 연결이 필요합니다
- 응답 시간은 네트워크 상태와 선택한 LLM에 따라 다를 수 있습니다

## 라이선스

이 프로젝트는 LICENSE 파일에 명시된 조건에 따라 배포됩니다.

## 문제 해결

문제가 발생한 경우 `MyAnswerChecker_debug.log` 파일을 확인하세요. 이 파일에는 자세한 디버그 정보가 포함되어 있습니다.
