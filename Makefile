.PHONY: install dev crawler web lint test clean

# 安装项目（可编辑模式）
install:
	pip install -e .

# 开发环境安装（含测试/lint 工具）
dev:
	pip install -e ".[dev]"

# 启动 DHT 爬虫
crawler:
	python -m crawler.main

# 启动 Web UI
web:
	cd src && streamlit run intelligence/web/app.py

# 代码检查
lint:
	ruff check src/ tests/

# 运行测试
test:
	pytest tests/ -v --tb=short

# 运行测试 + 覆盖率
test-cov:
	pytest tests/ -v --cov=src --cov-report=term-missing

# 清理缓存
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache *.egg-info
