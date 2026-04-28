# LaboraTobi

LaboraTobi es un MVP funcional para entrenamiento de ajedrez con partidas reales de Lichess Broadcast y momentos criticos generados por backend. El stack actual es `FastAPI + SQLAlchemy`, `Next.js` y `PostgreSQL`.

El proyecto ya tiene flujo productivo en Railway:

- Backend desplegado en Railway: `https://laboratobi-production.up.railway.app`
- Frontend desplegado en Railway como servicio separado.
- PostgreSQL productivo provisto por Railway.
- Swagger queda disponible como herramienta de debug, no como flujo operativo principal.

La operacion normal de contenido es semanal: se pega una URL completa de una ronda Lichess Broadcast y se ejecuta un unico script.

## Weekly Content Update

La actualizacion operativa de contenido es semanal, no diaria. El flujo normal no usa Swagger.

Comando canonico:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\weekly-update-round.ps1 -RoundUrl "<round_url>" -Limit 20
```

Ejemplo real:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\weekly-update-round.ps1 -RoundUrl "https://lichess.org/broadcast/german-bundesliga-202526/round-10/rbWGGERo/tEFEBiBg" -Limit 20
```

Por defecto usa:

- Backend: `https://laboratobi-production.up.railway.app`
- Limite semanal: `20`

El limite se puede cambiar en cada corrida con `-Limit`, o editando `scripts/weekly-update-config.json`:

```json
{
  "backend_url": "https://laboratobi-production.up.railway.app",
  "weekly_limit": 20
}
```

El script hace preview, resuelve el `round_id` desde la URL, importa hasta `Limit` partidas, genera critical moments cuando falten, consulta `/games/broadcast/recent` y `/games/broadcast/session`, e imprime un resumen con torneo, ronda, `round_id`, partidas encontradas/importadas y partidas visibles en `/study`.

## Desarrollo Local Canonico

La unica forma soportada de correr LaboraTobi en local es via `docker compose` y los scripts de `PowerShell` del directorio `scripts/`.

En este entorno la politica de ejecucion de PowerShell bloquea la llamada directa a `.ps1`, asi que los comandos canonicos se ejecutan con `ExecutionPolicy Bypass` solo para ese proceso.

1. Si falta el archivo de entorno, copia `.env.example` a `.env`.
2. Levanta el stack con:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1
```

3. Abre:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- Docs API: `http://localhost:8000/docs`
- PostgreSQL: `localhost:5432`

4. Para detener todo sin dejar contenedores huerfanos:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1
```

5. Para reiniciar limpio el stack de desarrollo, manteniendo la base de datos y limpiando la cache de Next del frontend:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-reset.ps1
```

6. Para ver logs en vivo del frontend y backend:

```powershell
docker compose logs -f frontend backend
```

## Puertos Canonicos

- Frontend unico: `3000`
- Backend unico: `8000`
- PostgreSQL local: `5432`

No se soporta correr `next dev` en puertos alternativos ni levantar instancias paralelas del visor fuera de este flujo.

## Notas De Orden Local

- Los logs de corridas manuales antiguas quedaron archivados en `logs/legacy-local-runs/`.
- Los scripts canonicos no borran datos de PostgreSQL ni tocan el pipeline de importacion o analisis.
- `dev-reset.ps1` limpia la cache `.next` del frontend para evitar residuos entre corridas de desarrollo.
- Si necesitas resetear tambien la base, hazlo explicitamente con `docker compose down -v`, fuera del flujo canonico.
