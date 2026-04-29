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
    "config.py",
    "data.py",
    "memory.py",
    "profiles.py",
    "run_once.py",
    "generate_report.py",
    "main.py",
    "api_server.py",
    "notifier.py",
    "subscribers.py",
    "daily_digest.py",
    "bluesky_bot.py",
    "backup.sh"
)

# 1. Subir archivos
Write-Host ""
Write-Host "==> [1/5] Subiendo archivos..." -ForegroundColor Cyan
foreach ($file in $FILES) {
    $local  = Join-Path $LOCAL_DIR $file
    $remote = "${SSH_TARGET}:${REMOTE_DIR}/${file}"
    Write-Host "    $file" -ForegroundColor Gray
    scp @SSH_ARGS $local $remote
}
# Subir .env
scp @SSH_ARGS (Join-Path $LOCAL_DIR ".env") "${SSH_TARGET}:${REMOTE_DIR}/.env"
Write-Host "    .env" -ForegroundColor Gray


# Subir OG image y archivos estáticos SEO
Write-Host "    assets/img/og.png" -ForegroundColor Gray
ssh @SSH_ARGS $SSH_TARGET "mkdir -p /var/www/ai-investor/assets/img"
scp @SSH_ARGS (Join-Path $LOCAL_DIR "assets\img\og.png")      "${SSH_TARGET}:/var/www/ai-investor/assets/img/og.png"
scp @SSH_ARGS (Join-Path $LOCAL_DIR "assets\img\favicon.png") "${SSH_TARGET}:/var/www/ai-investor/assets/img/favicon.png"
Write-Host "    robots.txt / sitemap.xml / llms.txt" -ForegroundColor Gray
scp @SSH_ARGS (Join-Path $LOCAL_DIR "web\robots.txt")  "${SSH_TARGET}:/var/www/ai-investor/robots.txt"
scp @SSH_ARGS (Join-Path $LOCAL_DIR "web\sitemap.xml") "${SSH_TARGET}:/var/www/ai-investor/sitemap.xml"
scp @SSH_ARGS (Join-Path $LOCAL_DIR "web\llms.txt")    "${SSH_TARGET}:/var/www/ai-investor/llms.txt"

# 2. Instalar dependencias nuevas si hacen falta
Write-Host ""
Write-Host "==> [2/5] Verificando dependencias..." -ForegroundColor Cyan
ssh @SSH_ARGS $SSH_TARGET "cd $REMOTE_DIR && source venv/bin/activate && pip install openai atproto --quiet"

# 3. Verificar sintaxis
Write-Host ""
Write-Host "==> [3/5] Verificando imports..." -ForegroundColor Cyan
$pyCheck = "cd $REMOTE_DIR && source venv/bin/activate && python3 -m py_compile agent.py config.py profiles.py data.py memory.py run_once.py generate_report.py main.py api_server.py && echo OK"
$result = ssh @SSH_ARGS $SSH_TARGET $pyCheck
if ($result -match "OK") {
    Write-Host "  Imports OK" -ForegroundColor Green
} else {
    Write-Host "  ERROR en imports - abortando" -ForegroundColor Red
    Write-Host $result
    exit 1
}

# 4. Añadir cron jobs OpenAI si no existen (via script remoto — evita conflicto de comillas en SSH)
Write-Host ""
Write-Host "==> [4/5] Configurando cron OpenAI..." -ForegroundColor Cyan
$cronSh = @'
#!/bin/bash
if crontab -l 2>/dev/null | grep -q 'moderate_openai'; then
  echo CRON_EXISTS
  exit 0
fi
(crontab -l 2>/dev/null
 echo '15 * * * * cd /root/ai-investor && source venv/bin/activate && python3 run_once.py moderate_openai >> logs/moderate_openai.log 2>&1'
 echo '20 * * * * cd /root/ai-investor && source venv/bin/activate && python3 run_once.py aggressive_openai >> logs/aggressive_openai.log 2>&1'
 echo '25 * * * * cd /root/ai-investor && source venv/bin/activate && python3 run_once.py degen_openai >> logs/degen_openai.log 2>&1'
) | crontab -
echo CRON_ADDED
'@
$cronSh = $cronSh -replace "`r`n", "`n"
$tmpCron = "$env:TEMP\setup_cron.sh"
[System.IO.File]::WriteAllText($tmpCron, $cronSh, [System.Text.UTF8Encoding]::new($false))
scp @SSH_ARGS $tmpCron "${SSH_TARGET}:/tmp/setup_cron.sh" | Out-Null
$cronResult = ssh @SSH_ARGS $SSH_TARGET "bash /tmp/setup_cron.sh; rm /tmp/setup_cron.sh"
if ($cronResult -match "CRON_ADDED") {
    Write-Host "  Cron jobs OpenAI añadidos (min 15/20/25)" -ForegroundColor Green
} else {
    Write-Host "  Cron jobs OpenAI ya existian" -ForegroundColor Gray
}

# 5. Reiniciar chat server via script remoto (evita SSH colgado)
Write-Host ""
Write-Host "==> [5/5] Reiniciando chat server..." -ForegroundColor Cyan

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

# Regenerar dashboard
Write-Host ""
Write-Host "==> Regenerando dashboard..." -ForegroundColor Cyan
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
