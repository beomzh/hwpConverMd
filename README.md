# hwpConverMd

HWP/HWPX 파일을 Markdown(.md)으로 변환하는 도구입니다.
REST API 서버와 CLI 두 가지 방식을 지원합니다.

---

## 설치

```bash
# 저장소 클론
git clone https://github.com/beomzh/hwpConverMd.git
cd hwpConverMd

# 가상환경 생성 및 활성화
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 의존성 설치
pip install -r requirements.txt

# 개발/테스트 의존성 포함 설치
pip install -r requirements-dev.txt
```

### pyhwp 추가 설정 (HWP 변환에 필요)

```bash
# pyhwp는 hwp5html 명령어를 제공합니다
pip install pyhwp

# 설치 확인
hwp5html --help
```

---

## 1. REST API 서버

### 서버 시작

```bash
# 직접 실행
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 또는 Docker로 실행
docker compose up --build
```

서버가 시작되면 다음 URL에서 확인:
- 헬스체크: http://localhost:8000/
- API 문서 (Swagger UI): http://localhost:8000/docs
- API 문서 (ReDoc): http://localhost:8000/redoc

### API 엔드포인트

| 메서드 | 경로 | 설명 | 응답 형식 |
|--------|------|------|-----------|
| GET | `/` | 헬스체크 | JSON |
| POST | `/api/v1/convert` | HWP/HWPX → Markdown (JSON) | JSON |
| POST | `/api/v1/convert/raw` | HWP/HWPX → Markdown (텍스트) | text/markdown |

### 파일 업로드 방법

#### 방법 1: curl 명령어

```bash
# JSON 응답 (filename + markdown 필드)
curl -X POST http://localhost:8000/api/v1/convert \
  -F "file=@tests/규격서_OPENMARU COP_오픈마루.hwp"

# 순수 Markdown 텍스트 응답
curl -X POST http://localhost:8000/api/v1/convert/raw \
  -F "file=@tests/규격서_OPENMARU COP_오픈마루.hwp"

# 결과를 파일로 저장
curl -X POST http://localhost:8000/api/v1/convert/raw \
  -F "file=@tests/규격서_OPENMARU COP_오픈마루.hwp" \
  -o output/result.md
```

#### 방법 2: Python requests

```python
import requests

# JSON 응답
with open("tests/규격서_OPENMARU COP_오픈마루.hwp", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/convert",
        files={"file": f},
    )

data = response.json()
print(data["markdown"])

# 파일로 저장
with open("output/result.md", "w", encoding="utf-8") as out:
    out.write(data["markdown"])
```

#### 방법 3: httpx (비동기)

```python
import httpx
import asyncio

async def convert():
    async with httpx.AsyncClient() as client:
        with open("tests/규격서_OPENMARU COP_오픈마루.hwp", "rb") as f:
            response = await client.post(
                "http://localhost:8000/api/v1/convert/raw",
                files={"file": f},
            )
        print(response.text)

asyncio.run(convert())
```

#### 방법 4: Swagger UI (웹 브라우저)

1. 서버 시작 후 http://localhost:8000/docs 접속
2. `POST /api/v1/convert` 엔드포인트 클릭
3. "Try it out" 버튼 클릭
4. "파일 선택" 버튼으로 HWP/HWPX 파일 선택
5. "Execute" 클릭
6. 아래 Response body에서 변환된 Markdown 확인

---

## 2. CLI (명령줄 도구)

```bash
# 표준출력으로 출력
python -m app tests/규격서_OPENMARU\ COP_오픈마루.hwp

# 파일로 저장
python -m app tests/규격서_OPENMARU\ COP_오픈마루.hwp -o output/result.md

# HWPX 파일 변환
python -m app document.hwpx -o output/document.md
```

### CLI 옵션

| 옵션 | 설명 |
|------|------|
| `input` | 입력 파일 경로 (.hwp 또는 .hwpx) |
| `-o`, `--output` | 출력 파일 경로. 미지정 시 표준출력 |

---

## 3. 테스트

### 테스트 파일

`tests/` 디렉토리에 테스트용 HWP 파일이 포함되어 있습니다:

```
tests/
  규격서_OPENMARU COP_오픈마루.hwp   # 테스트용 HWP 파일
```

추가 테스트 파일을 넣으려면 `.hwp` 또는 `.hwpx` 파일을 `tests/` 디렉토리에 복사하면 됩니다.

### 전체 테스트 실행

