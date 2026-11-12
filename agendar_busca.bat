@echo off
chcp 65001 >nul
REM Agenda a busca de vagas para rodar todo dia às 08:00 (Agendador de Tarefas do Windows).
REM Rode este arquivo de novo se mudar a pasta do projeto de lugar.
REM Para remover:  schtasks /Delete /TN "Busca Estagios TI" /F

set PASTA=%~dp0
for /f "delims=" %%p in ('where python') do (set PY=%%p& goto :achou)
echo Python nao encontrado no PATH. & pause & exit /b 1
:achou

REM O Indeed fica de fora da busca automatica: ele abre uma janela do navegador.
> "%PASTA%rodar_busca.bat" (
  echo @echo off
  echo cd /d "%PASTA%"
  echo "%PY%" buscar.py --fontes gupy solides linkedin vagas.com infojobs jobzi ^>^> dados\log_busca.txt 2^>^&1
)

schtasks /Create /TN "Busca Estagios TI" /TR "\"%PASTA%rodar_busca.bat\"" /SC DAILY /ST 08:00 /F
echo.
echo Pronto! A busca vai rodar todo dia as 08:00 (se o PC estiver ligado).
echo O resultado de cada execucao fica em dados\log_busca.txt
pause
