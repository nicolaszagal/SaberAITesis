# Diagnóstico de discrepancia: tablas generadas

Generado por `scripts/diagnostico_discrepancia.py`. Interpretación en `diagnostico_discrepancia.md`.

Clips: 104. Checkpoint `20260928_141021/best_model.pt`. Espacio de comparación: features normalizadas (estandarizadas y recortadas), como en `sensibilidad_features.md`.

## 0. Accuracy / F1 macro de sistema según brazo armado de Fog

| Camino | Acc | F1 macro | Coincide con CSV |
|---|---|---|---|
| CSV guardado | 0.5577 | 0.5249 | 104/104 |
| .npy reproducido | 0.5577 | 0.5249 | 104/104 |
| Fog derecha/derecha | 0.5577 | 0.5307 | 92/104 |
| Fog brazo anotado (pk=5) | 0.5673 | 0.5380 | 97/104 |

Clips con al menos un brazo anotado 'left': 41/104.

## 1. Distribución de |Δ| normalizada — Fog derecha/derecha (igual que `sensibilidad_features.md`)

Clips con el mismo T: 104/104. Cada celda: media / mediana / p95 / máx **entre clips** del valor por clip.

| Métrica por clip | media / mediana / p95 / máx |
|---|---|
| media de |Δ| | 0.1011 / 0.05574 / 0.3015 / 0.9796 |
| p95 de |Δ| | 0.4707 / 0.1663 / 2.129 / 6.072 |
| máx de |Δ| | 4.963 / 4.774 / 8.487 / 12.51 |
| fracción de valores con |Δ| > 0.0001 | 0.8664 / 0.8696 / 0.9203 / 0.9394 |

Por grupo de columnas (media de |Δ| dentro del grupo, por clip):

| Grupo | Tirador A | Tirador B |
|---|---|---|
| posición (0-50) | 0.08295 / 0.0294 / 0.333 / 2.593 | 0.1015 / 0.03107 / 0.1195 / 2.509 |
| velocidad (51-84) | 0.09233 / 0.06483 / 0.2792 / 0.5708 | 0.108 / 0.06478 / 0.3274 / 0.7454 |
| paso (85-88) | 0.08394 / 0.02724 / 0.2932 / 2.325 | 0.09822 / 0.02614 / 0.3221 / 1.838 |
| arma (89-90) | 0.3298 / 0.1492 / 0.9186 / 1.676 | 0.1236 / 0.04308 / 0.2889 / 2.234 |
| bio (91-95) | 0.2081 / 0.09188 / 0.5929 / 1.197 | 0.1049 / 0.05343 / 0.4138 / 1.504 |

Por posición del frame (primeros 5 vs el resto):

| Tramo | media de |Δ| | p95 de |Δ| |
|---|---|---|
| primeros 5 | 0.05228 / 0.03703 / 0.1096 / 0.7028 | 0.1915 / 0.1071 / 0.4323 / 4.569 |
| resto | 0.1127 / 0.05822 / 0.3391 / 1.187 | 0.5217 / 0.1697 / 2.267 / 6.178 |

Desplazamiento temporal que minimiza |Δ| (k=0 es alineación frame a frame): k=0: 104

## 1. Distribución de |Δ| normalizada — Fog con brazo armado anotado (pk=5)

Clips con el mismo T: 104/104. Cada celda: media / mediana / p95 / máx **entre clips** del valor por clip.

| Métrica por clip | media / mediana / p95 / máx |
|---|---|
| media de |Δ| | 0.09674 / 0.05243 / 0.2982 / 1.003 |
| p95 de |Δ| | 0.4544 / 0.1579 / 2.124 / 6.072 |
| máx de |Δ| | 4.873 / 4.719 / 8.487 / 12.51 |
| fracción de valores con |Δ| > 0.0001 | 0.8663 / 0.8699 / 0.9203 / 0.9394 |

Por grupo de columnas (media de |Δ| dentro del grupo, por clip):

| Grupo | Tirador A | Tirador B |
|---|---|---|
| posición (0-50) | 0.08295 / 0.0294 / 0.333 / 2.593 | 0.1015 / 0.03107 / 0.1195 / 2.509 |
| velocidad (51-84) | 0.09233 / 0.06483 / 0.2792 / 0.5708 | 0.108 / 0.06478 / 0.3274 / 0.7454 |
| paso (85-88) | 0.08394 / 0.02724 / 0.2932 / 2.325 | 0.09822 / 0.02614 / 0.3221 / 1.838 |
| arma (89-90) | 0.1382 / 0.03983 / 0.5595 / 2.798 | 0.1236 / 0.04308 / 0.2889 / 2.234 |
| bio (91-95) | 0.1159 / 0.0509 / 0.3362 / 1.431 | 0.1049 / 0.05343 / 0.4138 / 1.504 |

Por posición del frame (primeros 5 vs el resto):

| Tramo | media de |Δ| | p95 de |Δ| |
|---|---|---|
| primeros 5 | 0.047 / 0.03457 / 0.1021 / 0.7028 | 0.174 / 0.1004 / 0.2977 / 4.569 |
| resto | 0.1085 / 0.05352 / 0.3273 / 1.218 | 0.5055 / 0.1594 / 2.249 / 6.178 |

