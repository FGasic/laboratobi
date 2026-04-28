# Scripts

Scripts locales canonicos para desarrollo en Windows PowerShell.

- `dev-up.ps1`: levanta `db`, `backend` y `frontend` con `docker compose` en segundo plano.
- `dev-down.ps1`: detiene el stack y remueve orfandad de contenedores.
- `dev-reset.ps1`: baja y vuelve a levantar el stack manteniendo los datos persistidos y limpiando la cache de Next del frontend.
- `load-daily-broadcast.ps1`: hace preview de una ronda Lichess Broadcast y, con exactamente 3 `external_id`, importa esas partidas generando critical moments y verificando que quedan en `/study`.

Comandos recomendados:

- `powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1`
- `powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1`
- `powershell -ExecutionPolicy Bypass -File .\scripts\dev-reset.ps1`
- `powershell -ExecutionPolicy Bypass -File .\scripts\load-daily-broadcast.ps1 -RoundId <round_id>`
- `powershell -ExecutionPolicy Bypass -File .\scripts\load-daily-broadcast.ps1 -RoundId <round_id> -ExternalIds id1,id2,id3`

La ruta recomendada para el dia a dia es usar estos scripts y evitar corridas manuales de `next dev` o `uvicorn` en puertos alternativos.
