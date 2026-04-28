#!/bin/bash
# Diagnostic script for ai-investor production VPS
# Run directly on VPS: bash /root/ai-investor/check_prod.sh
# Or via PowerShell wrapper: .\check_prod.ps1

DIR="/root/ai-investor"
VENV="$DIR/venv/bin/activate"

RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}✓${RESET} $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }
err()  { echo -e "  ${RED}✗${RESET} $1"; }
hdr()  { echo -e "\n${BOLD}${CYAN}══ $1 ══${RESET}"; }

ERRORS=0
WARNINGS=0

# ── 1. Cron jobs ─────────────────────────────────────────────────────────────
hdr "CRON JOBS"
CRONTAB=$(crontab -l 2>/dev/null)

declare -A CRON_CHECKS=(
  ["moderate"]="run_once.py moderate"
  ["aggressive"]="run_once.py aggressive"
  ["degen"]="run_once.py degen"
  ["moderate_openai"]="run_once.py moderate_openai"
  ["aggressive_openai"]="run_once.py aggressive_openai"
  ["degen_openai"]="run_once.py degen_openai"
  ["api_server"]="api_server.py"
  ["daily_digest"]="daily_digest.py"
  ["backup"]="backup.sh"
)

for name in moderate aggressive degen moderate_openai aggressive_openai degen_openai api_server daily_digest backup; do
  pattern="${CRON_CHECKS[$name]}"
  if echo "$CRONTAB" | grep -q "$pattern"; then
    line=$(echo "$CRONTAB" | grep "$pattern" | head -1)
    ok "$name — $(echo "$line" | awk '{print $1,$2}')"
  else
    err "$name — NO ESTÁ en crontab"
    ((ERRORS++))
  fi
done

# ── 2. Procesos activos ───────────────────────────────────────────────────────
hdr "PROCESOS"
if pgrep -f "api_server.py" > /dev/null 2>&1; then
  PID=$(pgrep -f "api_server.py" | head -1)
  ok "api_server.py corriendo (PID $PID)"
else
  err "api_server.py NO está corriendo"
  ((ERRORS++))
fi

if ss -tlnp 2>/dev/null | grep -q ":5001"; then
  ok "Puerto 5001 escuchando"
else
  err "Puerto 5001 NO escucha — chat API caída"
  ((ERRORS++))
fi

# ── 3. Archivos de portfolio ──────────────────────────────────────────────────
hdr "PORTFOLIOS"
now=$(date +%s)
AGENTS=(moderate aggressive degen moderate_openai aggressive_openai degen_openai)
for agent in "${AGENTS[@]}"; do
  f="$DIR/portfolio_${agent}.json"
  if [ ! -f "$f" ]; then
    err "$agent — portfolio_${agent}.json no existe"
    ((ERRORS++))
    continue
  fi
  last_run=$(python3 -c "import json; d=json.load(open('$f')); print(d.get('last_run',''))" 2>/dev/null)
  if [ -z "$last_run" ]; then
    warn "$agent — portfolio existe pero last_run vacío"
    ((WARNINGS++))
  else
    ts=$(date -d "$last_run" +%s 2>/dev/null || date -j -f "%Y-%m-%dT%H:%M:%S" "${last_run%+*}" +%s 2>/dev/null || echo 0)
    diff_h=$(( (now - ts) / 3600 ))
    if [ "$diff_h" -le 2 ]; then
      ok "$agent — last_run hace ${diff_h}h"
    elif [ "$diff_h" -le 6 ]; then
      warn "$agent — last_run hace ${diff_h}h (esperado ≤2h)"
      ((WARNINGS++))
    else
      err "$agent — last_run hace ${diff_h}h — puede que no esté corriendo"
      ((ERRORS++))
    fi
  fi
done

# ── 4. Archivos de historial ──────────────────────────────────────────────────
hdr "HISTORIAL"
for agent in "${AGENTS[@]}"; do
  f="$DIR/history_${agent}.json"
  if [ ! -f "$f" ]; then
    warn "$agent — history_${agent}.json no existe aún"
    ((WARNINGS++))
  else
    count=$(python3 -c "import json; print(len(json.load(open('$f'))))" 2>/dev/null || echo "?")
    ok "$agent — $count entradas"
  fi
done

