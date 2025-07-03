# MCP Hub Python 🐍

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](./CONTRIBUTING.md)

**Model Context Protocol (MCP) 서버들을 위한 현대적이고 고성능인 중앙 집중식 관리 허브**

MCP Hub Python은 여러 MCP 서버를 통합 관리하고, 모든 MCP 클라이언트가 단일 엔드포인트를 통해 모든 서버 기능에 접근할 수 있게 해주는 FastAPI 기반의 강력한 중앙 협조자입니다.

![MCP Hub Architecture](docs/images/architecture.png)

## 🌟 주요 특징

### 🎯 통합된 MCP 경험
- **단일 엔드포인트**: 모든 MCP 클라이언트가 `localhost:3001/mcp` 하나만 설정
- **자동 네임스페이싱**: 서버 간 충돌 방지 (예: `memory::save`, `filesystem::search`)
- **실시간 동기화**: 서버 추가/제거 시 즉시 기능 업데이트
- **간편한 클라이언트 설정**: 복잡한 다중 서버 설정 대신 하나의 연결만 필요

### 🚀 현대적인 Python 아키텍처
- **FastAPI**: 고성능 비동기 웹 프레임워크
- **Pydantic**: 완전한 타입 안전성과 데이터 검증
- **asyncio**: 네이티브 비동기 성능
- **공식 MCP SDK**: `mcp[cli]` 패키지 기반

### 🛠️ 강력한 서버 관리
- **동적 서버 제어**: 실시간 서버 시작/중지/재시작
- **다중 전송 프로토콜**: STDIO, HTTP, SSE 지원
- **환경 변수 처리**: 보안 강화된 환경 변수 및 명령 실행
- **자동 복구**: 연결 실패 시 지능적 재연결

### 📊 실시간 모니터링 & 관리
- **웹 기반 관리 UI**: 직관적인 대시보드와 서버 상태 모니터링
- **자동 API 문서화**: OpenAPI/Swagger 자동 생성
- **Server-Sent Events**: 실시간 이벤트 스트리밍
- **구조화된 로깅**: 상세한 시스템 로그와 디버깅 정보

### 🔧 개발자 친화적
- **Rich CLI**: 아름다운 터미널 사용자 인터페이스
- **타입 힌트**: 완전한 타입 안전성
- **핫 리로드**: 개발 중 자동 재시작
- **설정 파일 감시**: 설정 변경 시 자동 서버 재연결

## 📦 설치 방법

### 요구사항
- Python 3.10 이상
- pip 패키지 관리자

### 개발 모드 설치 (추천)
```bash
# 저장소 클론
git clone https://github.com/your-org/mcp-hub.git
cd mcp-hub

# 개발 모드로 설치
pip install -e .

# 의존성 설치
pip install -r requirements.txt
```

### PyPI 설치 (출시 예정)
```bash
pip install mcp-hub-python
```

## 🚀 빠른 시작

### 1. 기본 설정 파일 생성
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username"],
      "disabled": false
    },
    "memory": {
      "command": "python",
      "args": ["-m", "mcp_server_memory"],
      "env": {
        "MEMORY_DB_PATH": "/tmp/memory.db"
      }
    }
  }
}
```

### 2. MCP Hub 시작
```bash
# 기본 실행
python -m mcp_hub.cli --port 3001 --config config.json

# 고급 옵션과 함께
python -m mcp_hub.cli \
  --port 3001 \
  --config config.json \
  --host 0.0.0.0 \
  --log-level DEBUG \
  --watch
```

### 3. 웹 UI 접속
브라우저에서 다음 주소로 접속:
- **관리 UI**: http://localhost:3001
- **API 문서**: http://localhost:3001/docs
- **ReDoc**: http://localhost:3001/redoc

### 4. MCP 클라이언트 설정

#### Claude Desktop
```json
{
  "mcpServers": {
    "mcp-hub": {
      "url": "http://localhost:3001/mcp"
    }
  }
}
```

#### Cline (VS Code)
```json
{
  "mcpServers": {
    "Hub": {
      "url": "http://localhost:3001/mcp"
    }
  }
}
```

## ⚙️ 설정 가이드

### 기본 서버 설정
```json
{
  "mcpServers": {
    "local-server": {
      "command": "python",
      "args": ["-m", "my_mcp_server"],
      "env": {
        "API_KEY": "your-api-key",
        "DATABASE_URL": "sqlite:///data.db"
      },
      "disabled": false
    }
  }
}
```

### 원격 서버 설정
```json
{
  "mcpServers": {
    "remote-server": {
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer your-token",
        "Content-Type": "application/json"
      }
    }
  }
}
```

### 환경 변수 및 명령 실행
```json
{
  "mcpServers": {
    "secure-server": {
      "command": "${MCP_BINARY_PATH}/server",
      "args": [
        "--token", "${API_TOKEN}",
        "--secret", "${cmd: op read op://vault/secret}"
      ],
      "env": {
        "API_TOKEN": "${cmd: aws ssm get-parameter --name /app/token --query Parameter.Value --output text}",
        "DB_URL": "postgresql://user:${DB_PASSWORD}@localhost/app"
      }
    }
  }
}
```

### 개발 모드 설정
```json
{
  "mcpServers": {
    "dev-server": {
      "command": "python",
      "args": ["-m", "my_mcp_server"],
      "dev": {
        "enabled": true,
        "watch": ["src/**/*.py", "**/*.json"],
        "cwd": "/absolute/path/to/server/directory"
      }
    }
  }
}
```

## 🎮 CLI 명령어

### 기본 명령어
```bash
# 서버 시작
python -m mcp_hub.cli --port 3001 --config config.json

