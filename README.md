# hwpConverMd

HWP/HWPX 파일을 Markdown(.md)으로 변환하는 REST API 서버입니다.
CLI, Docker Compose, Kubernetes 배포를 모두 지원하며, MCP 서버 및 Flowise와 연동하여 LLM 기반 문서 처리 파이프라인을 구성할 수 있습니다.

---

## 아키텍처

```
 ┌──────────────────────────────────────────────────────────┐
 │  Flowise (LLM Orchestrator)                              │
 │  ┌────────────┐    ┌──────────────┐    ┌──────────────┐  │
 │  │ Chat Input │───▶│ buildChatflow│───▶│CustomFunction│  │
 │  │ (HWP 업로드)│    │ (base64 추출)│    │ (MCP 호출)   │  │
 │  └────────────┘    └──────────────┘    └──────┬───────┘  │
 └───────────────────────────────────────────────┼──────────┘
                                                 │ JSON-RPC
                                                 ▼
                                    ┌────────────────────┐
                                    │ hwpConverMdMCP     │
                                    │ (MCP Server :3000) │
                                    └────────┬───────────┘
                                             │ multipart/form-data
                                             ▼
                                    ┌────────────────────┐
                                    │ hwpConverMd        │
                                    │ (FastAPI :8000)    │  ◀── 이 프로젝트
                                    └────────────────────┘
```

### 변환 엔진 구조

```
 HWP 파일 (.hwp)
   │
   ├─ 1차: HwpFastConverter (고속)
   │    pyhwp xmlevents → XML → ElementTree → Markdown
   │    ▸ XSLT 건너뛰고 내부 XML 직접 파싱
   │    ▸ 대용량 파일에서 10배 이상 빠름
   │
   └─ 2차: HwpConverter (폴백)
        hwp5html → HTML → BeautifulSoup → markdownify → Markdown
        ▸ 고속 변환 실패 시 자동 폴백

 HWPX 파일 (.hwpx)
   │
   └─ HwpxConverter
        ZIP → XML 직접 파싱 → Markdown
        ▸ 추가 도구 불필요
```

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
| GET | `/health` | 헬스체크 (K8s probe용) | JSON |
| POST | `/api/v1/convert` | HWP/HWPX -> Markdown (JSON) | JSON (`filename`, `markdown`, `download_url`) |
| POST | `/api/v1/convert/raw` | HWP/HWPX -> Markdown (텍스트) | text/markdown |
| POST | `/api/v1/convert/base64` | Base64 HWP -> Markdown (JSON) | JSON (`filename`, `markdown`, `download_url`) |
| GET | `/api/v1/download/{filename}` | 변환된 Markdown 파일 다운로드 | file (text/markdown) |

### 파일 업로드 방법

#### 방법 1: curl 명령어

```bash
# JSON 응답 (filename + markdown + download_url)
curl -X POST http://localhost:8000/api/v1/convert \
  -F "file=@document.hwp"

# 순수 Markdown 텍스트 응답
curl -X POST http://localhost:8000/api/v1/convert/raw \
  -F "file=@document.hwp"

# 결과를 파일로 저장
curl -X POST http://localhost:8000/api/v1/convert/raw \
  -F "file=@document.hwp" \
  -o output/result.md

# Base64 JSON 변환 (Flowise, n8n 등 외부 시스템 연동용)
B64=$(base64 -i document.hwp | tr -d '\n')
curl -X POST http://localhost:8000/api/v1/convert/base64 \
  -H "Content-Type: application/json" \
  -d "{\"filename\":\"document.hwp\",\"content_base64\":\"$B64\"}"

# 변환된 파일 다운로드
curl -O http://localhost:8000/api/v1/download/document_abc123.md
```

#### 방법 2: Python requests

```python
import requests

# JSON 응답
with open("document.hwp", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/convert",
        files={"file": f},
    )

data = response.json()
print(data["markdown"])
print(data["download_url"])  # /api/v1/download/document_abc123.md

# 파일로 저장
with open("output/result.md", "w", encoding="utf-8") as out:
    out.write(data["markdown"])
```

#### 방법 3: Swagger UI (웹 브라우저)

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
python -m app document.hwp

# 파일로 저장
python -m app document.hwp -o output/result.md

# HWPX 파일 변환
python -m app document.hwpx -o output/document.md
```

### CLI 옵션

| 옵션 | 설명 |
|------|------|
| `input` | 입력 파일 경로 (.hwp 또는 .hwpx) |
| `-o`, `--output` | 출력 파일 경로. 미지정 시 표준출력 |

---

## 3. Docker Compose (통합 스택)

`docker-compose.yml`로 API + MCP 서버 + Flowise를 한 번에 기동할 수 있습니다:

```bash
# 전체 스택 기동
docker compose up -d --build

# 개별 서비스 로그
docker compose logs -f api       # HWP API
docker compose logs -f mcp       # MCP 서버
docker compose logs -f flowise   # Flowise
```

### 서비스 구성

| 서비스 | 컨테이너 | 포트 | 역할 |
|--------|----------|------|------|
| `api` | hwp-api | `:8000` | HWP/HWPX -> Markdown 변환 엔진 |
| `mcp` | hwp-mcp | `:3001` | MCP 프로토콜 인터페이스 |


---

## 4. Kubernetes 배포

### 매니페스트 구조

```
k8s_manifest/
├── namespace.yaml           # 네임스페이스 생성
├── configmap.yaml           # 환경변수 ConfigMap
├── rbac.yaml                # RBAC (ServiceAccount, Role, RoleBinding)
├── resource-policy.yaml     # ResourceQuota, LimitRange
├── api-deployment.yaml      # HWP API Deployment + Service + HPA
└── ingress.yaml             # Ingress (hwp-api.your-domain.com)
```

### 배포

```bash
kubectl apply -f k8s_manifest/
```

### 주요 설정

| 항목 | 값 | 비고 |
|------|-----|------|
| Replicas | 2 (HPA: 2~10) | CPU 기반 오토스케일링 |
| CPU Request | 500m~1000m 권장 | HWP 변환은 CPU 집약적 |
| Health Probe | `/health` | liveness + readiness |
| 파일 크기 제한 | `MAX_UPLOAD_SIZE_MB=100` | 환경변수로 설정 |

### Ingress 설정 (필수)

HWP 파일 변환 시 폴백 경로(hwp5html)가 최대 300초 소요될 수 있으므로 Ingress에 다음 annotation이 필요합니다:

```yaml
metadata:
  annotations:
    nginx.ingress.kubernetes.io/proxy-body-size: "50m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "360"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "360"
