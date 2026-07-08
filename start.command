#!/bin/bash
# Fund Prism 启动器 — 双击运行
# 同时启动后端 (FastAPI) + 前端 (Vite dev server)，自动打开浏览器

# 不使用 set -e，避免后台命令的非零退出码导致脚本提前退出

# ---- 路径配置 ----
PROJECT_DIR="/Users/jerry/Documents/vibe/fund-prism"
BACKEND_PORT=8000
FRONTEND_PORT=5173
FRONTEND_URL="http://localhost:${FRONTEND_PORT}"
BACKEND_URL="http://localhost:${BACKEND_PORT}"
export FUND_PRISM_API_URL="${BACKEND_URL}"

# ---- 颜色输出 ----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo -e "${CYAN}  Fund Prism 启动器${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════${NC}"
echo ""

# 检查项目目录
if [ ! -d "$PROJECT_DIR" ]; then
  echo -e "${RED}错误：项目目录不存在 $PROJECT_DIR${NC}"
  echo "请编辑此文件修改 PROJECT_DIR 路径"
  read -n 1 -s -r -p "按任意键退出..."
  exit 1
fi

cd "$PROJECT_DIR"

# ---- 清理函数：退出时杀掉后台进程 ----
cleanup() {
  echo ""
  echo -e "${YELLOW}正在停止服务...${NC}"
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    kill "$FRONTEND_PID" 2>/dev/null
  fi
  # 清理子进程
  pkill -f "uvicorn fund_research.api.app" 2>/dev/null
  pkill -f "vite.*fund-prism/frontend" 2>/dev/null
  echo -e "${GREEN}已停止。${NC}"
}
trap cleanup EXIT SIGINT SIGTERM

# ---- 检查端口占用 ----
check_port() {
  local port=$1
  if lsof -i :"$port" -t -sTCP:LISTEN >/dev/null 2>&1; then
    echo -e "${YELLOW}端口 $port 已被占用，尝试释放...${NC}"
    lsof -i :"$port" -t -sTCP:LISTEN | xargs kill -9 2>/dev/null
    sleep 1
  fi
}

echo -e "${YELLOW}[1/4] 检查端口...${NC}"
check_port $BACKEND_PORT
check_port $FRONTEND_PORT
echo -e "${GREEN}  端口可用${NC}"
echo ""

# ---- 启动后端 ----
echo -e "${YELLOW}[2/4] 启动后端 (FastAPI @ :${BACKEND_PORT})...${NC}"
export FUND_DB_PATH="${PROJECT_DIR}/data/fund_research.sqlite"
uv run uvicorn fund_research.api.app:create_app \
  --host 127.0.0.1 \
  --port $BACKEND_PORT \
  --factory \
  > /tmp/fund_prism_backend.log 2>&1 &
BACKEND_PID=$!
echo -e "${GREEN}  后端 PID: ${BACKEND_PID}${NC}"
echo ""

# ---- 启动前端 ----
echo -e "${YELLOW}[3/4] 启动前端 (Vite dev @ :${FRONTEND_PORT})...${NC}"
cd "${PROJECT_DIR}/frontend"
npm run dev -- --port $FRONTEND_PORT > /tmp/fund_prism_frontend.log 2>&1 &
FRONTEND_PID=$!
echo -e "${GREEN}  前端 PID: ${FRONTEND_PID}${NC}"
echo ""

# ---- 等待服务就绪 ----
echo -e "${YELLOW}[4/4] 等待服务就绪...${NC}"

wait_for_url() {
  local url=$1
  local name=$2
  local pid=$3
  local logfile=$4
  local max_wait=30
  local waited=0
  while [ $waited -lt $max_wait ]; do
    if curl -s "$url" >/dev/null 2>&1; then
      echo -e "${GREEN}  ${name} 已就绪${NC}"
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
    if ! kill -0 "$pid" 2>/dev/null; then
      echo -e "${RED}  ${name} 启动失败${NC}"
      echo -e "  日志：${YELLOW}${logfile}${NC}"
      return 1
    fi
  done
  echo -e "${YELLOW}  ${name} 启动超时（${max_wait}s），可能仍在加载${NC}"
  return 0
}

wait_for_url "${BACKEND_URL}/api/v2/health" "后端" "$BACKEND_PID" "/tmp/fund_prism_backend.log"
wait_for_url "$FRONTEND_URL" "前端" "$FRONTEND_PID" "/tmp/fund_prism_frontend.log"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Fund Prism 已启动！${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  前端：  ${CYAN}${FRONTEND_URL}${NC}"
echo -e "  后端：  ${CYAN}${BACKEND_URL}/api/v2/health${NC}"
echo ""
echo -e "  后端日志：  ${YELLOW}/tmp/fund_prism_backend.log${NC}"
echo -e "  前端日志：  ${YELLOW}/tmp/fund_prism_frontend.log${NC}"
echo ""
echo -e "${YELLOW}  关闭此窗口将停止所有服务${NC}"
echo ""

# ---- 自动打开浏览器 ----
sleep 1
open "$FRONTEND_URL"

# ---- 保持前台运行 ----
# 用无限循环 + sleep 替代 wait，避免子进程 stdio 重定向导致
# shell 提前收到 EOF 而退出（这是 .command 双击自动关闭的常见原因）
while true; do
  # 检查子进程是否还活着
  backends_alive=false
  frontends_alive=false
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    backends_alive=true
  fi
  if [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
    frontends_alive=true
  fi
  if [ "$backends_alive" = false ] || [ "$frontends_alive" = false ]; then
    echo ""
    if [ "$backends_alive" = false ]; then
      echo -e "${RED}后端已退出，查看日志：tail -50 /tmp/fund_prism_backend.log${NC}"
    fi
    if [ "$frontends_alive" = false ]; then
      echo -e "${RED}前端已退出，查看日志：tail -50 /tmp/fund_prism_frontend.log${NC}"
    fi
    echo ""
    echo -e "${YELLOW}服务已停止。按任意键关闭窗口...${NC}"
    read -n 1 -s -r -t 5 || true
    break
  fi
  sleep 2
done
