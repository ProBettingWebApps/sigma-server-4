@echo off
TITLE Protocollo Sigma 4.0 - Console TV
color 0A
cd /d "%~dp0"
py -m streamlit run app_web.py
pause