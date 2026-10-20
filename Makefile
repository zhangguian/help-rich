# 买股工具室 — 统一命令入口
#
# 用法:
#   make setup      首次初始化(装依赖 + 建库)
#   make dev        同时启动后端(8000)与前端(5173)
#   make test       后端全量测试
#   make lint       静态检查(后端 ruff + 前端 tsc/lint)
#   make retention  数据裁剪 + 回收磁盘
#
# Windows 用户可直接用 scripts\dev.ps1(等价于 make dev)。

.DEFAULT_GOAL := help
SHELL := /bin/bash

BACKEND  := backend
FRONTEND := frontend
PY       := $(BACKEND)/.venv/Scripts/python.exe

# Windows 用 .exe 版,其他平台用无后缀
ifeq ($(OS),Windows_NT)
    PY := $(BACKEND)/.venv/Scripts/python.exe
else
    PY := $(BACKEND)/.venv/bin/python
endif

.PHONY: help setup setup-backend setup-frontend migrate dev dev-backend dev-frontend test test-watch lint lint-backend lint-backend-fix lint-frontend typecheck retention doctor clean

help:
	@echo "买股工具室 — 可用命令:"
	@echo "  make setup        初始化(装依赖 + 建库 + 生成 .env)"
	@echo "  make dev          同时启动后端(:8000)与前端(:5173)"
	@echo "  make test         后端全量测试"
	@echo "  make test-watch   后端测试(watch 模式)"
	@echo "  make lint         静态检查(ruff + tsc + eslint)"
	@echo "  make lint-fix     后端 ruff 自动修复 + 格式化"
	@echo "  make retention    数据裁剪 + VACUUM 回收磁盘"
	@echo "  make doctor       环境自检(依赖/迁移/健康检查)"
	@echo "  make clean        清理缓存与构建产物"

setup: setup-backend setup-frontend migrate

setup-backend:
	@if [ ! -d "$(BACKEND)/.venv" ]; then python -m venv $(BACKEND)/.venv; fi
	@cd $(BACKEND) && $(PY) -m pip install -q --upgrade pip
	@cd $(BACKEND) && $(PY) -m pip install -q pytest pytest-asyncio pytest-cov ruff
	@if [ ! -f "$(BACKEND)/.env" ] && [ -f "$(BACKEND)/.env.example" ]; then \
		cp $(BACKEND)/.env.example $(BACKEND)/.env && echo "已生成 backend/.env"; fi

setup-frontend:
	@cd $(FRONTEND) && npm install --silent

migrate:
	@cd $(BACKEND) && $(PY) -m alembic upgrade head

dev:
	@echo "后端 http://127.0.0.1:8000  |  前端 http://localhost:5173"
	@$(MAKE) dev-backend & $(MAKE) dev-frontend

dev-backend:
	@cd $(BACKEND) && $(PY) -m uvicorn app.main:app --reload --port 8000

dev-frontend:
	@cd $(FRONTEND) && npm run dev

test:
	@cd $(BACKEND) && $(PY) -m pytest -q

test-watch:
	@cd $(BACKEND) && $(PY) -m pytest -q --lf -x

lint: lint-backend lint-frontend typecheck

lint-backend:
	@cd $(BACKEND) && $(PY) -m ruff check app tests

lint-backend-fix:
	@cd $(BACKEND) && $(PY) -m ruff check --fix app tests && $(PY) -m ruff format app tests

lint-frontend:
	@cd $(FRONTEND) && npm run lint

typecheck:
	@cd $(FRONTEND) && npm run typecheck

retention:
	@cd $(BACKEND) && $(PY) -m app.services.retention --vacuum

doctor:
	@echo "--- Python ---";  $(PY) --version
	@echo "--- Alembic 迁移链 ---"; cd $(BACKEND) && $(PY) -m alembic heads; cd ..
	@echo "--- Node ---"; node --version
	@echo "--- 数据目录 ---"; ls -lh $(BACKEND)/data.db 2>/dev/null || echo "  data.db 尚未创建"

clean:
	@find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	@rm -rf $(BACKEND)/.pytest_tmp $(FRONTEND)/.next/cache 2>/dev/null || true
	@echo "已清理"
