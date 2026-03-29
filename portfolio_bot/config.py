from __future__ import annotations
import os
import logging
import pytz
from dotenv import load_dotenv

load_dotenv()

# ══ 환경변수 ══════════════════════════════════════════════
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID", "0"))
NGROK_TOKEN      = os.getenv("NGROK_TOKEN", "")
FLASK_PORT       = int(os.getenv("FLASK_PORT", "5050"))
# USE_NGROK=false → ngrok 없이 Flask 직접 노출 (GCP 등 공인 IP 서버에서 사용)
# FLASK_PUBLIC_URL → 외부에서 접근 가능한 URL (예: http://34.xx.xx.xx:5050)
USE_NGROK        = os.getenv("USE_NGROK", "true").lower() not in ("false", "0", "no")
FLASK_PUBLIC_URL = os.getenv("FLASK_PUBLIC_URL", "")

KST = pytz.timezone("Asia/Seoul")

# ══ 데이터 디렉터리 ═══════════════════════════════════════
# portfolio_bot/ 패키지의 부모 디렉터리(프로젝트 루트)에 data/ 생성
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ══ HTTP 헤더 (price_fetcher 공용) ════════════════════════
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://finance.naver.com/",
}

# ══ 로깅 설정 ══════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S", level=logging.INFO,
)
log = logging.getLogger(__name__)