Desplazamiento temporal que minimiza |Δ| (k=0 es alineación frame a frame): k=0: 104

## 2. Rango de frames

| Comparación | Clips con T(.npy) igual |
|---|---|
| frames del clip `test_trimmed` (CAP_PROP_FRAME_COUNT) | 104/104 |
| frames del clip `test_trimmed` realmente decodificados | 104/104 |
| rango original pk=2: round(ff·fps/24) − round(fi·fps/24) + 1 | 104/104 |
| pk=5 `frame_fin_trimmed` + 1 | 104/104 |
| camino "original" con datos de pk=5 (fi=0, ff=round(frame_fin_trimmed·fps/24)) | 0/104 |

Alineación píxel a píxel del clip `test_trimmed` contra el original en [fi_real, ff_real]: k=0: 92 clips. Diferencia media de píxeles (0-255, gris 1/4 res.) en k=0: 0.29 / 0.1904 / 0.8582 / 2.994 (media / mediana / p95 / máx).

| stem | T .npy | frames trimmed | T pk=2 | T pk=5+1 | fps orig | k alineación | lock_frame Fog |
|---|---|---|---|---|---|---|---|
| AttackA_0007 | 15 | 15 | 15 | 15 | 30.00 | 0 | 0 |
| AttackA_0009 | 28 | 28 | 28 | 28 | 30.00 | 0 | 0 |
| AttackA_0023 | 17 | 17 | 17 | 17 | 30.00 | 0 | 0 |
| AttackA_0024 | 30 | 30 | 30 | 30 | 30.00 | 0 | 0 |
| AttackA_0027 | 28 | 28 | 28 | 28 | 30.00 | 0 | 0 |
| AttackA_0029 | 34 | 34 | 34 | 34 | 30.00 | 0 | 0 |
| AttackA_0036 | 18 | 18 | 18 | 18 | 30.00 | 0 | 0 |
| AttackA_0051 | 25 | 25 | 25 | 25 | 30.00 | 0 | 0 |
| AttackA_0056 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| AttackA_0057 | 11 | 11 | 11 | 11 | 30.00 | n/d | 0 |
| AttackA_0063 | 20 | 20 | 20 | 20 | 30.00 | 0 | 0 |
| AttackA_0071 | 19 | 19 | 19 | 19 | 30.00 | 0 | 0 |
| AttackA_0108 | 21 | 21 | 21 | 21 | 30.00 | 0 | 0 |
| AttackA_0109 | 25 | 25 | 25 | 25 | 30.00 | 0 | 0 |
| AttackA_0115 | 21 | 21 | 21 | 21 | 30.00 | 0 | 0 |
| AttackA_0130 | 19 | 19 | 19 | 19 | 30.00 | 0 | 0 |
| AttackA_0140 | 15 | 15 | 15 | 15 | 30.00 | 0 | 0 |
| AttackA_0144 | 21 | 21 | 21 | 21 | 30.00 | 0 | 0 |
| AttackA_0152 | 19 | 19 | 19 | 19 | 30.00 | 0 | 0 |
| AttackA_0155 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| AttackA_0164 | 37 | 37 | 37 | 37 | 30.00 | 0 | 0 |
| AttackA_0167 | 21 | 21 | 21 | 21 | 30.00 | 0 | 0 |
| AttackA_0174 | 51 | 51 | 51 | 51 | 60.00 | n/d | 0 |
| AttackA_0189 | 18 | 18 | 18 | 18 | 30.00 | 0 | 0 |
| AttackA_0190 | 29 | 29 | 29 | 29 | 30.00 | 0 | 0 |
| AttackA_0193 | 18 | 18 | 18 | 18 | 30.00 | 0 | 0 |
| AttackA_0198 | 20 | 20 | 20 | 20 | 30.00 | 0 | 0 |
| AttackB_0006 | 18 | 18 | 18 | 18 | 30.00 | 0 | 0 |
| AttackB_0016 | 30 | 30 | 30 | 30 | 30.00 | n/d | 0 |
| AttackB_0017 | 26 | 26 | 26 | 26 | 30.00 | 0 | 0 |
| AttackB_0019 | 17 | 17 | 17 | 17 | 30.00 | 0 | 0 |
| AttackB_0052 | 31 | 31 | 31 | 31 | 30.00 | 0 | 0 |
| AttackB_0055 | 29 | 29 | 29 | 29 | 30.00 | 0 | 0 |
| AttackB_0057 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| AttackB_0058 | 22 | 22 | 22 | 22 | 30.00 | 0 | 0 |
| AttackB_0059 | 22 | 22 | 22 | 22 | 30.00 | 0 | 0 |
| AttackB_0064 | 17 | 17 | 17 | 17 | 30.00 | 0 | 0 |
| AttackB_0080 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| AttackB_0087 | 17 | 17 | 17 | 17 | 30.00 | 0 | 0 |
| AttackB_0096 | 58 | 58 | 58 | 58 | 60.00 | 0 | 0 |
| AttackB_0103 | 22 | 22 | 22 | 22 | 30.00 | 0 | 0 |
| AttackB_0113 | 26 | 26 | 26 | 26 | 30.00 | 0 | 0 |
| AttackB_0139 | 31 | 31 | 31 | 31 | 30.00 | 0 | 0 |
| AttackB_0142 | 24 | 24 | 24 | 24 | 30.00 | 0 | 0 |
| AttackB_0162 | 39 | 39 | 39 | 39 | 60.00 | n/d | 0 |
| AttackB_0167 | 35 | 35 | 35 | 35 | 30.00 | 0 | 0 |
| AttackB_0172 | 21 | 21 | 21 | 21 | 30.00 | 0 | 0 |
| AttackB_0177 | 24 | 24 | 24 | 24 | 30.00 | 0 | 0 |
| AttackB_0183 | 36 | 36 | 36 | 36 | 60.00 | 0 | 0 |
| AttackB_0186 | 26 | 26 | 26 | 26 | 30.00 | n/d | 0 |
| AttackB_0187 | 22 | 22 | 22 | 22 | 30.00 | 0 | 0 |
| AttackB_0188 | 29 | 29 | 29 | 29 | 30.00 | n/d | 0 |
| AttackB_0194 | 24 | 24 | 24 | 24 | 30.00 | 0 | 0 |
| ContrattackA_0002 | 27 | 27 | 27 | 27 | 30.00 | n/d | 0 |
| ContrattackA_0005 | 32 | 32 | 32 | 32 | 30.00 | 0 | 0 |
| ContrattackA_0010 | 35 | 35 | 35 | 35 | 30.00 | 0 | 0 |
| ContrattackA_0015 | 28 | 28 | 28 | 28 | 30.00 | 0 | 0 |
| ContrattackA_0019 | 24 | 24 | 24 | 24 | 30.00 | n/d | 0 |
| ContrattackA_0020 | 20 | 20 | 20 | 20 | 30.00 | 0 | 0 |
| ContrattackA_0048 | 31 | 31 | 31 | 31 | 30.00 | 0 | 0 |
| ContrattackA_0055 | 61 | 61 | 61 | 61 | 30.00 | 0 | 0 |
| ContrattackA_0056 | 41 | 41 | 41 | 41 | 30.00 | 0 | 0 |
| ContrattackA_0070 | 29 | 29 | 29 | 29 | 30.00 | 0 | 0 |
| ContrattackA_0071 | 54 | 54 | 54 | 54 | 30.00 | 0 | 0 |
| ContrattackA_0072 | 16 | 16 | 16 | 16 | 30.00 | 0 | 0 |
| ContrattackA_0075 | 40 | 40 | 40 | 40 | 30.00 | 0 | 0 |
| ContrattackA_0085 | 34 | 34 | 34 | 34 | 30.00 | 0 | 0 |
| ContrattackB_0001 | 28 | 28 | 28 | 28 | 30.00 | 0 | 0 |
| ContrattackB_0006 | 22 | 22 | 22 | 22 | 30.00 | 0 | 0 |
| ContrattackB_0015 | 37 | 37 | 37 | 37 | 30.00 | 0 | 0 |
| ContrattackB_0025 | 22 | 22 | 22 | 22 | 30.00 | 0 | 0 |
| ContrattackB_0033 | 27 | 27 | 27 | 27 | 30.00 | n/d | 0 |
| ContrattackB_0041 | 39 | 39 | 39 | 39 | 30.00 | 0 | 0 |
| ContrattackB_0045 | 30 | 30 | 30 | 30 | 30.00 | 0 | 0 |
| ContrattackB_0050 | 30 | 30 | 30 | 30 | 30.00 | 0 | 0 |
| ContrattackB_0056 | 30 | 30 | 30 | 30 | 30.00 | 0 | 0 |
| ContrattackB_0066 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| ContrattackB_0069 | 42 | 42 | 42 | 42 | 30.00 | 0 | 0 |
| ContrattackB_0074 | 28 | 28 | 28 | 28 | 30.00 | 0 | 0 |
| ContrattackB_0078 | 33 | 33 | 33 | 33 | 60.00 | 0 | 0 |
| ContrattackB_0091 | 32 | 32 | 32 | 32 | 30.00 | 0 | 0 |
| ContrattackB_0094 | 22 | 22 | 22 | 22 | 30.00 | 0 | 0 |
| ContrattackB_0107 | 35 | 35 | 35 | 35 | 30.00 | 0 | 0 |
| RiposteA_0021 | 27 | 27 | 27 | 27 | 30.00 | 0 | 0 |
| RiposteA_0034 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| RiposteA_0041 | 28 | 28 | 28 | 28 | 30.00 | 0 | 0 |
| RiposteA_0055 | 29 | 29 | 29 | 29 | 30.00 | 0 | 0 |
| RiposteA_0057 | 27 | 27 | 27 | 27 | 30.00 | 0 | 0 |
| RiposteA_0058 | 21 | 21 | 21 | 21 | 30.00 | 0 | 0 |
| RiposteA_0060 | 26 | 26 | 26 | 26 | 30.00 | n/d | 0 |
| RiposteA_0061 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| RiposteA_0068 | 35 | 35 | 35 | 35 | 30.00 | 0 | 0 |
| RiposteA_0070 | 17 | 17 | 17 | 17 | 30.00 | 0 | 0 |
| RiposteA_0072 | 25 | 25 | 25 | 25 | 30.00 | n/d | 0 |
| RiposteB_0004 | 27 | 27 | 27 | 27 | 30.00 | 0 | 0 |
| RiposteB_0007 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| RiposteB_0011 | 25 | 25 | 25 | 25 | 30.00 | 0 | 0 |
| RiposteB_0057 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| RiposteB_0062 | 43 | 43 | 43 | 43 | 60.00 | 0 | 0 |
| RiposteB_0071 | 17 | 17 | 17 | 17 | 30.00 | n/d | 0 |
| RiposteB_0075 | 26 | 26 | 26 | 26 | 30.00 | 0 | 0 |
| RiposteB_0078 | 23 | 23 | 23 | 23 | 30.00 | 0 | 0 |
| RiposteB_0082 | 26 | 26 | 26 | 26 | 30.00 | 0 | 0 |
| RiposteB_0083 | 32 | 32 | 32 | 32 | 30.00 | 0 | 0 |

