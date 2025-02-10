import re
import json
import logging


def extract_difficulty(llm_response: str) -> str:
    """
    LLM 응답의 마지막 부분에서 recommendation JSON 블록을 찾아
    그 안에 있는 난이도(recommendation) 값을 추출하여 반환합니다.
    
    파라미터:
        llm_response (str): LLM의 전체 응답 텍스트

    리턴:
        str: 추출한 난이도 값. 없으면 빈 문자열 반환.
    """
    if not llm_response:
        logging.error("LLM 응답이 비어있습니다.")
        return ""
        
    logging.debug(f"LLM 응답 처리 시작:\n{llm_response[:200]}...")
    
    # 마지막에 나타나는 JSON 블럭을 찾기 위한 정규 표현식입니다.
    pattern = r'\{[^{]*"recommendation"\s*:\s*"([^"]+)"[^}]*\}\s*$'
    match = re.search(pattern, llm_response, re.DOTALL)
    
    if match:
        try:
            recommendation = match.group(1).strip()
            logging.debug(f"추출된 난이도: {recommendation}")
            return recommendation
        except Exception as e:
            logging.error(f"난이도 값 추출 중 오류: {str(e)}")
    else:
        logging.error("추천 JSON 블럭을 찾을 수 없습니다.")
        logging.debug(f"응답의 마지막 부분:\n{llm_response[-200:]}")
    return ""


if __name__ == "__main__":
    # 디버깅 및 테스트용 예제입니다.
    sample_response = '''
    사용자 답변은 핵심 의미를 정확하게 파악하고 있습니다. "시민사회 정부 시장의 협치"는 거버넌스의 주요 구성 요소를 명확하게 언급하며, 최근 행정 개념에서의 거버넌스 의미를 잘 나타냅니다. 정답과 표현 방식과 순서에서 약간의 차이가 있지만, '시민사회, 정부, 시장 간 협력'이라는 거버넌스의 핵심 요소를 명확히 나타내고 있습니다. '협치'라는 용어 또한 거버넌스의 의미를 잘 반영합니다.

    답변 시간은 8초로, 5초에서 40초 사이인 'Good' 범위에 해당합니다.

    **정답 및 해설:**

    **정답:** 정부, 시장, 시민사회 간 협력체계를 뜻하며 국정운영의 파트너십을 의미

    **해설:** 최근의 행정 개념에서 거버넌스는 정부, 시장, 시민사회 간의 상호작용과 협력을 통해 국정운영의 효율성과 민주성을 높이는 체계를 의미합니다. 사용자 답변은 이러한 핵심 요소를 잘 요약하고 있습니다. '협치'는 거버넌스를 간결하게 표현하는 적절한 용어입니다.

    전반적으로 사용자의 답변은 거버넌스의 핵심 개념을 잘 이해하고 있으며, 적절한 시간 내에 답변했습니다. 따라서 'Good'을 추천합니다.
    
    {
        "recommendation": "Good"
    }
    '''

    difficulty = extract_difficulty(sample_response)
    print("추출된 난이도:", difficulty) 