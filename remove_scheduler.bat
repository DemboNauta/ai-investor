@echo off
schtasks /delete /tn "AIInvestor" /f 2>nul
schtasks /delete /tn "AIInvestor_moderate" /f 2>nul
schtasks /delete /tn "AIInvestor_aggressive" /f 2>nul
schtasks /delete /tn "AIInvestor_degen" /f 2>nul
echo Todas las tareas eliminadas.
pause
