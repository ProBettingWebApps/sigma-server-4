@echo off
TITLE Protocollo Sigma 4.0
COLOR 0A
echo Avvio console in corso... attendere l'apertura del browser.
cd /d "%~dp0"
py -m streamlit run app_web.py
pause