## 3. Intercambio A/B (Fog con brazo anotado)

- `fog_right`: clips con A/B intercambiados (distancia con bloques cruzados < distancia con bloques directos): 0/104
- `fog_ann`: clips con A/B intercambiados (distancia con bloques cruzados < distancia con bloques directos): 0/104

| stem | grupo | d directa | d cruzada | frames con cruce más cercano | corr A-A | corr A-B | intercambiado | pred CSV | pred Fog | lado cambia |
|---|---|---|---|---|---|---|---|---|---|---|
| AttackA_0029 | cambia | 0.088 | 0.968 | 0/34 | 0.923 | 0.393 | no | ContrattackA | AttackA | no |
| AttackA_0198 | cambia | 0.157 | 1.495 | 0/20 | 0.929 | 0.219 | no | AttackA | RiposteB | sí |
| AttackB_0167 | cambia | 0.179 | 1.558 | 0/35 | 0.896 | 0.295 | no | AttackB | AttackA | sí |
| AttackB_0183 | cambia | 0.207 | 1.294 | 0/36 | 0.901 | 0.362 | no | RiposteB | AttackA | sí |
| ContrattackA_0048 | cambia | 0.069 | 1.506 | 0/31 | 0.984 | 0.019 | no | ContrattackA | RiposteA | no |
| ContrattackB_0015 | cambia | 0.148 | 1.104 | 0/37 | 0.852 | 0.248 | no | AttackB | ContrattackB | no |
| ContrattackB_0025 | cambia | 0.057 | 1.781 | 0/22 | 0.983 | -0.188 | no | RiposteB | ContrattackB | no |
| ContrattackB_0041 | cambia | 0.604 | 1.426 | 0/39 | 0.895 | 0.157 | no | ContrattackB | RiposteB | no |
| ContrattackB_0045 | cambia | 0.061 | 1.671 | 0/30 | 0.975 | -0.061 | no | RiposteB | ContrattackB | no |
| RiposteA_0021 | cambia | 0.163 | 1.857 | 0/27 | 0.991 | 0.042 | no | ContrattackA | AttackA | no |
| RiposteA_0041 | cambia | 1.956 | 2.785 | 0/28 | 0.882 | 0.161 | no | AttackB | ContrattackA | sí |
| RiposteA_0060 | cambia | 0.159 | 2.187 | 0/26 | 0.910 | 0.037 | no | ContrattackA | AttackA | no |
| AttackA_0007 | no cambia | 0.069 | 1.768 | 0/15 | 0.998 | -0.032 | no | AttackB | AttackB | no |
| AttackA_0189 | no cambia | 0.080 | 1.152 | 0/18 | 0.940 | 0.347 | no | ContrattackB | ContrattackB | no |
| AttackB_0186 | no cambia | 0.218 | 3.536 | 0/26 | 0.966 | -0.043 | no | AttackB | AttackB | no |
| ContrattackB_0069 | no cambia | 1.719 | 2.677 | 0/42 | -0.017 | -0.071 | no | AttackB | AttackB | no |
| RiposteB_0083 | no cambia | 0.137 | 1.384 | 0/32 | 0.941 | 0.192 | no | RiposteB | RiposteB | no |

