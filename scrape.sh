#!/usr/bin/env bash
#
# 抓取 os-labs 站点并写入 raw/。
# 用法:
#   ./scrape.sh              # 等价于 python -m oslabs_scraper scrape
#   ./scrape.sh verify       # 透传子命令与参数
#
set -euo pipefail
cd "$(dirname "$0")"

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  PYTHON=python
fi

if [ "$#" -eq 0 ]; then
  exec "$PYTHON" -m oslabs_scraper scrape
fi

exec "$PYTHON" -m oslabs_scraper "$@"
