# Cómo añadir un nuevo proveedor de LLM

Guía paso a paso para añadir un tercer proveedor (ej. Gemini, DeepSeek, Mistral).
El patrón está establecido con Grok (xai) y OpenAI como referencia.

---

## Requisitos previos

- El proveedor debe exponer una API compatible con el formato OpenAI Chat Completions
  (`/v1/chat/completions` con `tool_calls`).
- Si no es compatible, hay que adaptar `agent.py` — ver Nota al final.

---

## Paso 1 — Añadir credenciales al `.env`

```env
GEMINI_API_KEY=tu-api-key
GEMINI_MODEL=gemini-2.5-pro        # o el nombre del modelo que quieras usar
```

---

## Paso 2 — Añadir variables a `config.py`

```python
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"  # ejemplo Gemini
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
```

---

## Paso 3 — Registrar el proveedor en `run_once.py`

En la función `_make_client(provider: str)`:

```python
def _make_client(provider: str):
    if provider == "openai":
        return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL), OPENAI_MODEL
    if provider == "gemini":                                          # ← añadir esto
        return OpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL), GEMINI_MODEL
    return OpenAI(api_key=XAI_API_KEY, base_url=XAI_BASE_URL), MODEL  # xai default
```

También actualizar el import de config al inicio del archivo:

```python
from config import (INITIAL_CAPITAL_EUR,
                    XAI_API_KEY, XAI_BASE_URL, MODEL,
                    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL,
                    GEMINI_API_KEY, GEMINI_BASE_URL, GEMINI_MODEL)   # ← añadir
```

---

## Paso 4 — Añadir los 3 perfiles en `profiles.py`

Copiar el bloque de cualquier proveedor existente y cambiar:
- `provider`: nombre del proveedor (debe coincidir con `_make_client`)
- `portfolio_file`: nombre único para los JSON
- `name`: nombre visible en el dashboard

```python
"moderate_gemini": {
    "name": "Moderate (Gemini)",
    "provider": "gemini",
    "portfolio_file": "portfolio_moderate_gemini.json",
    "system_prompt": """...""",   # mismo prompt que moderate
},

"aggressive_gemini": {
    "name": "Aggressive (Gemini)",
    "provider": "gemini",
    "portfolio_file": "portfolio_aggressive_gemini.json",
    "system_prompt": """...""",
},

"degen_gemini": {
    "name": "Degen (Gemini)",
    "provider": "gemini",
    "portfolio_file": "portfolio_degen_gemini.json",
    "system_prompt": """...""",
},
```

---

## Paso 5 — Actualizar `generate_report.py`

### 5a. Añadir a los dicts del proveedor

```python
ACCENT["moderate_gemini"]    = "#00d4ff"   # o el color que quieras
ACCENT["aggressive_gemini"]  = "#ffb800"
ACCENT["degen_gemini"]       = "#ff3366"

RISK_LABEL["moderate_gemini"]   = "BAJO RIESGO"
RISK_LABEL["aggressive_gemini"] = "ALTO RIESGO"
RISK_LABEL["degen_gemini"]      = "EXTREMO"

CRON_MINUTE["moderate_gemini"]   = 30   # minuto de cron (ej. 30/35/40)
CRON_MINUTE["aggressive_gemini"] = 35
CRON_MINUTE["degen_gemini"]      = 40

PROVIDER_LABEL["gemini"] = "Gemini 2.5 Pro"
PROVIDER_COLOR["gemini"] = "#4285F4"   # azul Google
```

### 5b. Añadir top border CSS para las nuevas cards

Buscar el bloque `/* ── OpenAI card top borders ── */` y añadir:

```css
.card-moderate_gemini::before  { background: linear-gradient(90deg, transparent 5%, #00d4ff 50%, transparent 95%); opacity: 0.35; }
.card-aggressive_gemini::before { background: linear-gradient(90deg, transparent 5%, #ffb800 50%, transparent 95%); opacity: 0.35; }
.card-degen_gemini::before      { background: linear-gradient(90deg, transparent 5%, #ff3366 50%, transparent 95%); opacity: 0.35; }
```

### 5c. Añadir al scoreboard y al battle grid

