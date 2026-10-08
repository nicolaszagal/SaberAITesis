# pip-audit (DEPLOY05, 08/10/2026)

`pip-audit -r requirements-fog.txt` falla por sí solo ("requirement ultralytics is not pinned"),
porque ese archivo deja sin versión `ultralytics`, `lap` y `python-multipart`. Se auditó con
`--no-deps --disable-pip` sobre copias que resuelven esas tres con `constraints.txt`
(`ultralytics==8.4.75`) y con las versiones instaladas en `.venv` (`lap==0.5.13`,
`python-multipart==0.0.32`). Cloud se auditó con `requirements-cloud.txt` más `torch` y
`torchvision` de `constraints.txt`.

| Archivo | Resultado |
|---|---|
| `requirements-fog.txt` | `No known vulnerabilities found` |
| `requirements-cloud.txt` + `torch`/`torchvision` | `Found 1 known vulnerability in 1 package`: `torch 2.12.1`, PYSEC-2025-194, versión de corrección 2.13.0 |

## Excepción: torch 2.12.1 (PYSEC-2025-194 / CVE-2025-3000 / GHSA-rrmf-rvhw-rf47)

**Qué dice el aviso** (OSV, publicado 31/03/2025, última modificación 13/07/2026):
vulnerabilidad clasificada como **crítica** en `torch.jit.script` de PyTorch **2.6.0**;
corrupción de memoria; el ataque se lanza **en el host local**; el exploit es público.
Referencia: pytorch/pytorch#149623.

**Inconsistencia del propio aviso.** OSV declara el rango afectado como `introduced: 0` y
`last_affected: "2.6.0-NA"`. Esa cota no es una versión parseable, y `pip-audit` la trata como
"afecta a todas las versiones" y reporta 2.13.0 como corrección. El aviso describe el defecto en
2.6.0 y **no** afirma que 2.12.1 lo conserve; con lo revisado no puedo determinar si 2.12.1 está
afectado ni en qué versión se corrigió realmente.

**Uso en este sistema** (revisión del código y de `.venv`):
- El código propio de Fog, Cloud y `shared` **no** llama a `torch.jit.script` ni `torch.jit.trace`.
- Cloud carga solo el checkpoint propio `best_model.pt` incluido en la imagen
  (`cloud/infrastructure/classifier/lstm6class_adapter.py`, `torch.load(...)`), no archivos
  recibidos por la red. Fog carga `yolov8x-pose.pt`, cuyo SHA-256 se verifica en el build.
- Cloud consume de Redis solo arreglos numéricos de features (no modelos ni código).
- En `ultralytics 8.4.75` las únicas menciones de `torch.jit` son el cargador de modelos
  TorchScript (`.torchscript`, que el sistema no usa) y un callback de TensorBoard de
  entrenamiento. No revisé el resto de ultralytics más allá de buscar `jit.script`/`jit.trace`.

**Conclusión:** no hay entradas externas hacia `torch.jit.script` en el código revisado. No se
actualiza torch en DEPLOY05 porque `torch`, `torchvision` y `ultralytics` están verificados juntos
(DEF-19) y subir a 2.13.x exige repetir esa verificación y la prueba de paridad de features.
Pendiente: confirmar en el aviso original si 2.12.1 está afectado y evaluar la actualización.

- Fecha de revisión: 08/10/2026. Próxima revisión: antes de la Validación 2.
- Responsable: el autor de la tesis.
