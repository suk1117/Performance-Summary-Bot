"""봇 런처 - python -m 대신 직접 실행 (한글 경로 호환)"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from portfolio_bot.main import main

if __name__ == "__main__":
    main()
