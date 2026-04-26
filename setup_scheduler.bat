@echo off
echo Registrando AI Investor (3 perfiles) en Windows Task Scheduler...

set PYTHON=C:\Users\edgar\AppData\Local\Programs\Python\Python310\python.exe
set SCRIPT=F:\Documentos\Proyectos\ai-investor\run_once.py
set WORKDIR=F:\Documentos\Proyectos\ai-investor

schtasks /create /tn "AIInvestor_moderate"   /tr "\"%PYTHON%\" \"%SCRIPT%\" moderate"   /sc HOURLY /mo 1 /st 00:00 /rl HIGHEST /ru "%USERNAME%" /f
schtasks /create /tn "AIInvestor_aggressive" /tr "\"%PYTHON%\" \"%SCRIPT%\" aggressive" /sc HOURLY /mo 1 /st 00:05 /rl HIGHEST /ru "%USERNAME%" /f
schtasks /create /tn "AIInvestor_degen"      /tr "\"%PYTHON%\" \"%SCRIPT%\" degen"      /sc HOURLY /mo 1 /st 00:10 /rl HIGHEST /ru "%USERNAME%" /f

if %ERRORLEVEL% == 0 (
    echo.
    echo Tareas registradas. Ejecutando primer ciclo de cada perfil...
    cd /d "%WORKDIR%"
    "%PYTHON%" "%SCRIPT%" moderate
    "%PYTHON%" "%SCRIPT%" aggressive
    "%PYTHON%" "%SCRIPT%" degen
    echo.
    echo Listo. Los 3 perfiles corren cada hora con 5min de separacion.
) else (
    echo Error. Ejecuta como Administrador.
)

pause