```

### 다운로드 엔드포인트 주의사항

- 한글 파일명은 RFC 5987 (`filename*=UTF-8''...`) 인코딩으로 Content-Disposition 헤더를 설정합니다.
- HWP API가 **다중 Pod**로 운영되는 경우, 변환한 Pod과 다운로드 요청을 받는 Pod이 다를 수 있습니다.
  - **해결 방법 A**: `/app/output`에 ReadWriteMany PVC를 마운트
  - **해결 방법 B**: Flowise CustomFunction에서 MCP 응답의 markdown을 직접 활용 (download URL 미사용)

---

## 5. 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `ENV` | 실행 환경 (`development` / `production`) | - |
| `MAX_UPLOAD_SIZE_MB` | 최대 업로드 파일 크기 (MB) | `100` |
| `HWP_FAST_DISABLE` | `1`로 설정 시 고속 변환 비활성화 (hwp5html만 사용) | `0` |
| `HWP5HTML_TIMEOUT` | hwp5html 폴백 변환 타임아웃 (초) | `300` |

---

## 6. 테스트

```bash
# 의존성 설치 (최초 1회)
pip install -r requirements-dev.txt

# 전체 테스트 실행
pytest

# 개별 테스트
pytest tests/test_api.py        # API 테스트
pytest tests/test_cli.py        # CLI 테스트
pytest tests/test_converter.py  # 변환 서비스 테스트
```

### 테스트 항목

| 파일 | 테스트 항목 |
|------|-------------|
| `test_converter.py` | HWP/HWPX 변환, 미지원 형식 예외, 파일 없음 예외 |
| `test_api.py` | 헬스체크, JSON 변환, Raw 변환, Base64 변환, 다운로드, 파일 형식 오류 |
| `test_cli.py` | 표준출력, 파일 저장, 오류 처리 |

---

## 프로젝트 구조

```
hwpConverMd/
├── app/
│   ├── __init__.py
│   ├── __main__.py                # CLI 진입점
│   ├── main.py                    # FastAPI 앱
│   ├── cli.py                     # CLI 인터페이스
│   ├── schemas.py                 # Pydantic 스키마
│   ├── api/
│   │   └── endpoints.py           # REST API 엔드포인트
│   ├── core/
│   │   └── exceptions.py          # 커스텀 예외
│   ├── services/
│   │   ├── converter.py           # 변환 디스패처 (매직바이트 감지 + 라우팅)
│   │   ├── hwp_fast_converter.py  # HWP 고속 변환 (XML 직접 파싱)
│   │   ├── hwp_converter.py       # HWP 변환 폴백 (hwp5html 경유)
│   │   └── hwpx_converter.py      # HWPX 변환 (XML 직접 파싱)
│   └── utils/
│       └── file_manager.py        # 임시 파일 관리, OUTPUT_DIR
├── k8s_manifest/                  # Kubernetes 매니페스트
├── tests/                         # pytest 테스트
├── temp/                          # 임시 파일 (API 업로드 시 사용)
├── output/                        # 변환 결과 저장 (.md 파일)
├── requirements.txt               # 런타임 의존성
├── requirements-dev.txt           # 개발/테스트 의존성
├── Dockerfile
└── pytest.ini
```

## 지원 형식

| 입력 | 변환 방식 | 비고 |
|------|-----------|------|
| `.hwp` | **1차**: pyhwp XML 직접 파싱 (고속) | XSLT 건너뜀, 10배+ 빠름 |
|        | **2차**: hwp5html -> HTML -> Markdown (폴백) | 고속 변환 실패 시 자동 전환 |
| `.hwpx` | ZIP -> XML 직접 파싱 -> Markdown | 추가 도구 불필요 |

### 타임아웃 설정

| 구성 요소 | 타임아웃 | 설명 |
|-----------|---------|------|
| HwpFastConverter | 제한 없음 (수 초 내 완료) | XML 직접 파싱, XSLT 미사용 |
| HwpConverter (hwp5html 폴백) | 300초 | `HWP5HTML_TIMEOUT` 환경변수로 변경 가능 |
| Uvicorn keep-alive | 360초 | Dockerfile `--timeout-keep-alive` |
| Nginx Ingress proxy | 360초 | `proxy-read-timeout`, `proxy-send-timeout` |

## 응답 예시

### POST /api/v1/convert (JSON)

```json
{
  "filename": "document.hwp",
  "markdown": "# 제목\n\n본문 내용...",
  "download_url": "/api/v1/download/document_a1b2c3.md"
}
```

### POST /api/v1/convert/base64 (JSON)

```json
// 요청
{
  "filename": "document.hwp",
  "content_base64": "0M8R4KGxGuEAAAAAAAA..."
}

// 응답 (convert와 동일)
{
  "filename": "document.hwp",
  "markdown": "# 제목\n\n본문 내용...",
  "download_url": "/api/v1/download/document_a1b2c3.md"
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