# ── 5. Logs ───────────────────────────────────────────────────────────────────
hdr "LOGS (últimas ejecuciones)"
LOG_AGENTS=(moderate aggressive degen moderate_openai aggressive_openai degen_openai)
for agent in "${LOG_AGENTS[@]}"; do
  f="$DIR/logs/${agent}.log"
  if [ ! -f "$f" ]; then
    warn "$agent — log no existe todavía"
    ((WARNINGS++))
    continue
  fi
  mod=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
  diff_h=$(( (now - mod) / 3600 ))
  last_line=$(tail -1 "$f" 2>/dev/null)
  has_error=$(tail -20 "$f" 2>/dev/null | grep -i "error\|traceback\|exception" | tail -1)

  if [ "$diff_h" -le 2 ]; then
    status="${GREEN}hace ${diff_h}h${RESET}"
  elif [ "$diff_h" -le 6 ]; then
    status="${YELLOW}hace ${diff_h}h${RESET}"
    ((WARNINGS++))
  else
    status="${RED}hace ${diff_h}h${RESET}"
    ((ERRORS++))
  fi

  echo -e "  $agent — modificado $status"
  if [ -n "$has_error" ]; then
    echo -e "    ${RED}Último error: ${has_error:0:120}${RESET}"
    ((WARNINGS++))
  fi
done

# Logs adicionales
for extra in chat daily_digest backup; do
  f="$DIR/logs/${extra}.log"
  [ ! -f "$f" ] && continue
  mod=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
  diff_h=$(( (now - mod) / 3600 ))
  has_error=$(tail -20 "$f" 2>/dev/null | grep -i "error\|traceback" | tail -1)
  echo -e "  $extra.log — modificado hace ${diff_h}h"
  if [ -n "$has_error" ]; then
    echo -e "    ${YELLOW}Último error: ${has_error:0:120}${RESET}"
  fi
done

# ── 6. Variables de entorno ───────────────────────────────────────────────────
hdr "VARIABLES DE ENTORNO (.env)"
ENV_FILE="$DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
  err ".env no existe"
  ((ERRORS++))
else
  REQUIRED_VARS=(XAI_API_KEY OPENAI_API_KEY RESEND_API_KEY UNSUB_SECRET FROM_EMAIL BASE_URL)
  for var in "${REQUIRED_VARS[@]}"; do
    val=$(grep "^${var}=" "$ENV_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
    if [ -z "$val" ]; then
      err "$var — NO definido o vacío"
      ((ERRORS++))
    else
      masked="${val:0:4}****"
      ok "$var = $masked"
    fi
  done
fi

# ── 7. Entorno Python ─────────────────────────────────────────────────────────
hdr "ENTORNO PYTHON"
if [ -f "$VENV" ]; then
  ok "venv existe"
  source "$VENV" 2>/dev/null
  PKGS=(openai python-dotenv requests feedparser)
  for pkg in "${PKGS[@]}"; do
    ver=$(pip show "$pkg" 2>/dev/null | grep "^Version:" | awk '{print $2}')
    if [ -n "$ver" ]; then
      ok "$pkg == $ver"
    else
      err "$pkg — NO instalado"
      ((ERRORS++))
    fi
  done
else
  err "venv no encontrado en $DIR/venv"
  ((ERRORS++))
fi

# ── 8. Disco ──────────────────────────────────────────────────────────────────
hdr "DISCO"
disk_use=$(df -h "$DIR" 2>/dev/null | tail -1 | awk '{print $5}' | tr -d '%')
disk_info=$(df -h "$DIR" 2>/dev/null | tail -1 | awk '{print $3"/"$2" ("$5" usado)"}')
if [ -n "$disk_use" ]; then
  if [ "$disk_use" -ge 90 ]; then
    err "Disco: $disk_info"
    ((ERRORS++))
  elif [ "$disk_use" -ge 75 ]; then
    warn "Disco: $disk_info"
    ((WARNINGS++))
  else
    ok "Disco: $disk_info"
  fi
fi

# ── 9. Resumen ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}══════════════════════════════════════${RESET}"
if [ "$ERRORS" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
  echo -e "${GREEN}${BOLD}  TODO OK — producción saludable${RESET}"
elif [ "$ERRORS" -eq 0 ]; then
  echo -e "${YELLOW}${BOLD}  $WARNINGS aviso(s) — revisar arriba${RESET}"
else
  echo -e "${RED}${BOLD}  $ERRORS error(s), $WARNINGS aviso(s) — acción requerida${RESET}"
fi
echo -e "${BOLD}══════════════════════════════════════${RESET}"
echo ""
