# bingx-brk-signal-bot

Bot de **señales** (no opera solo) para los perpetuos USDT de **BingX** en **5 minutos**. Cada vez que cierra una vela de 5m recorre todos los pares con liquidez, aplica la estrategia de *ruptura del máximo/mínimo del día* y manda las señales a **Telegram**. Pensado para correr 24/7 en **Railway** desde un repositorio de **GitHub**.

> Contenido educativo. Las señales no son asesoramiento financiero y esta estrategia **no tiene resultados demostrados en cripto**: valídala antes de usar dinero real (ver "Validar antes de operar").

## Cómo decide

Réplica de `pine/BRK_Dia_Cripto_BingX_5m.pine` (misma lógica, para validarla en TradingView):

1. **Nivel:** máximo/mínimo del día UTC hasta la vela anterior (o ventana móvil con `LEVEL_MODE=rolling`). No emite señales en las primeras 36 velas del día.
2. **Ruptura:** `PERSIST_BARS` cierres seguidos más allá del nivel (por defecto 2).
3. **Filtros** (todo normalizado en ADR/ATR, por eso vale para cualquier par):
   - Sesgo: |cierre − apertura UTC| ≥ 0,15 ADR a favor de la dirección.
   - Espacio: recorrido consumido desde el extremo opuesto ≤ 1,0 ADR.
   - Día tranquilo: se excluye si el rango de ayer < 0,6 ADR.
   - Coste en R: se descarta si comisión+slippage > 0,20 R (stop = 2×ATR).
   - Sin señales a partir de las 23:00 UTC; máximo 2 por par y día.
4. **Mensaje:** dirección, nivel roto, entrada de referencia, stop (2×ATR), objetivos 2R/3R, tamaño sugerido por riesgo fijo y contexto.

## Estructura

```
main.py                 punto de entrada (--once, --test-telegram, --list-symbols)
bot/strategy.py         lógica pura de la estrategia
bot/bingx.py            cliente de los endpoints públicos de BingX (sin claves API)
bot/scanner.py          recorre todos los pares al cierre de cada vela
bot/telegram.py         envío a Telegram
bot/messages.py         formato del mensaje y tamaño sugerido
bot/config.py           variables de entorno
tests/                  tests (estrategia, parseo, escáner con BingX simulado)
pine/                   la misma estrategia en Pine Script v6 para backtest
railway.json            arranque y reinicios en Railway
.env.example            todas las variables
```

## Puesta en marcha

### 1. Telegram
1. En Telegram habla con **@BotFather** → `/newbot` → copia el **token**.
2. Abre un chat con tu bot y pulsa *Start* (o añádelo a tu grupo/canal como administrador).
3. Obtén tu **chat id**: escribe al bot y abre `https://api.telegram.org/bot<TOKEN>/getUpdates`; verás `"chat":{"id": ...}`. Para grupos el id empieza por `-`.

### 2. Probar en local
```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
python -m pytest -q                                   # tests

cp .env.example .env                                  # rellena token y chat id
export $(grep -v '^#' .env | xargs)                   # o usa tu gestor de variables
python main.py --test-telegram                        # llega un mensaje de prueba
python main.py --list-symbols                         # pares que vigilará
DRY_RUN=1 python main.py --once                       # un escaneo, sin Telegram
```

### 3. Subir a GitHub
```bash
git init && git add . && git commit -m "bot de señales BingX"
git branch -M main
git remote add origin git@github.com:<tu-usuario>/bingx-brk-signal-bot.git
git push -u origin main
```
`.env` está en `.gitignore`: **nunca subas el token**.

### 4. Desplegar en Railway
1. *New Project → Deploy from GitHub repo* → elige el repositorio.
2. En *Variables* añade como mínimo `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (el resto es opcional, ver `.env.example`).
3. Railway detecta Python por `requirements.txt` y arranca con `python -u main.py` (`railway.json`). No necesita dominio público ni puerto.
4. Mira *Deployments → Logs*: al arrancar verás `Universo: N pares` y te llegará un mensaje "Bot de señales activo". Cada 5 minutos aparece una línea `Escaneo: ...`.

## Variables más útiles

| Variable | Por defecto | Para qué |
|---|---|---|
| `SYMBOLS` | vacío | Lista fija de pares (`BTC-USDT,ETH-USDT`). Vacío = todos con liquidez |
| `MIN_QUOTE_VOLUME_USDT` | 3000000 | Volumen 24h mínimo para vigilar un par |
| `RT_COST_PCT` | 0.12 | Comisión+slippage ida y vuelta (%). Ponlo igual que tu coste real |
| `MAX_COST_R` | 0.20 | Cuanto más bajo, menos pares/momentos operables |
| `PERSIST_BARS` | 2 | Cierres seguidos para confirmar la ruptura |
| `LEVEL_MODE` | day | `day` (máx/mín del día UTC) o `rolling` (24 h móviles) |
| `ACCOUNT_USDT` / `RISK_PCT` / `MAX_LEVERAGE` | 1000 / 0.5 / 3 | Solo para el tamaño sugerido del mensaje |
| `REQ_PER_SEC` | 8 | Peticiones/segundo a BingX. Con ~300 pares un escaneo tarda ~1 min |
| `DRY_RUN` | 0 | 1 = imprime en logs en vez de enviar a Telegram |

## Validar antes de operar

1. Pasa `pine/BRK_Dia_Cripto_BingX_5m.pine` por varios pares en TradingView (misma lógica) y mira expectativa en R, estadístico t y coste en R. Descarta los pares con coste en R alto.
2. Deja el bot 2–4 semanas **solo mirando señales** (o con `DRY_RUN=1`) y anota qué habría pasado, descontando comisiones reales.
3. Si operas, hazlo con el tamaño mínimo y respeta el stop. Las señales son de referencia: el precio puede haberse movido cuando las lees.

## Primer arranque: qué comprobar

Este código se probó con tests y datos simulados, **no contra la API real de BingX ni de Telegram**. En el primer despliegue revisa los logs:

- `Universo: N pares` con N > 0. Si es 0, el endpoint de contratos o de volumen ha cambiado: pon `MIN_QUOTE_VOLUME_USDT=0` o fija `SYMBOLS`.
- Las velas usan `/openApi/swap/v3/quote/klines` con fallback automático a `/v2/`. Si ves `Usando ... (fallback)` es normal; si fallan ambas, ajusta `BINGX_KLINES_PATH`.
- Si el orden de campos de las velas fuese distinto al esperado, `tests/test_strategy.py::test_parse_klines_dict_and_list` documenta los formatos soportados.
- `Escaneo: ... errores` altos → baja `REQ_PER_SEC` (límites de BingX por IP).

## Limitaciones

- Solo avisa: no abre ni cierra operaciones. No usa claves API de BingX.
- No modela funding (cada 8 h), liquidación ni diferencias entre el gráfico de TradingView y el de BingX.
- El estado de duplicados vive en memoria: si Railway reinicia en mitad de una vela podría repetirse una señal una vez.
- La caché diaria (ADR) se recarga cada día UTC; los pares con menos de 10 días de historial se omiten.
