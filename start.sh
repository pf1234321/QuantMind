#!/usr/bin/env bash
# ============================================================
# QuantMind 前后端一键管理脚本
#
# 用法:
#   ./start.sh            # 启动调度器 + API + 前端
#   ./start.sh start      # 同上
#   ./start.sh stop       # 停止全部服务
#   ./start.sh restart    # 重启全部服务
#   ./start.sh status     # 查看全部服务状态
#
# 说明:
#   - 后端使用项目自己的 .venv 虚拟环境
#   - 前端使用 frontend/node_modules/.bin/vite
#   - API 禁用内嵌调度器，避免重复执行定时任务
#   - PID 文件 + pgrep 双保险检测，避免重复启动
# ============================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY="$SCRIPT_DIR/.venv/bin/python"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
VITE="$FRONTEND_DIR/node_modules/.bin/vite"
LOG_DIR="$SCRIPT_DIR/data/logs"
APP_LOG="$LOG_DIR/app.log"
mkdir -p "$LOG_DIR"

SCHED_PID="$LOG_DIR/scheduler.pid"
RUNTIME_LOG="$LOG_DIR/runtime.log"
SCHED_PATTERN="python -m app\.scheduler"

API_PID="$LOG_DIR/api.pid"
API_PATTERN="python run\.py"

FRONT_PID="$LOG_DIR/frontend.pid"
FRONT_LOG="$LOG_DIR/frontend.log"
FRONT_PATTERN="vite --host 0\.0\.0\.0"

is_running() {
    local pid_file="$1" pattern="$2"
    if [ -f "$pid_file" ]; then
        local pid
        pid="$(cat "$pid_file" 2>/dev/null || echo '')"
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
    fi
    pgrep -f "$pattern" >/dev/null 2>&1
}

start_scheduler() {
    if is_running "$SCHED_PID" "$SCHED_PATTERN"; then
        echo "[调度器] 已在运行，跳过启动"
        return 0
    fi
    rm -f "$SCHED_PID"
    echo "[调度器] 启动中..."
    nohup "$PY" -m app.scheduler > /dev/null 2>> "$RUNTIME_LOG" &
    echo $! > "$SCHED_PID"
    sleep 2
    if is_running "$SCHED_PID" "$SCHED_PATTERN"; then
        echo "[调度器] 启动成功 (PID $(cat "$SCHED_PID"))"
    else
        echo "[调度器] 启动失败，请查看日志: $RUNTIME_LOG 或 $APP_LOG"
        rm -f "$SCHED_PID"
        return 1
    fi
}

start_api() {
    if is_running "$API_PID" "$API_PATTERN"; then
        echo "[API服务] 已在运行，跳过启动"
        return 0
    fi
    rm -f "$API_PID"
    echo "[API服务] 启动中..."
    CHANPY_PATH="$SCRIPT_DIR/chan.py" PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" SCHEDULER_ENABLED=false nohup "$PY" run.py > /dev/null 2>> "$RUNTIME_LOG" &
    echo $! > "$API_PID"
    sleep 2
    if is_running "$API_PID" "$API_PATTERN"; then
        echo "[API服务] 启动成功 (PID $(cat "$API_PID"))"
    else
        echo "[API服务] 启动失败，请查看日志: $RUNTIME_LOG 或 $APP_LOG"
        rm -f "$API_PID"
        return 1
    fi
}

start_frontend() {
    if is_running "$FRONT_PID" "$FRONT_PATTERN"; then
        echo "[前端服务] 已在运行，跳过启动"
        return 0
    fi
    if [ ! -x "$VITE" ]; then
        echo "[前端服务] 启动失败，未找到 $VITE"
        echo "请先执行: cd frontend && npm install"
        return 1
    fi
    rm -f "$FRONT_PID"
    echo "[前端服务] 启动中..."
    (cd "$FRONTEND_DIR" && nohup "$VITE" --host 0.0.0.0 >> "$FRONT_LOG" 2>&1) &
    echo $! > "$FRONT_PID"
    sleep 2
    if is_running "$FRONT_PID" "$FRONT_PATTERN"; then
        echo "[前端服务] 启动成功 (PID $(cat "$FRONT_PID"))"
    else
        echo "[前端服务] 启动失败，请查看日志: $FRONT_LOG"
        rm -f "$FRONT_PID"
        return 1
    fi
}

stop_one() {
    local name="$1" pid_file="$2" pattern="$3"
    if ! is_running "$pid_file" "$pattern"; then
        echo "[$name] 未在运行"
        rm -f "$pid_file"
        return 0
    fi

    local pid=""
    [ -f "$pid_file" ] && pid="$(cat "$pid_file" 2>/dev/null || echo '')"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "[$name] 停止中 (PID $pid)..."
        kill "$pid" 2>/dev/null
        for _ in $(seq 1 10); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "[$name] 未响应，强制终止"
            kill -9 "$pid" 2>/dev/null
        fi
    else
        pkill -f "$pattern" 2>/dev/null || true
    fi
    rm -f "$pid_file"
    echo "[$name] 已停止"
}

status_one() {
    local name="$1" pid_file="$2" pattern="$3"
    if is_running "$pid_file" "$pattern"; then
        if [ -f "$pid_file" ]; then
            echo "[$name] 运行中 (PID $(cat "$pid_file"))"
        else
            echo "[$name] 运行中 (无 PID 文件，由 pgrep 检出)"
        fi
    else
        echo "[$name] 未运行"
    fi
}

start_all() {
    echo "========== QuantMind 启动 =========="
    if [ ! -x "$PY" ]; then
        echo "[错误] 未找到 $PY"
        echo "请先创建虚拟环境: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
        exit 1
    fi
    if [ ! -d "$FRONTEND_DIR" ]; then
        echo "[错误] 未找到前端目录: $FRONTEND_DIR"
        exit 1
    fi

    start_scheduler
    start_api
    start_frontend

    echo "=================================="
    echo "前端页面: http://localhost:5173"
    echo "API 文档: http://localhost:8000/docs"
    echo "健康检查: http://localhost:8000/health"
    echo "后台应用日志: $APP_LOG"
    echo "进程运行日志: $RUNTIME_LOG"
    echo "前端日志: $FRONT_LOG"
}

stop_all() {
    echo "========== QuantMind 停止 =========="
    stop_one "前端服务" "$FRONT_PID" "$FRONT_PATTERN"
    stop_one "API服务" "$API_PID" "$API_PATTERN"
    stop_one "调度器" "$SCHED_PID" "$SCHED_PATTERN"
    echo "=================================="
}

status_all() {
    echo "========== QuantMind 状态 =========="
    status_one "调度器" "$SCHED_PID" "$SCHED_PATTERN"
    status_one "API服务" "$API_PID" "$API_PATTERN"
    status_one "前端服务" "$FRONT_PID" "$FRONT_PATTERN"
    echo "=================================="
}

case "${1:-start}" in
    start|"") start_all ;;
    stop) stop_all ;;
    restart)
        stop_all
        sleep 1
        start_all
        ;;
    status) status_all ;;
    *)
        echo "用法: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
