# LaboraTobi

MVP local para entrenamiento de ajedrez con `FastAPI + SQLAlchemy`, `Next.js` y `PostgreSQL`.

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

## Carga Diaria De 3 Partidas Broadcast

Flujo canonico operativo:

1. Levanta el stack:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1
```

2. Haz preview de una ronda seria de Lichess Broadcast:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\load-daily-broadcast.ps1 -RoundId <round_id>
```

3. Elige exactamente 3 `external_id` del preview e importalos con generacion automatica de momentos criticos:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\load-daily-broadcast.ps1 -RoundId <round_id> -ExternalIds id1,id2,id3
```

El script reutiliza los endpoints existentes de preview, import Broadcast y generacion de critical moments. Al final imprime las partidas cargadas, sus `game_id`, cuantos momentos criticos quedaron activos y confirma que esas 3 partidas estan en la sesion de `/study`.
