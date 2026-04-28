# Scripts

Scripts canonicos para operar y desarrollar LaboraTobi en Windows PowerShell.

## Operacion productiva semanal

El flujo vigente de contenido es semanal y no depende de Swagger. Se usa `weekly-update-round.ps1` contra el backend productivo de Railway.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\weekly-update-round.ps1 -RoundUrl "<round_url>" -Limit 20
```

El limite se puede cambiar con `-Limit` o en `weekly-update-config.json`.

## Scripts vigentes

- `dev-up.ps1`: levanta `db`, `backend` y `frontend` con `docker compose` en segundo plano.
- `dev-down.ps1`: detiene el stack y remueve orfandad de contenedores.
- `dev-reset.ps1`: baja y vuelve a levantar el stack manteniendo los datos persistidos y limpiando la cache de Next del frontend.
- `preview-broadcast-round.ps1`: previsualiza una ronda Lichess Broadcast usando solo la URL de la ronda.
- `import-broadcast-round.ps1`: hace preview, importa una ronda Lichess Broadcast usando solo la URL y, por defecto, genera critical moments y resume `/study`.
- `weekly-update-round.ps1`: flujo semanal productivo en un solo comando; hace preview, import, critical moments y resumen de `/study`.
- `weekly-update-config.json`: backend productivo y limite semanal por defecto para `weekly-update-round.ps1`.

## Comandos recomendados

- `powershell -ExecutionPolicy Bypass -File .\scripts\dev-up.ps1`
- `powershell -ExecutionPolicy Bypass -File .\scripts\dev-down.ps1`
- `powershell -ExecutionPolicy Bypass -File .\scripts\dev-reset.ps1`
- `powershell -ExecutionPolicy Bypass -File .\scripts\preview-broadcast-round.ps1 -RoundUrl "<round_url>"`
- `powershell -ExecutionPolicy Bypass -File .\scripts\import-broadcast-round.ps1 -RoundUrl "<round_url>"`
- `powershell -ExecutionPolicy Bypass -File .\scripts\weekly-update-round.ps1 -RoundUrl "<round_url>" -Limit 20`

La ruta recomendada para produccion semanal es `weekly-update-round.ps1`. Swagger queda como herramienta de debug, no como flujo operativo principal.
