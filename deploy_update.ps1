# Sube .py modificados, reinicia api_server y regenera dashboard
$VPS_IP   = "178.104.140.243"
$VPS_USER = "root"
$SSH_KEY  = "$env:USERPROFILE\.ssh\id_ed25519"

$ErrorActionPreference = "Stop"
$REMOTE_DIR = "/root/ai-investor"
$LOCAL_DIR  = $PSScriptRoot

$SSH_ARGS = @("-o", "StrictHostKeyChecking=no")
if ($SSH_KEY -ne "") { $SSH_ARGS += @("-i", $SSH_KEY) }
$SSH_TARGET = "${VPS_USER}@${VPS_IP}"

$FILES = @(
    "agent.py",
    "data.py",
    "memory.py",
    "run_once.py",
    "generate_report.py",
    "main.py",
    "api_server.py",
    "notifier.py",
    "subscribers.py",
    "daily_digest.py",
    "backup.sh"
)

# 1. Subir archivos
Write-Host ""
Write-Host "==> [1/4] Subiendo archivos..." -ForegroundColor Cyan
foreach ($file in $FILES) {
    $local  = Join-Path $LOCAL_DIR $file
    $remote = "${SSH_TARGET}:${REMOTE_DIR}/${file}"
    Write-Host "    $file" -ForegroundColor Gray
    scp @SSH_ARGS $local $remote
}


# 2. Verificar sintaxis
Write-Host ""
Write-Host "==> [2/4] Verificando imports..." -ForegroundColor Cyan
$pyCheck = "cd $REMOTE_DIR && source venv/bin/activate && python3 -m py_compile agent.py data.py memory.py run_once.py generate_report.py main.py api_server.py && echo OK"
$result = ssh @SSH_ARGS $SSH_TARGET $pyCheck
if ($result -match "OK") {
    Write-Host "  Imports OK" -ForegroundColor Green
} else {
    Write-Host "  ERROR en imports - abortando" -ForegroundColor Red
    Write-Host $result
    exit 1
}

# 3. Reiniciar chat server via script remoto (evita SSH colgado)
Write-Host ""
Write-Host "==> [3/4] Reiniciando chat server..." -ForegroundColor Cyan

$restartSh = @"
#!/bin/bash
mkdir -p /root/ai-investor/logs
pkill -f api_server.py 2>/dev/null
sleep 1
cd /root/ai-investor
source venv/bin/activate
nohup python3 api_server.py >> /root/ai-investor/logs/chat.log 2>&1 &
echo \$! > /tmp/chat_server.pid
sleep 2
ss -tlnp | grep 5001 && echo LISTENING || echo NOT_LISTENING
"@
$restartSh = $restartSh -replace "`r`n", "`n"
$tmpFile = "$env:TEMP\restart_chat.sh"
[System.IO.File]::WriteAllText($tmpFile, $restartSh, [System.Text.UTF8Encoding]::new($false))
scp @SSH_ARGS $tmpFile "${SSH_TARGET}:/tmp/restart_chat.sh" | Out-Null
$portCheck = ssh @SSH_ARGS $SSH_TARGET "bash /tmp/restart_chat.sh; rm /tmp/restart_chat.sh"
if ($portCheck -match "LISTENING") {
    Write-Host "  Chat server activo en puerto 5001" -ForegroundColor Green
} else {
    Write-Host "  ADVERTENCIA: chat server no responde" -ForegroundColor Yellow
    $log = ssh @SSH_ARGS $SSH_TARGET "tail -10 /root/ai-investor/logs/chat.log 2>/dev/null"
    Write-Host $log -ForegroundColor Gray
}

# 4. Regenerar dashboard
Write-Host ""
Write-Host "==> [4/4] Regenerando dashboard..." -ForegroundColor Cyan
$reportCmd = "cd $REMOTE_DIR && source venv/bin/activate && python3 generate_report.py && echo REPORT_OK"
$reportResult = ssh @SSH_ARGS $SSH_TARGET $reportCmd
if ($reportResult -match "REPORT_OK") {
    Write-Host "  Dashboard actualizado" -ForegroundColor Green
} else {
    Write-Host "  ADVERTENCIA: revisar generate_report.py" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host " Listo. Cron sigue activo sin interrupciones." -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