```bash
# 의존성 설치 (최초 1회)
pip install -r requirements-dev.txt

# 전체 테스트 실행
pytest

# 특정 테스트 파일만 실행
pytest tests/test_api.py        # API 테스트만
pytest tests/test_cli.py        # CLI 테스트만
pytest tests/test_converter.py  # 변환 서비스 테스트만

# 특정 테스트 함수만 실행
pytest tests/test_api.py::test_convert_hwp_api
```

### 테스트 항목

**test_converter.py** - 변환 서비스 단위 테스트
- `test_convert_hwp_file`: HWP → Markdown 변환
- `test_convert_hwpx_file`: HWPX → Markdown 변환 (hwpx 파일이 있을 때)
- `test_unsupported_format`: 지원하지 않는 형식 예외 처리
- `test_convert_nonexistent_file`: 존재하지 않는 파일 예외 처리

**test_api.py** - REST API 통합 테스트
- `test_health_check`: 헬스체크 엔드포인트
- `test_convert_hwp_api`: HWP 업로드 → JSON 응답
- `test_convert_raw_api`: HWP 업로드 → Markdown 텍스트 응답
- `test_upload_invalid_format`: 잘못된 형식 업로드 시 400 에러

**test_cli.py** - CLI 통합 테스트
- `test_cli_hwp_to_stdout`: HWP → 표준출력
- `test_cli_hwp_to_file`: HWP → .md 파일 저장
- `test_cli_invalid_format`: 잘못된 형식 오류 처리
- `test_cli_nonexistent_file`: 없는 파일 오류 처리

### 수동 테스트 (curl)

서버가 실행된 상태에서:

```bash
# 1. 헬스체크
curl http://localhost:8000/

# 2. HWP 변환 (JSON)
curl -X POST http://localhost:8000/api/v1/convert \
  -F "file=@tests/규격서_OPENMARU COP_오픈마루.hwp" | python -m json.tool

# 3. HWP 변환 (순수 Markdown) 결과를 파일로 저장
curl -X POST http://localhost:8000/api/v1/convert/raw \
  -F "file=@tests/규격서_OPENMARU COP_오픈마루.hwp" \
  -o output/규격서.md

# 4. 잘못된 형식 업로드 (400 에러 확인)
curl -X POST http://localhost:8000/api/v1/convert \
  -F "file=@README.md"
```

---

## 프로젝트 구조

```
hwpConverMd/
├── app/
│   ├── __init__.py
│   ├── __main__.py            # CLI 진입점
│   ├── main.py                # FastAPI 앱
│   ├── cli.py                 # CLI 인터페이스
│   ├── api/
│   │   └── endpoints.py       # REST API 엔드포인트
│   ├── core/
│   │   └── exceptions.py      # 커스텀 예외
│   ├── services/
│   │   ├── converter.py       # 변환 디스패처
│   │   ├── hwp_converter.py   # HWP → Markdown (hwp5html 경유)
│   │   └── hwpx_converter.py  # HWPX → Markdown (XML 직접 파싱)
│   └── utils/
│       └── file_manager.py    # 임시 파일 관리
├── tests/
│   ├── conftest.py            # pytest 공통 fixture
│   ├── test_converter.py      # 변환 서비스 테스트
│   ├── test_api.py            # API 통합 테스트
│   ├── test_cli.py            # CLI 통합 테스트
│   └── *.hwp / *.hwpx        # 테스트용 문서 파일
├── temp/                      # 임시 파일 (API 업로드 시 사용)
├── output/                    # 변환 결과 저장 디렉토리
├── requirements.txt           # 런타임 의존성
├── requirements-dev.txt       # 개발/테스트 의존성
├── Dockerfile
├── docker-compose.yml
└── pytest.ini
```

## 지원 형식

| 입력 | 변환 방식 | 비고 |
|------|-----------|------|
| `.hwp` | hwp5html → HTML → Markdown | pyhwp의 hwp5html 명령어 필요 |
| `.hwpx` | ZIP → XML 직접 파싱 → Markdown | 추가 도구 불필요 |

## 응답 예시

### POST /api/v1/convert (JSON)

```json
{
  "filename": "document.hwp",
  "markdown": "# 제목\n\n본문 내용이 여기에 표시됩니다.\n\n## 소제목\n\n| 항목 | 값 |\n| --- | --- |\n| A | 100 |"
}
```

### POST /api/v1/convert/raw (text/markdown)

```markdown
# 제목

본문 내용이 여기에 표시됩니다.

## 소제목

| 항목 | 값 |
| --- | --- |
| A | 100 |
```