## 4. Camino de entrenamiento (`process_clip`, instancia YOLO nueva por clip) vs .npy

`trim`: sobre el clip de `test_trimmed` (is_trimmed=True). `orig`: sobre el clip original desde el frame 0, recorte a [fi, ff] de pk=2 (is_trimmed=False). Brazo armado anotado. |Δ| en espacio normalizado.

| stem | grupo | T .npy | trim: T | trim: mean|Δ| vs .npy | trim: max|Δ| vs .npy | trim vs Fog(ann): max|Δ| | orig: T | orig: lock | orig: mean|Δ| vs .npy | orig: max|Δ| vs .npy | pred CSV | pred trim | pred orig |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AttackA_0029 | cambia | 34 | 34 | 0.032 | 3.871 | 0 | 34 | 0 | 0.9597 | 7.473 | ContrattackA | ContrattackA | ContrattackA |
| AttackA_0198 | cambia | 20 | 20 | 0.06873 | 3.834 | 0 | 20 | 0 | 0.2333 | 8.271 | AttackA | AttackA | RiposteB |
| AttackB_0167 | cambia | 35 | 35 | 0.06419 | 5.943 | 0 | 35 | 0 | 0.1169 | 6.481 | AttackB | AttackB | AttackA |
| AttackB_0183 | cambia | 36 | 36 | 0.08599 | 5.881 | 0 | 36 | 0 | 1.951 | 7.479 | RiposteB | AttackA | ContrattackB |
| ContrattackA_0048 | cambia | 31 | 31 | 0.03461 | 3.717 | 0 | 31 | 0 | 1.042 | 14.71 | ContrattackA | RiposteA | ContrattackA |
| ContrattackB_0015 | cambia | 37 | 37 | 0.061 | 4.21 | 0 | 37 | 0 | 0.9475 | 7.453 | AttackB | AttackB | AttackB |
| ContrattackB_0025 | cambia | 22 | 22 | 0.02826 | 3.505 | 0 | 22 | 0 | 1.005 | 7.477 | RiposteB | ContrattackB | ContrattackA |
| ContrattackB_0041 | cambia | 39 | 39 | 0.2884 | 8.927 | 0 | 39 | 0 | 1.822 | 8.259 | ContrattackB | ContrattackB | ContrattackB |
| ContrattackB_0045 | cambia | 30 | 30 | 0.0307 | 3.361 | 0 | 30 | 0 | 1.013 | 7.473 | RiposteB | ContrattackB | AttackB |
| RiposteA_0021 | cambia | 27 | 27 | 0.08134 | 7.336 | 0 | 27 | 0 | 1.548 | 9.233 | ContrattackA | AttackA | ContrattackA |
| RiposteA_0041 | cambia | 28 | 28 | 0.9782 | 10.84 | 0 | 28 | 0 | 0.9923 | 10.84 | AttackB | ContrattackA | ContrattackA |
| RiposteA_0060 | cambia | 26 | 26 | 0.06511 | 4.163 | 0 | 26 | 0 | 1.053 | 7.598 | ContrattackA | AttackA | ContrattackA |
| AttackA_0007 | no cambia | 15 | 15 | 0.03443 | 5.018 | 0 | 15 | 0 | 1.901 | 7.483 | AttackB | AttackB | ContrattackB |
| AttackA_0189 | no cambia | 18 | 18 | 0.03078 | 4.762 | 0 | 18 | 0 | 0.06996 | 3.938 | ContrattackB | ContrattackB | ContrattackB |
| AttackB_0186 | no cambia | 26 | 26 | 0.1092 | 6.156 | 0 | 26 | 0 | 0.6749 | 10.07 | AttackB | AttackB | ContrattackA |
| ContrattackB_0069 | no cambia | 42 | 42 | 0.8597 | 7.483 | 0 | 42 | 0 | 1.8 | 7.478 | AttackB | AttackB | AttackB |
| RiposteB_0083 | no cambia | 32 | 32 | 0.06062 | 4.72 | 0 | 32 | 0 | 0.9985 | 7.476 | RiposteB | RiposteB | ContrattackB |