En `STRATEGY_PAIRS` al principio del archivo, **no añadir** — ese array solo define Grok vs GPT.

Para un tercer proveedor el layout cambia. Opciones:
- **Opción A (simple)**: añadir una tercera columna al `battle-grid` y extender `STRATEGY_PAIRS` a triplets.
- **Opción B (tabs)**: añadir botones de filtro por proveedor sobre el grid (JS toggle).

La opción B escala mejor con N proveedores.

### 5d. Actualizar el chart

En `_chart_script`, el array `ordered_keys` decide el orden en la leyenda:

```python
ordered_keys = [
    "moderate", "aggressive", "degen",
    "moderate_openai", "aggressive_openai", "degen_openai",
    "moderate_gemini", "aggressive_gemini", "degen_gemini",   # ← añadir
]
```

Y en `is_openai` (mal nombre para cuando hay más proveedores) — renombrar a `dashed_providers`:

```python
dashed_providers = {
    "moderate_openai", "aggressive_openai", "degen_openai",
    "moderate_gemini", "aggressive_gemini", "degen_gemini",   # ← añadir
}
```

---

## Paso 6 — Actualizar `daily_digest.py`

Añadir a los dicts locales:

```python
ACCENT["moderate_gemini"] = "#00d4ff"
# ...etc

PROVIDER_LABEL["gemini"] = "Gemini 2.5 Pro"
STRATEGY_PAIRS.append(("moderate_gemini", ...))  # o reestructurar si hay >2 proveedores
```

El `build_and_send` usa `STRATEGY_PAIRS` para la tabla comparativa — con 3 proveedores hay que adaptar esa tabla a 5 columnas o cambiar el formato.

---

## Paso 7 — Añadir cron jobs en el VPS

SSH al VPS y editar crontab:

```bash
crontab -e
```

Añadir las 3 entradas (minutos 30/35/40 en el ejemplo):

```cron
30 * * * * cd /root/ai-investor && source venv/bin/activate && python3 run_once.py moderate_gemini >> logs/moderate_gemini.log 2>&1
35 * * * * cd /root/ai-investor && source venv/bin/activate && python3 run_once.py aggressive_gemini >> logs/aggressive_gemini.log 2>&1
40 * * * * cd /root/ai-investor && source venv/bin/activate && python3 run_once.py degen_gemini >> logs/degen_gemini.log 2>&1
```

> Los minutos no deben coincidir con ningún cron existente (0/5/10 = Grok, 15/20/25 = GPT).
> Dejar al menos 3 minutos de separación entre perfiles del mismo proveedor.

---

## Paso 8 — Deploy

```powershell
.\deploy_update.ps1
```

El script sube automáticamente `config.py`, `profiles.py`, `agent.py`, `run_once.py`,
`generate_report.py`, `daily_digest.py` y `.env`.

Los portfolios del nuevo proveedor se crean solos en el primer ciclo (`portfolio.load()` 
inicializa si el archivo no existe). **Los JSON existentes de otros proveedores no se tocan.**

---

## Nota: APIs no compatibles con OpenAI SDK

Si el proveedor no soporta el formato OpenAI Chat Completions con `tool_calls`
(ej. APIs propietarias con otro esquema), hay que:

1. Crear un cliente adaptador que implemente `.chat.completions.create()` con la misma interfaz.
2. O añadir un bloque `if provider == "X"` en `agent.py` dentro del loop de `run_cycle`.

Todos los proveedores actuales (xAI Grok, OpenAI, Gemini via OpenAI-compat endpoint,
DeepSeek, Mistral) soportan el SDK de OpenAI — no se necesita adaptar `agent.py`.

---

## Resumen rápido — checklist

- [ ] `.env` — API key + model name
- [ ] `config.py` — variables de entorno
- [ ] `run_once.py` — `_make_client()` + imports
- [ ] `profiles.py` — 3 perfiles nuevos con `provider` correcto
- [ ] `generate_report.py` — dicts, CSS borders, chart keys
- [ ] `daily_digest.py` — dicts + adaptar comparativa si >2 proveedores
- [ ] VPS crontab — 3 entradas nuevas (minutos únicos)
- [ ] `deploy_update.ps1` — ejecutar
