# pip-audit (DEPLOY05, 08/10/2026)

Se auditaron `requirements-fog.txt` y `requirements-cloud.txt` con
`pip-audit --no-deps`, resolviendo las dependencias sin versión (`ultralytics`,
`lap`, `python-multipart`) con las de `constraints.txt` y las instaladas en `.venv`.

| Archivo | Resultado |
|---|---|
| `requirements-fog.txt` | Sin vulnerabilidades conocidas. |
| `requirements-cloud.txt` (+ `torch`/`torchvision` de `constraints.txt`) | `torch 2.12.1`: PYSEC-2025-194, corregida en 2.13.0. |

## Excepción: torch 2.12.1 (Cloud)
No es crítica según el reporte (no se clasificó como tal) y no se sube la versión en este
prompt: `torch`, `torchvision` y `ultralytics` están verificados juntos (DEF-19) y el
checkpoint se validó con ellos. Subir a 2.13.x exige repetir esa verificación y la prueba de
paridad de features. Pendiente: evaluar la actualización antes de la validación con árbitros.
