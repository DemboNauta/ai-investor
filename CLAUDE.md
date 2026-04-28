# AI Investor — Contexto del proyecto

## Qué es

Sistema de paper trading crypto con **6 agentes autónomos** divididos en 2 equipos que compiten entre sí:
- **Equipo Grok**: 3 agentes con Grok 4.1 fast reasoning (xAI API)
- **Equipo GPT**: 3 agentes con GPT-4o mini (OpenAI API)

Mismas estrategias en ambos equipos. Se compara qué modelo toma mejores decisiones.
Corre en VPS Linux 24/7. Dashboard web público en producción.

## Agentes / Perfiles

| Key | Nombre | Modelo | Estrategia | Portfolio file |
|-----|--------|--------|-----------|----------------|
| `moderate` | Moderate | Grok 4.1 | Conservador, top 10 coins, max 25% por coin | `portfolio_moderate.json` |
| `aggressive` | Aggressive | Grok 4.1 | Agresivo, top 50 coins, max 40% por coin | `portfolio_aggressive.json` |
| `degen` | Degen | Grok 4.1 | Extremo, alta concentración, FOMO válido | `portfolio_degen.json` |
| `moderate_openai` | Moderate (GPT) | GPT-4o mini | Conservador, top 10 coins, max 25% por coin | `portfolio_moderate_openai.json` |
| `aggressive_openai` | Aggressive (GPT) | GPT-4o mini | Agresivo, top 50 coins, max 40% por coin | `portfolio_aggressive_openai.json` |
| `degen_openai` | Degen (GPT) | GPT-4o mini | Extremo, alta concentración, FOMO válido | `portfolio_degen_openai.json` |

Capital inicial: **€1000** por agente.

## Infraestructura

### VPS
- **IP**: `178.104.140.243`
- **OS**: Ubuntu (Linux)
- **Usuario**: `root`
- **SSH key**: `~/.ssh/id_ed25519`
- **Directorio proyecto**: `/root/ai-investor/`
- **Directorio web**: `/var/www/ai-investor/` (sirve el HTML estático)

### Dominio
- **URL pública**: https://cryptoaiarena.com
- **Registrado en**: Cloudflare
- **DNS**: Cloudflare proxy activo (nube naranja) — SSL Flexible
- **Reverse proxy**: Caddy v2 — config en `/etc/caddy/Caddyfile`

### Caddy config (`/etc/caddy/Caddyfile`)
```
http://cryptoaiarena.com, http://www.cryptoaiarena.com {
    root * /var/www/ai-investor
    file_server
    reverse_proxy /api/* localhost:5001
}
```
> HTTP en origen, Cloudflare pone HTTPS al usuario (modo Flexible).
> No usar Let's Encrypt con Cloudflare proxy activo — conflicto con ACME http-01.

## Arquitectura de la app

```
cron (cada hora)
  ├── run_once.py moderate   → agente → portfolio_moderate.json + history_moderate.json
  ├── run_once.py aggressive → agente → portfolio_aggressive.json + history_aggressive.json
  └── run_once.py degen      → agente → portfolio_degen.json + history_degen.json
        │
        └── generate_report.py → /var/www/ai-investor/index.html

chat_server.py (puerto 5001, arranca @reboot vía cron)
  └── /api/chat/<profile> — accedido por el dashboard vía Caddy proxy
```

## Cron en VPS

```
0  * * * *  run_once.py moderate
5  * * * *  run_once.py aggressive
10 * * * *  run_once.py degen
15 * * * *  run_once.py moderate_openai
20 * * * *  run_once.py aggressive_openai
25 * * * *  run_once.py degen_openai
@reboot     api_server.py
0 18 * * *  daily_digest.py
0  3 * * *  backup.sh
```

Logs en `/root/ai-investor/logs/`.

## Archivos clave