- `trim` vs .npy (17 clips con igual T): mean|Δ| 0.1714 / 0.06419 / 0.8834 / 0.9782; max|Δ| 5.513 / 4.762 / 9.309 / 10.84 (media / mediana / p95 / máx entre clips).
- `orig` vs .npy (17 clips con igual T): mean|Δ| 1.066 / 1.005 / 1.911 / 1.951; max|Δ| 8.188 / 7.479 / 11.61 / 14.71 (media / mediana / p95 / máx entre clips).
- `trim` vs Fog(ann) (17 clips): mean|Δ| 0 / 0 / 0 / 0; max|Δ| 0 / 0 / 0 / 0.

## 5. Detalle por clip (Fog con brazo anotado vs .npy)

| stem | brazos A/B | mean|Δ| | p95|Δ| | max|Δ| | primeros 5 mean | resto mean | pred CSV | pred Fog(right) | pred Fog(ann) |
|---|---|---|---|---|---|---|---|---|---|
| AttackA_0007 | right/right | 0.03443 | 0.1026 | 5.018 | 0.01012 | 0.04658 | AttackB | AttackB | AttackB |
| AttackA_0009 | right/right | 0.07005 | 0.2116 | 3.897 | 0.04233 | 0.07608 | ContrattackB | ContrattackB | ContrattackB |
| AttackA_0023 | left/right | 0.1346 | 0.6027 | 10 | 0.03987 | 0.1741 | AttackB | AttackB | AttackB |
| AttackA_0024 | right/right | 0.05506 | 0.1778 | 5.17 | 0.09284 | 0.0475 | AttackA | AttackA | AttackA |
| AttackA_0027 | right/right | 0.02693 | 0.07693 | 5.105 | 0.03492 | 0.02519 | AttackB | AttackB | AttackB |
| AttackA_0029 | left/right | 0.032 | 0.08635 | 3.871 | 0.02317 | 0.03352 | ContrattackA | AttackA | ContrattackA |
| AttackA_0036 | left/right | 0.0342 | 0.08063 | 3.849 | 0.03157 | 0.03521 | AttackA | AttackA | AttackA |
| AttackA_0051 | left/right | 0.02754 | 0.0759 | 4.581 | 0.01083 | 0.03172 | AttackA | AttackA | AttackA |
| AttackA_0056 | right/right | 0.01923 | 0.05671 | 2.974 | 0.02438 | 0.0178 | AttackA | AttackA | AttackA |
| AttackA_0057 | right/right | 0.01963 | 0.04699 | 2.398 | 0.02863 | 0.01213 | AttackB | AttackB | AttackB |
| AttackA_0063 | left/right | 0.07841 | 0.2177 | 4.98 | 0.01373 | 0.09997 | AttackA | AttackA | AttackA |
| AttackA_0071 | right/right | 0.03157 | 0.08168 | 2.754 | 0.008961 | 0.03965 | AttackA | AttackA | AttackA |
| AttackA_0108 | left/right | 0.04243 | 0.1439 | 5.832 | 0.01318 | 0.05157 | RiposteB | RiposteB | RiposteB |
| AttackA_0109 | right/right | 0.01479 | 0.06054 | 0.3008 | 0.005662 | 0.01707 | AttackA | AttackA | AttackA |
| AttackA_0115 | right/right | 0.2511 | 1.42 | 3.878 | 0.09332 | 0.3004 | AttackA | AttackA | AttackA |
| AttackA_0130 | right/right | 0.05436 | 0.1666 | 3.298 | 0.04947 | 0.0561 | AttackA | AttackA | AttackA |
| AttackA_0140 | right/right | 0.07992 | 0.243 | 5.176 | 0.02954 | 0.1051 | AttackA | AttackA | AttackA |
| AttackA_0144 | left/right | 0.03608 | 0.08731 | 2.634 | 0.008772 | 0.04462 | RiposteB | RiposteB | RiposteB |
| AttackA_0152 | right/right | 0.04026 | 0.0755 | 5.031 | 0.01571 | 0.04903 | AttackA | AttackA | AttackA |
| AttackA_0155 | right/right | 0.276 | 1.88 | 6.006 | 0.1101 | 0.322 | RiposteB | RiposteB | RiposteB |
| AttackA_0164 | left/right | 0.02606 | 0.06364 | 3.631 | 0.005706 | 0.02925 | AttackA | AttackA | AttackA |
| AttackA_0167 | right/right | 0.0224 | 0.06207 | 3.862 | 0.00935 | 0.02648 | AttackA | AttackA | AttackA |
| AttackA_0174 | right/right | 0.2999 | 1.723 | 7.477 | 0.05165 | 0.3269 | ContrattackB | ContrattackB | ContrattackB |
| AttackA_0189 | left/right | 0.03078 | 0.0779 | 4.762 | 0.01143 | 0.03823 | ContrattackB | ContrattackB | ContrattackB |
| AttackA_0190 | left/right | 0.01745 | 0.05583 | 2.252 | 0.01047 | 0.0189 | ContrattackA | ContrattackA | ContrattackA |
| AttackA_0193 | right/right | 0.0639 | 0.185 | 3.724 | 0.1036 | 0.04861 | AttackA | AttackA | AttackA |
| AttackA_0198 | left/right | 0.06873 | 0.2157 | 3.834 | 0.06965 | 0.06842 | AttackA | RiposteB | AttackA |
| AttackB_0006 | left/right | 0.03822 | 0.1266 | 2.86 | 0.0228 | 0.04415 | AttackB | AttackB | AttackB |
| AttackB_0016 | right/right | 0.05752 | 0.2034 | 4.575 | 0.04868 | 0.05929 | AttackB | AttackB | AttackB |
| AttackB_0017 | right/right | 0.05882 | 0.1489 | 6.018 | 0.03675 | 0.06408 | AttackB | AttackB | AttackB |
| AttackB_0019 | right/right | 0.05571 | 0.1352 | 4.655 | 0.04265 | 0.06115 | AttackB | AttackB | AttackB |
| AttackB_0052 | left/right | 0.1055 | 0.27 | 5.195 | 0.03375 | 0.1193 | AttackB | AttackB | AttackB |
| AttackB_0055 | right/right | 0.0587 | 0.16 | 4.718 | 0.04331 | 0.06191 | ContrattackB | ContrattackB | ContrattackB |
| AttackB_0057 | right/right | 0.04868 | 0.1714 | 5.483 | 0.06499 | 0.04415 | AttackB | AttackB | AttackB |
| AttackB_0058 | left/right | 0.04836 | 0.1545 | 4.335 | 0.03752 | 0.05155 | AttackB | AttackB | AttackB |
| AttackB_0059 | right/right | 0.05572 | 0.1208 | 4.362 | 0.05365 | 0.05633 | ContrattackA | ContrattackA | ContrattackA |
| AttackB_0064 | left/right | 0.07657 | 0.3046 | 5.14 | 0.008599 | 0.1049 | RiposteA | RiposteA | RiposteA |
| AttackB_0080 | left/right | 0.1287 | 0.6007 | 8.043 | 0.0471 | 0.1513 | AttackB | AttackB | AttackB |
| AttackB_0087 | right/right | 0.09032 | 0.2664 | 4.93 | 0.03636 | 0.1128 | AttackB | AttackB | AttackB |
| AttackB_0096 | right/right | 0.02342 | 0.07573 | 5.123 | 0.0379 | 0.02205 | ContrattackB | ContrattackB | ContrattackB |
| AttackB_0103 | left/right | 0.04218 | 0.08771 | 5.122 | 0.03638 | 0.04389 | AttackB | AttackB | AttackB |
| AttackB_0113 | left/right | 0.0405 | 0.1154 | 3.107 | 0.03879 | 0.0409 | AttackB | AttackB | AttackB |
| AttackB_0139 | right/right | 0.05087 | 0.158 | 3.369 | 0.02692 | 0.05548 | AttackB | AttackB | AttackB |
| AttackB_0142 | right/right | 0.03038 | 0.06662 | 4.926 | 0.008622 | 0.0361 | AttackA | AttackA | AttackA |
| AttackB_0162 | left/right | 0.2189 | 1.021 | 12.51 | 0.04107 | 0.245 | AttackA | AttackA | AttackA |
| AttackB_0167 | left/right | 0.06419 | 0.1766 | 5.943 | 0.07601 | 0.06221 | AttackB | AttackA | AttackB |
| AttackB_0172 | left/right | 0.04067 | 0.1309 | 2.812 | 0.01879 | 0.0475 | RiposteB | RiposteB | RiposteB |
| AttackB_0177 | right/right | 0.5704 | 4.065 | 7.903 | 0.04145 | 0.7096 | AttackB | AttackB | AttackB |
| AttackB_0183 | left/right | 0.08599 | 0.2677 | 5.881 | 0.03576 | 0.09409 | RiposteB | AttackA | AttackA |
| AttackB_0186 | right/right | 0.1092 | 0.3721 | 6.156 | 0.2201 | 0.08284 | AttackB | AttackB | AttackB |
| AttackB_0187 | right/right | 0.0979 | 0.3639 | 6.82 | 0.01421 | 0.1225 | AttackB | AttackB | AttackB |
| AttackB_0188 | right/right | 0.02754 | 0.08549 | 2.689 | 0.01704 | 0.02973 | ContrattackA | ContrattackA | ContrattackA |
| AttackB_0194 | right/right | 0.06696 | 0.2405 | 5.459 | 0.02363 | 0.07836 | AttackB | AttackB | AttackB |
| ContrattackA_0002 | right/right | 0.04329 | 0.149 | 3.458 | 0.03525 | 0.04512 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0005 | left/right | 0.04561 | 0.1386 | 5.033 | 0.04993 | 0.04481 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0010 | right/right | 0.05384 | 0.1587 | 5.176 | 0.01519 | 0.06028 | RiposteA | RiposteA | RiposteA |
| ContrattackA_0015 | left/right | 0.0334 | 0.0927 | 2.875 | 0.04541 | 0.03079 | RiposteA | RiposteA | RiposteA |
| ContrattackA_0019 | left/right | 1.003 | 4.961 | 7.738 | 0.186 | 1.218 | AttackA | AttackA | AttackA |
| ContrattackA_0020 | right/right | 0.02729 | 0.09563 | 3.641 | 0.01674 | 0.0308 | AttackA | AttackA | AttackA |
| ContrattackA_0048 | right/right | 0.03461 | 0.1097 | 3.717 | 0.04047 | 0.03349 | ContrattackA | RiposteA | RiposteA |
| ContrattackA_0055 | right/right | 0.04843 | 0.1255 | 4.486 | 0.05023 | 0.04827 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0056 | right/right | 0.0432 | 0.1659 | 3.208 | 0.04142 | 0.04345 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0070 | right/right | 0.05018 | 0.1303 | 6.379 | 0.03367 | 0.05362 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0071 | left/right | 0.06082 | 0.1694 | 5.769 | 0.01697 | 0.0653 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0072 | left/right | 0.02694 | 0.05923 | 2.9 | 0.01803 | 0.03099 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0075 | right/right | 0.05645 | 0.1903 | 4.866 | 0.03993 | 0.05881 | ContrattackA | ContrattackA | ContrattackA |
| ContrattackA_0085 | left/right | 0.05352 | 0.1797 | 4.252 | 0.01868 | 0.05952 | AttackA | AttackA | AttackA |
| ContrattackB_0001 | right/right | 0.05711 | 0.1815 | 5.334 | 0.03088 | 0.06282 | RiposteB | RiposteB | RiposteB |
| ContrattackB_0006 | right/right | 0.09389 | 0.259 | 10 | 0.01719 | 0.1165 | ContrattackB | ContrattackB | ContrattackB |
| ContrattackB_0015 | left/right | 0.061 | 0.1323 | 4.21 | 0.08058 | 0.05794 | AttackB | ContrattackB | AttackB |
| ContrattackB_0025 | right/right | 0.02826 | 0.09218 | 3.505 | 0.03552 | 0.02612 | RiposteB | ContrattackB | ContrattackB |
| ContrattackB_0033 | left/right | 0.05066 | 0.1751 | 3.697 | 0.03502 | 0.05421 | ContrattackB | ContrattackB | ContrattackB |
| ContrattackB_0041 | left/right | 0.2884 | 2.167 | 8.927 | 0.02379 | 0.3273 | ContrattackB | RiposteB | ContrattackB |
| ContrattackB_0045 | right/right | 0.0307 | 0.0826 | 3.361 | 0.02965 | 0.03091 | RiposteB | ContrattackB | ContrattackB |
| ContrattackB_0050 | left/right | 0.02176 | 0.07453 | 2.728 | 0.03832 | 0.01845 | RiposteB | RiposteB | RiposteB |
| ContrattackB_0056 | left/right | 0.0652 | 0.1883 | 5.088 | 0.03092 | 0.07205 | ContrattackB | ContrattackB | ContrattackB |
| ContrattackB_0066 | right/right | 0.08501 | 0.2783 | 5.106 | 0.03309 | 0.09943 | RiposteB | RiposteB | RiposteB |
| ContrattackB_0069 | right/right | 0.8597 | 6.072 | 7.483 | 0.7028 | 0.8809 | AttackB | AttackB | AttackB |
| ContrattackB_0074 | right/right | 0.03669 | 0.106 | 6.043 | 0.04578 | 0.03471 | RiposteB | RiposteB | RiposteB |
| ContrattackB_0078 | left/right | 0.0266 | 0.06797 | 5.059 | 0.01897 | 0.02796 | ContrattackB | ContrattackB | ContrattackB |
| ContrattackB_0091 | right/right | 0.06053 | 0.1683 | 4.929 | 0.05824 | 0.06095 | RiposteB | RiposteB | RiposteB |
| ContrattackB_0094 | right/right | 0.0302 | 0.1047 | 2.917 | 0.02689 | 0.03117 | ContrattackB | ContrattackB | ContrattackB |
| ContrattackB_0107 | right/right | 0.05134 | 0.1276 | 6.206 | 0.1068 | 0.04208 | ContrattackB | ContrattackB | ContrattackB |
| RiposteA_0021 | right/right | 0.08134 | 0.2891 | 7.336 | 0.03407 | 0.09209 | ContrattackA | AttackA | AttackA |
| RiposteA_0034 | right/right | 0.05377 | 0.1577 | 4.402 | 0.02589 | 0.06151 | RiposteA | RiposteA | RiposteA |
| RiposteA_0041 | right/right | 0.9782 | 5.682 | 10.84 | 0.0364 | 1.183 | AttackB | ContrattackA | ContrattackA |
| RiposteA_0055 | left/right | 0.02926 | 0.07318 | 3.586 | 0.02733 | 0.02966 | ContrattackA | ContrattackA | ContrattackA |
| RiposteA_0057 | right/right | 0.06204 | 0.1592 | 4.792 | 0.03226 | 0.06881 | RiposteA | RiposteA | RiposteA |
| RiposteA_0058 | left/right | 0.05786 | 0.1827 | 4.44 | 0.09295 | 0.0469 | AttackB | AttackB | AttackB |
| RiposteA_0060 | left/right | 0.06511 | 0.2479 | 4.163 | 0.0769 | 0.0623 | ContrattackA | AttackA | AttackA |
| RiposteA_0061 | left/right | 0.0493 | 0.1283 | 3.41 | 0.08427 | 0.03958 | AttackB | AttackB | AttackB |
| RiposteA_0068 | right/right | 0.4702 | 3.36 | 8.566 | 0.06543 | 0.5377 | AttackA | AttackA | AttackA |
| RiposteA_0070 | right/right | 0.02857 | 0.07746 | 3.628 | 0.01847 | 0.03278 | ContrattackA | ContrattackA | ContrattackA |
| RiposteA_0072 | left/right | 0.05859 | 0.1738 | 3.295 | 0.02103 | 0.06798 | RiposteA | RiposteA | RiposteA |
| RiposteB_0004 | right/right | 0.05966 | 0.1826 | 4.787 | 0.01869 | 0.06896 | RiposteB | RiposteB | RiposteB |
| RiposteB_0007 | right/right | 0.03593 | 0.1217 | 2.751 | 0.02685 | 0.03845 | RiposteB | RiposteB | RiposteB |
| RiposteB_0011 | right/right | 0.04725 | 0.1156 | 6.893 | 0.03442 | 0.05046 | RiposteB | RiposteB | RiposteB |
| RiposteB_0057 | right/right | 0.04515 | 0.1468 | 4.11 | 0.06616 | 0.03932 | RiposteB | RiposteB | RiposteB |
| RiposteB_0062 | left/right | 0.05125 | 0.1603 | 3.71 | 0.03472 | 0.05343 | ContrattackB | ContrattackB | ContrattackB |
| RiposteB_0071 | right/right | 0.07817 | 0.2542 | 5.776 | 0.04725 | 0.09106 | AttackB | AttackB | AttackB |
| RiposteB_0075 | right/right | 0.0655 | 0.1912 | 6.113 | 0.02208 | 0.07584 | RiposteB | RiposteB | RiposteB |
| RiposteB_0078 | right/right | 0.03807 | 0.09686 | 3.571 | 0.07793 | 0.027 | ContrattackB | ContrattackB | ContrattackB |
| RiposteB_0082 | right/right | 0.0384 | 0.1153 | 3.362 | 0.02615 | 0.04132 | RiposteB | RiposteB | RiposteB |
| RiposteB_0083 | left/right | 0.06062 | 0.1713 | 4.72 | 0.03392 | 0.06556 | RiposteB | RiposteB | RiposteB |
