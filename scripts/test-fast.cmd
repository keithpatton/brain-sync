@echo off
python -m pytest -n auto -m "unit or integration or external or mcp" --timeout=30 %*