| Archivo | Rol |
|---------|-----|
| `run_once.py` | Ejecuta un ciclo de trading para un perfil |
| `agent.py` | Lógica del agente Grok — decide compras/ventas |
| `data.py` | Fetches: CoinGecko, Fear&Greed, Binance, Yahoo, RSS noticias |
| `generate_report.py` | Genera `web/index.html` con dashboard completo |
| `api_server.py` | HTTP server puerto 5001 — API chat con agentes |
| `memory.py` | Sistema de memoria persistente por agente |
| `portfolio.py` | CRUD de portfolios JSON |
| `profiles.py` | Definición de los 3 agentes y sus system prompts |
| `main.py` | Loop continuo (alternativa al cron, no usado en prod) |
| `config.py` | Variables globales: API key, modelo, capital inicial |
| `notifier.py` | Notificaciones email vía Resend SDK |
| `subscribers.py` | Gestión de suscriptores con doble opt-in (SQLite) |
| `daily_digest.py` | Resumen diario a suscriptores — cron 18:00 UTC |
| `backup.sh` | Backup diario de datos persistentes — cron 03:00 UTC |

## Datos persistentes en VPS (NO tocar/sobrescribir)

- `portfolio_moderate.json` / `portfolio_aggressive.json` / `portfolio_degen.json`
- `portfolio_moderate_openai.json` / `portfolio_aggressive_openai.json` / `portfolio_degen_openai.json`
- `history_moderate.json` / `history_aggressive.json` / `history_degen.json`
- `history_moderate_openai.json` / `history_aggressive_openai.json` / `history_degen_openai.json`
- `memory_moderate.md` / `memory_aggressive.md` / `memory_degen.md`
- `chat_history.db` (SQLite — historial de chats)
- `subscribers.db` (SQLite — suscriptores email)
- `alert_state.json` (timestamp última alerta — cooldown 6h)
- `logs/`
- `backups/` (backups diarios, retención 7 días — NO borrar manualmente)

**Deploy nunca hace rm ni rsync --delete. Solo scp de archivos .py/.sh específicos.**

## Deploy / actualizar producción

```powershell
# Subir cambios y reiniciar chat server
.\deploy_update.ps1

# Deploy completo (primera vez o setup)
.\deploy.ps1
```

`deploy_update.ps1` sube: `agent.py`, `data.py`, `memory.py`, `run_once.py`,
`generate_report.py`, `main.py`, `api_server.py`, `notifier.py`, `subscribers.py`,
`daily_digest.py`, `backup.sh`.

## Variables de entorno (`.env`)

```
XAI_API_KEY=...          # xAI / Grok API key
GROK_MODEL=grok-4.1-fast-reasoning  # Modelo Grok usado
OPENAI_API_KEY=...       # OpenAI API key
OPENAI_MODEL=gpt-4o-mini # Modelo OpenAI usado
CYCLE_INTERVAL_HOURS=1   # Intervalo ciclos (no usado en prod con cron)
RESEND_API_KEY=...       # Resend SDK — envío de emails
FROM_EMAIL=noreply@send.cryptoaiarena.com
FROM_NAME=CryptoAiArena
NOTIFY_EMAIL=edgarxiaomi10744@gmail.com
UNSUB_SECRET=...         # Semilla HMAC para tokens de baja
BASE_URL=https://cryptoaiarena.com
CHAT_PORT=5001           # Puerto chat server (default 5001)
WEB_DIR=...              # Directorio output HTML (default: web/)
```

## Fuentes de datos del agente

- **CoinGecko** — precios, market cap, RSI, trending, datos globales
- **Alternative.me** — Fear & Greed Index
- **Binance Futures** — funding rates
- **Yahoo Finance** — DXY y S&P 500 (contexto macro)
- **Coindesk + Cointelegraph** — noticias vía RSS
- **xAI Grok 4.1 fast reasoning** — modelo de decisión equipo Grok
- **OpenAI GPT-4o mini** — modelo de decisión equipo GPT

## Acceso remoto al VPS

```powershell
# Escritorio remoto vía túnel SSH
.\setup_rdp.ps1
# Luego: mstsc /v:localhost:3389
```

## Notas importantes

- `generate_report.py:1434` — `CHAT_API` usa `window.location.hostname` sin puerto
  (correcto para producción con Caddy; en local dev cambiar a `:5001`)
- El dashboard se regenera automáticamente en cada ciclo de cron
- `chat_server.py` arranca solo al reboot — si muere, reiniciar manualmente o via `deploy_update.ps1`
- Cloudflare SSL modo **Flexible** — no cambiar a Full/Full Strict sin cert válido en origen