# 설정 파일 검증
python -m mcp_hub.cli validate --config config.json

# 마켓플레이스 조회
python -m mcp_hub.cli marketplace

# 도움말
python -m mcp_hub.cli --help
```

### CLI 옵션

| 옵션 | 설명 | 기본값 | 필수 |
|------|------|--------|------|
| `--port` | HTTP 서버 포트 | - | ✅ |
| `--config` | 설정 파일 경로 | - | ✅ |
| `--host` | 바인딩 호스트 | `localhost` | ❌ |
| `--watch` | 설정 파일 변경 감지 | `false` | ❌ |
| `--log-level` | 로그 레벨 (DEBUG/INFO/WARNING/ERROR) | `INFO` | ❌ |
| `--reload` | 개발 모드 자동 리로드 | `false` | ❌ |
| `--auto-shutdown` | 클라이언트 없을 때 자동 종료 | `false` | ❌ |
| `--shutdown-delay` | 자동 종료 지연 시간(초) | `10` | ❌ |

## 🏗️ 아키텍처

### 시스템 구조
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   MCP Clients   │────│   MCP Hub       │────│   MCP Servers   │
│                 │    │   Python        │    │                 │
│ • Claude        │◄──►│                 │◄──►│ • Filesystem    │
│ • Cline         │    │ ┌─────────────┐ │    │ • Memory        │
│ • Custom Apps   │    │ │  FastAPI    │ │    │ • Database      │
│                 │    │ │  Server     │ │    │ • Custom        │
│                 │    │ └─────────────┘ │    │                 │
│                 │    │ ┌─────────────┐ │    │                 │
│                 │    │ │   Web UI    │ │    │                 │
│                 │    │ └─────────────┘ │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### 핵심 컴포넌트

#### 🏗️ 아키텍처 모듈
- **`hub.py`**: 중앙 허브 로직과 서버 오케스트레이션
- **`connection.py`**: MCP 서버 연결 관리 (STDIO/HTTP/SSE)
- **`server.py`**: FastAPI 기반 HTTP 서버
- **`config.py`**: 설정 관리 및 실시간 파일 감시

#### 🔧 지원 모듈
- **`events.py`**: 비동기 이벤트 시스템 (Node.js EventEmitter 스타일)
- **`env_resolver.py`**: 보안 강화된 환경 변수 처리
- **`sse_manager.py`**: Server-Sent Events 관리
- **`marketplace.py`**: 서버 마켓플레이스 통합
- **`types.py`**: Pydantic 기반 타입 정의
- **`cli.py`**: Rich 기반 아름다운 CLI

#### 🎨 사용자 인터페이스
- **`templates/index.html`**: Alpine.js + Tailwind CSS 웹 UI

### 데이터 흐름
1. **클라이언트 요청** → MCP Hub (`/mcp` 엔드포인트)
2. **요청 라우팅** → 네임스페이스 기반 서버 선택
3. **서버 통신** → STDIO/HTTP/SSE를 통한 서버 호출
4. **응답 처리** → 결과 수집 및 변환
5. **통합 응답** → 클라이언트에게 표준 MCP 응답 반환
6. **실시간 이벤트** → SSE를 통한 상태 업데이트

## 🔧 개발 가이드

### 개발 환경 설정
```bash
# 개발 의존성 설치
pip install -e ".[dev]"

# 코드 포맷팅
black src/
isort src/

# 타입 체킹
mypy src/

# 린팅
flake8 src/

# 테스트 실행
pytest tests/ -v

