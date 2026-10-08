@echo off
chcp 65001 >nul
python -m pip install -q pycparser
python main.py %*
pause
