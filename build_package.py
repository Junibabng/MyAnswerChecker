import os
import shutil
import zipfile
import re
from pathlib import Path
import argparse

def remove_debug_code(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 디버그 관련 패턴들
    patterns = [
        r'print\s*\([^)]*\)\s*#\s*debug.*\n',  # print() # debug
        r'logging\.debug\([^)]*\).*\n',         # logging.debug()
        r'#\s*DEBUG.*\n',                       # # DEBUG
        r'if\s+DEBUG:.*?(?=\n\S)',             # if DEBUG: 블록
    ]
    
    # 패턴 적용
    for pattern in patterns:
        content = re.sub(pattern, '', content, flags=re.MULTILINE | re.DOTALL)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def safe_copy(src, dst, is_dir=False, remove_debug=False):
    try:
        if is_dir:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
            if remove_debug and dst.suffix == '.py':
                remove_debug_code(dst)
        print(f"복사 성공: {src} -> {dst}")
    except Exception as e:
        print(f"복사 실패: {src}")
        print(f"에러 메시지: {str(e)}")
        return False
    return True

def create_zip(source_dir, output_filename):
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, _, files in os.walk(source_dir):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source_dir)
                print(f"압축 추가: {arcname}")
                zipf.write(file_path, arcname)

def build_package(is_release=False):
    # 빌드 디렉토리 설정
    build_dir = Path("build_package")
    print(f"빌드 디렉토리 생성: {build_dir}")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir()

    # libs 디렉토리 생성
    build_libs_dir = build_dir / "libs"
    build_libs_dir.mkdir()

    # 핵심 파일 복사
    core_files = [
        "manifest.json",
        "__init__.py",
        "main.py",
        "providers.py",
        "bridge.py",
        "answer_checker_window.py"
    ]

    print("\n핵심 파일 복사 시작...")
    for file in core_files:
        if os.path.exists(file):
            safe_copy(Path(file), build_dir / file, remove_debug=is_release)
        else:
            print(f"파일 없음: {file}")

    # 필요한 라이브러리 디렉토리들
    required_libs = [
        "PyQt6",
        "PyQt6_sip-13.9.1.dist-info",
        "PyQt6-6.8.0.dist-info",
        "PyQt6_Qt6-6.8.1.dist-info",
        "bs4",
        "beautifulsoup4-4.12.3.dist-info",
        "soupsieve",
        "soupsieve-2.6.dist-info",
        "requests",
        "requests-2.32.3.dist-info",
        "urllib3",
        "urllib3-2.3.0.dist-info",
        "charset_normalizer",
        "charset_normalizer-3.4.0.dist-info",
        "certifi",
        "certifi-2024.12.14.dist-info",
        "idna",
        "idna-3.10.dist-info"
    ]

    print("\n라이브러리 파일 복사 시작...")
    libs_dir = Path("libs")
    for lib in required_libs:
        src = libs_dir / lib
        if src.exists():
            dst = build_libs_dir / lib
            safe_copy(src, dst, is_dir=src.is_dir())
        else:
            print(f"라이브러리 없음: {lib}")

    # ZIP 파일 생성
    suffix = "" if is_release else "_dev"
    zip_filename = f"MyAnswerChecker{suffix}.ankiaddon"
    print(f"\nZIP 파일 생성 시작: {zip_filename}")
    create_zip(build_dir, zip_filename)

    print(f"\n배포 패키지 생성 완료!")
    print(f"생성된 파일: {zip_filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Anki 플러그인 패키지 빌더')
    parser.add_argument('--release', action='store_true', help='배포용 빌드 생성 (디버그 코드 제거)')
    args = parser.parse_args()

    build_package(is_release=args.release) 