# 커버리지 확인
pytest --cov=src/mcp_hub tests/
```

### 프로젝트 구조
```
mcp-hub/
├── src/mcp_hub/              # Python 패키지
│   ├── __init__.py           # 패키지 초기화
│   ├── cli.py                # Rich 기반 CLI
│   ├── server.py             # FastAPI 웹 서버
│   ├── hub.py                # 핵심 허브 로직
│   ├── connection.py         # 연결 관리
│   ├── config.py             # 설정 관리
│   ├── marketplace.py        # 마켓플레이스
│   ├── events.py             # 이벤트 시스템
│   ├── sse_manager.py        # SSE 관리
│   ├── env_resolver.py       # 환경 변수 처리
│   ├── types.py              # Pydantic 타입
│   └── templates/            # 웹 UI
│       └── index.html        # 메인 페이지
├── tests/                    # 테스트 파일
├── examples/                 # 예제 설정
├── pyproject.toml            # 프로젝트 설정
├── requirements.txt          # 의존성
└── README.md                 # 이 문서
```

### API 엔드포인트

#### 관리 API
- `GET /` - 웹 UI 홈페이지
- `GET /health` - 헬스체크
- `GET /api/status` - 허브 상태 조회
- `GET /api/stats` - 통계 정보
- `GET /api/servers` - 서버 목록
- `POST /api/servers/{name}/reconnect` - 서버 재연결
- `GET /api/tools` - 사용 가능한 도구 목록
- `GET /api/resources` - 리소스 목록
- `GET /api/prompts` - 프롬프트 목록
- `GET /api/events` - 실시간 이벤트 스트림 (SSE)

#### MCP 프로토콜 API
- `POST /mcp` - MCP 프로토콜 메시지 처리

#### 자동 문서화
- `GET /docs` - OpenAPI/Swagger UI
- `GET /redoc` - ReDoc 문서
- `GET /openapi.json` - OpenAPI 스키마

## 🧪 테스트

### 테스트 실행
```bash
# 전체 테스트
pytest tests/ -v

# 특정 테스트 파일
pytest tests/test_hub.py -v

# 특정 테스트 함수
pytest tests/test_hub.py::test_server_connection -v

# 커버리지와 함께
pytest --cov=src/mcp_hub --cov-report=html tests/
```

## 🚀 배포

### Docker 배포
```dockerfile
FROM python:3.10-slim

WORKDIR /app

# 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY src/ src/
COPY pyproject.toml .

# 패키지 설치
RUN pip install -e .

# 포트 노출
EXPOSE 3001

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:3001/health || exit 1

# 실행
CMD ["python", "-m", "mcp_hub.cli", "--port", "3001", "--config", "config.json", "--host", "0.0.0.0"]
```

## 🔍 트러블슈팅

### 일반적인 문제들

#### 1. 서버 연결 실패
```bash
# 디버그 모드로 실행
python -m mcp_hub.cli --log-level DEBUG --config config.json --port 3001

# 설정 파일 검증
python -m mcp_hub.cli validate --config config.json
```

#### 2. 포트 충돌
```bash
# 포트 사용 확인
lsof -i :3001

# 다른 포트 사용
python -m mcp_hub.cli --port 3002 --config config.json
```

#### 3. 권한 문제
```bash
# 파일 권한 확인
ls -la config.json

# 실행 권한 부여
chmod +x /path/to/mcp/server
```

## 🤝 기여하기

### 기여 절차
1. **이슈 확인**: [GitHub Issues](https://github.com/your-org/mcp-hub/issues)에서 기존 이슈 확인
2. **브랜치 생성**: `git checkout -b feature/amazing-feature`
3. **개발**: 코딩 스타일 가이드 준수
4. **테스트**: 새로운 기능에 대한 테스트 작성
5. **커밋**: 의미 있는 커밋 메시지 작성
6. **푸시**: `git push origin feature/amazing-feature`
7. **PR 생성**: Pull Request 생성 및 설명 작성

### 코딩 스타일

#### Python 스타일 가이드
- **Black**: 자동 코드 포맷팅
- **isort**: 임포트 정렬
- **mypy**: 타입 체킹 (strict 모드)
- **flake8**: 린팅 (PEP 8 준수)

#### 커밋 메시지 규칙
```
Type(scope): Brief description

Longer description if needed

- Detailed changes
- References #issue-number
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`

## 📄 라이선스

MIT License - 자세한 내용은 [LICENSE](LICENSE.md) 파일을 참조하세요.

## 🙏 감사의 말

- [Model Context Protocol](https://modelcontextprotocol.io/) - 혁신적인 프로토콜 표준
- [FastAPI](https://fastapi.tiangolo.com/) - 현대적인 고성능 웹 프레임워크
- [Pydantic](https://docs.pydantic.dev/) - 강력한 데이터 검증 및 직렬화
- [Rich](https://github.com/Textualize/rich) - 아름다운 터미널 UI
- [Alpine.js](https://alpinejs.dev/) - 가벼운 프론트엔드 프레임워크
- [Tailwind CSS](https://tailwindcss.com/) - 유틸리티 우선 CSS 프레임워크

## 📞 지원 및 커뮤니티

### 도움 받기
- **이슈 리포트**: [GitHub Issues](https://github.com/your-org/mcp-hub/issues)
- **기능 요청**: [GitHub Discussions](https://github.com/your-org/mcp-hub/discussions)
- **문서**: [프로젝트 Wiki](https://github.com/your-org/mcp-hub/wiki)

---

**MCP Hub Python과 함께 Model Context Protocol의 무한한 가능성을 경험해보세요!** 🚀✨ 