import re
import json
import logging


def extract_difficulty(llm_response: str) -> str:
    """
    LLM 응답에서 난이도 추천을 추출합니다.
    코드 블록(```json)과 일반 JSON 형식 모두 처리합니다.
    
    Args:
        llm_response (str): LLM의 전체 응답 텍스트
        
    Returns:
        str: 추출된 난이도 값 ("Again", "Hard", "Good", "Easy" 중 하나)
             추출 실패 시 빈 문자열 반환
    """
    if not llm_response:
        logging.error("LLM 응답이 비어있습니다.")
        return ""
        
    logging.debug(f"LLM 응답 처리 시작:\n{llm_response[:200]}...")
    
    try:
        # 먼저 코드 블록으로 감싸진 경우를 감지하여 내부 JSON을 추출
        codeblock_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
        codeblock_match = re.search(codeblock_pattern, llm_response, re.IGNORECASE)
        
        if codeblock_match:
            json_content = codeblock_match.group(1)
            logging.debug(f"코드 블록에서 JSON 추출: {json_content}")
        else:
            json_content = llm_response
            logging.debug("코드 블록이 없어 전체 텍스트를 처리합니다.")

        valid_recommendations = ["Again", "Hard", "Good", "Easy"]
        
        # 추출한 문자열이 바로 JSON 형식이면 파싱 시도
        try:
            data = json.loads(json_content)
            recommendation = data.get("recommendation", "").strip()
            if recommendation in valid_recommendations:
                logging.debug(f"직접 JSON 파싱 성공: {recommendation}")
                return recommendation
        except json.JSONDecodeError:
            logging.debug("직접 JSON 파싱 실패, 텍스트 내 JSON 객체 검색을 시도합니다.")
            # JSON 파싱에 실패하면 텍스트 내 JSON 객체를 여러 개 찾는 방식으로 처리
            json_matches = list(re.finditer(r'\{(?:[^{}]|{[^{}]*})*\}', json_content))
            for match in reversed(json_matches):
                try:
                    data = json.loads(match.group(0))
                    if "recommendation" in data:
                        recommendation = data["recommendation"].strip()
                        if recommendation in valid_recommendations:
                            logging.debug(f"JSON 객체 검색에서 난이도 추출 성공: {recommendation}")
                            return recommendation
                except json.JSONDecodeError:
                    continue
        
        logging.error("유효한 난이도 추천을 찾을 수 없습니다.")
        return ""
            
    except Exception as e:
        logging.error(f"난이도 추출 중 오류 발생: {str(e)}")
        return ""


if __name__ == "__main__":
    # 테스트 케이스
    test_cases = [
        # 코드 블록 케이스
        '''
        평가 결과입니다.
        ```json
        {
            "recommendation": "Good"
        }
        ```
        ''',
        # 일반 JSON 케이스
        '''
        평가 결과입니다.
        {
            "recommendation": "Hard"
        }
        ''',
        # 여러 JSON 객체가 있는 케이스
        '''
        {
            "temp": "value"
        }
        평가 결과입니다.
        {
            "recommendation": "Again"
        }
        '''
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n테스트 케이스 {i}:")
        print(f"입력:\n{test_case}")
        difficulty = extract_difficulty(test_case)
        print(f"추출된 난이도: {difficulty}") 