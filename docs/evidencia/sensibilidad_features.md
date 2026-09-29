# Prueba de sensibilidad de features — dataset vs Fog

> **Errata.** La versión anterior de este reporte pasaba brazo armado `right`/`right` a Fog, mientras que los `.npy` se extrajeron con el brazo anotado en Label Studio (pk=5). Eso sobrestimaba la discrepancia: 92/104 predicciones iguales al CSV frente a 97/104 con el brazo anotado, que es lo que usa esta versión.

Checkpoint: `20260928_141021/best_model.pt` (luz_size=0, hidden_size=64). Comparación contra `results/20260928_141021_predictions.csv`.

Clips comparados: 104/104. Fallas de extracción: 0.

## Accuracy y F1 macro de sistema por camino

| Camino | Acc sistema | F1 macro sistema |
|---|---|---|
| CSV guardado (`pred_sistema` original) | 0.5577 | 0.5249 |
| Reproducción camino dataset (`.npy` + `_standardize_and_clamp`) | 0.5577 | 0.5249 |
| Camino Fog (`YoloV8PoseAdapter` + `New192FeatureExtractor`) | 0.5673 | 0.5380 |

La fila "Reproducción camino dataset" debe coincidir con la fila "CSV guardado" — confirma que esta prueba reproduce el mismo cálculo que `evaluate.py` antes de comparar contra Fog.

## Coincidencia de pred_sistema contra el CSV guardado

- Reproducción dataset == CSV: 104/104 (1.0000)
- Fog == CSV: 97/104 (0.9327)

## Diferencia de features normalizadas (dataset vs Fog), por clip

- max|Δ| — media sobre 104 clips: 4.873 (máximo: 12.51)
- mean|Δ| — media sobre 104 clips: 0.09674 (máximo: 1.003)

## Clips donde Fog difiere de la predicción guardada

| stem | true_label | pred CSV | pred Fog | max|Δ| | mean|Δ| |
|---|---|---|---|---|---|
| AttackB_0183 | AttackB | RiposteB | AttackA | 5.881 | 0.08599 |
| ContrattackA_0048 | ContrattackA | ContrattackA | RiposteA | 3.717 | 0.03461 |
| ContrattackB_0025 | ContrattackB | RiposteB | ContrattackB | 3.505 | 0.02826 |
| ContrattackB_0045 | ContrattackB | RiposteB | ContrattackB | 3.361 | 0.0307 |
| RiposteA_0021 | RiposteA | ContrattackA | AttackA | 7.336 | 0.08134 |
| RiposteA_0041 | RiposteA | AttackB | ContrattackA | 10.84 | 0.9782 |
| RiposteA_0060 | RiposteA | ContrattackA | AttackA | 4.163 | 0.06511 |

## Todos los clips (detalle)

| stem | clase | true_label | pred CSV | pred dataset (repro) | pred Fog | max|Δ| | mean|Δ| |
|---|---|---|---|---|---|---|---|
| AttackA_0007 | AttackA | AttackA | AttackB | AttackB | AttackB | 5.018 | 0.03443 |
| AttackA_0009 | AttackA | AttackA | ContrattackB | ContrattackB | ContrattackB | 3.897 | 0.07005 |
| AttackA_0023 | AttackA | AttackA | AttackB | AttackB | AttackB | 10 | 0.1346 |
| AttackA_0024 | AttackA | AttackA | AttackA | AttackA | AttackA | 5.17 | 0.05506 |
| AttackA_0027 | AttackA | AttackA | AttackB | AttackB | AttackB | 5.105 | 0.02693 |
| AttackA_0029 | AttackA | AttackA | ContrattackA | ContrattackA | ContrattackA | 3.871 | 0.032 |
| AttackA_0036 | AttackA | AttackA | AttackA | AttackA | AttackA | 3.849 | 0.0342 |
| AttackA_0051 | AttackA | AttackA | AttackA | AttackA | AttackA | 4.581 | 0.02754 |
| AttackA_0056 | AttackA | AttackA | AttackA | AttackA | AttackA | 2.974 | 0.01923 |
| AttackA_0057 | AttackA | AttackA | AttackB | AttackB | AttackB | 2.398 | 0.01963 |
| AttackA_0063 | AttackA | AttackA | AttackA | AttackA | AttackA | 4.98 | 0.07841 |
| AttackA_0071 | AttackA | AttackA | AttackA | AttackA | AttackA | 2.754 | 0.03157 |
| AttackA_0108 | AttackA | AttackA | RiposteB | RiposteB | RiposteB | 5.832 | 0.04243 |
| AttackA_0109 | AttackA | AttackA | AttackA | AttackA | AttackA | 0.3008 | 0.01479 |
| AttackA_0115 | AttackA | AttackA | AttackA | AttackA | AttackA | 3.878 | 0.2511 |
| AttackA_0130 | AttackA | AttackA | AttackA | AttackA | AttackA | 3.298 | 0.05436 |
| AttackA_0140 | AttackA | AttackA | AttackA | AttackA | AttackA | 5.176 | 0.07992 |
| AttackA_0144 | AttackA | AttackA | RiposteB | RiposteB | RiposteB | 2.634 | 0.03608 |
| AttackA_0152 | AttackA | AttackA | AttackA | AttackA | AttackA | 5.031 | 0.04026 |
| AttackA_0155 | AttackA | AttackA | RiposteB | RiposteB | RiposteB | 6.006 | 0.276 |
| AttackA_0164 | AttackA | AttackA | AttackA | AttackA | AttackA | 3.631 | 0.02606 |
| AttackA_0167 | AttackA | AttackA | AttackA | AttackA | AttackA | 3.862 | 0.0224 |
| AttackA_0174 | AttackA | AttackA | ContrattackB | ContrattackB | ContrattackB | 7.477 | 0.2999 |
| AttackA_0189 | AttackA | AttackA | ContrattackB | ContrattackB | ContrattackB | 4.762 | 0.03078 |
| AttackA_0190 | AttackA | AttackA | ContrattackA | ContrattackA | ContrattackA | 2.252 | 0.01745 |
| AttackA_0193 | AttackA | AttackA | AttackA | AttackA | AttackA | 3.724 | 0.0639 |
| AttackA_0198 | AttackA | AttackA | AttackA | AttackA | AttackA | 3.834 | 0.06873 |
| AttackB_0006 | AttackB | AttackB | AttackB | AttackB | AttackB | 2.86 | 0.03822 |
| AttackB_0016 | AttackB | AttackB | AttackB | AttackB | AttackB | 4.575 | 0.05752 |
| AttackB_0017 | AttackB | AttackB | AttackB | AttackB | AttackB | 6.018 | 0.05882 |
| AttackB_0019 | AttackB | AttackB | AttackB | AttackB | AttackB | 4.655 | 0.05571 |
| AttackB_0052 | AttackB | AttackB | AttackB | AttackB | AttackB | 5.195 | 0.1055 |
| AttackB_0055 | AttackB | AttackB | ContrattackB | ContrattackB | ContrattackB | 4.718 | 0.0587 |
| AttackB_0057 | AttackB | AttackB | AttackB | AttackB | AttackB | 5.483 | 0.04868 |
| AttackB_0058 | AttackB | AttackB | AttackB | AttackB | AttackB | 4.335 | 0.04836 |
| AttackB_0059 | AttackB | AttackB | ContrattackA | ContrattackA | ContrattackA | 4.362 | 0.05572 |
| AttackB_0064 | AttackB | AttackB | RiposteA | RiposteA | RiposteA | 5.14 | 0.07657 |
| AttackB_0080 | AttackB | AttackB | AttackB | AttackB | AttackB | 8.043 | 0.1287 |
| AttackB_0087 | AttackB | AttackB | AttackB | AttackB | AttackB | 4.93 | 0.09032 |
| AttackB_0096 | AttackB | AttackB | ContrattackB | ContrattackB | ContrattackB | 5.123 | 0.02342 |
| AttackB_0103 | AttackB | AttackB | AttackB | AttackB | AttackB | 5.122 | 0.04218 |
| AttackB_0113 | AttackB | AttackB | AttackB | AttackB | AttackB | 3.107 | 0.0405 |
| AttackB_0139 | AttackB | AttackB | AttackB | AttackB | AttackB | 3.369 | 0.05087 |
| AttackB_0142 | AttackB | AttackB | AttackA | AttackA | AttackA | 4.926 | 0.03038 |
| AttackB_0162 | AttackB | AttackB | AttackA | AttackA | AttackA | 12.51 | 0.2189 |
| AttackB_0167 | AttackB | AttackB | AttackB | AttackB | AttackB | 5.943 | 0.06419 |
| AttackB_0172 | AttackB | AttackB | RiposteB | RiposteB | RiposteB | 2.812 | 0.04067 |
| AttackB_0177 | AttackB | AttackB | AttackB | AttackB | AttackB | 7.903 | 0.5704 |
| AttackB_0183 | AttackB | AttackB | RiposteB | RiposteB | AttackA | 5.881 | 0.08599 |
| AttackB_0186 | AttackB | AttackB | AttackB | AttackB | AttackB | 6.156 | 0.1092 |
| AttackB_0187 | AttackB | AttackB | AttackB | AttackB | AttackB | 6.82 | 0.0979 |
| AttackB_0188 | AttackB | AttackB | ContrattackA | ContrattackA | ContrattackA | 2.689 | 0.02754 |
| AttackB_0194 | AttackB | AttackB | AttackB | AttackB | AttackB | 5.459 | 0.06696 |
| ContrattackA_0002 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 3.458 | 0.04329 |
| ContrattackA_0005 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 5.033 | 0.04561 |
| ContrattackA_0010 | ContrattackA | ContrattackA | RiposteA | RiposteA | RiposteA | 5.176 | 0.05384 |
| ContrattackA_0015 | ContrattackA | ContrattackA | RiposteA | RiposteA | RiposteA | 2.875 | 0.0334 |
| ContrattackA_0019 | ContrattackA | ContrattackA | AttackA | AttackA | AttackA | 7.738 | 1.003 |
| ContrattackA_0020 | ContrattackA | ContrattackA | AttackA | AttackA | AttackA | 3.641 | 0.02729 |
| ContrattackA_0048 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | RiposteA | 3.717 | 0.03461 |
| ContrattackA_0055 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 4.486 | 0.04843 |
| ContrattackA_0056 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 3.208 | 0.0432 |
| ContrattackA_0070 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 6.379 | 0.05018 |
| ContrattackA_0071 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 5.769 | 0.06082 |
| ContrattackA_0072 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 2.9 | 0.02694 |
| ContrattackA_0075 | ContrattackA | ContrattackA | ContrattackA | ContrattackA | ContrattackA | 4.866 | 0.05645 |
| ContrattackA_0085 | ContrattackA | ContrattackA | AttackA | AttackA | AttackA | 4.252 | 0.05352 |
| ContrattackB_0001 | ContrattackB | ContrattackB | RiposteB | RiposteB | RiposteB | 5.334 | 0.05711 |
| ContrattackB_0006 | ContrattackB | ContrattackB | ContrattackB | ContrattackB | ContrattackB | 10 | 0.09389 |
| ContrattackB_0015 | ContrattackB | ContrattackB | AttackB | AttackB | AttackB | 4.21 | 0.061 |
| ContrattackB_0025 | ContrattackB | ContrattackB | RiposteB | RiposteB | ContrattackB | 3.505 | 0.02826 |
| ContrattackB_0033 | ContrattackB | ContrattackB | ContrattackB | ContrattackB | ContrattackB | 3.697 | 0.05066 |
| ContrattackB_0041 | ContrattackB | ContrattackB | ContrattackB | ContrattackB | ContrattackB | 8.927 | 0.2884 |
| ContrattackB_0045 | ContrattackB | ContrattackB | RiposteB | RiposteB | ContrattackB | 3.361 | 0.0307 |
| ContrattackB_0050 | ContrattackB | ContrattackB | RiposteB | RiposteB | RiposteB | 2.728 | 0.02176 |
| ContrattackB_0056 | ContrattackB | ContrattackB | ContrattackB | ContrattackB | ContrattackB | 5.088 | 0.0652 |
| ContrattackB_0066 | ContrattackB | ContrattackB | RiposteB | RiposteB | RiposteB | 5.106 | 0.08501 |
| ContrattackB_0069 | ContrattackB | ContrattackB | AttackB | AttackB | AttackB | 7.483 | 0.8597 |
| ContrattackB_0074 | ContrattackB | ContrattackB | RiposteB | RiposteB | RiposteB | 6.043 | 0.03669 |
| ContrattackB_0078 | ContrattackB | ContrattackB | ContrattackB | ContrattackB | ContrattackB | 5.059 | 0.0266 |
| ContrattackB_0091 | ContrattackB | ContrattackB | RiposteB | RiposteB | RiposteB | 4.929 | 0.06053 |
| ContrattackB_0094 | ContrattackB | ContrattackB | ContrattackB | ContrattackB | ContrattackB | 2.917 | 0.0302 |
| ContrattackB_0107 | ContrattackB | ContrattackB | ContrattackB | ContrattackB | ContrattackB | 6.206 | 0.05134 |
| RiposteA_0021 | RiposteA | RiposteA | ContrattackA | ContrattackA | AttackA | 7.336 | 0.08134 |
| RiposteA_0034 | RiposteA | RiposteA | RiposteA | RiposteA | RiposteA | 4.402 | 0.05377 |
| RiposteA_0041 | RiposteA | RiposteA | AttackB | AttackB | ContrattackA | 10.84 | 0.9782 |
| RiposteA_0055 | RiposteA | RiposteA | ContrattackA | ContrattackA | ContrattackA | 3.586 | 0.02926 |
| RiposteA_0057 | RiposteA | RiposteA | RiposteA | RiposteA | RiposteA | 4.792 | 0.06204 |
| RiposteA_0058 | RiposteA | RiposteA | AttackB | AttackB | AttackB | 4.44 | 0.05786 |
| RiposteA_0060 | RiposteA | RiposteA | ContrattackA | ContrattackA | AttackA | 4.163 | 0.06511 |
| RiposteA_0061 | RiposteA | RiposteA | AttackB | AttackB | AttackB | 3.41 | 0.0493 |
| RiposteA_0068 | RiposteA | RiposteA | AttackA | AttackA | AttackA | 8.566 | 0.4702 |
| RiposteA_0070 | RiposteA | RiposteA | ContrattackA | ContrattackA | ContrattackA | 3.628 | 0.02857 |
| RiposteA_0072 | RiposteA | RiposteA | RiposteA | RiposteA | RiposteA | 3.295 | 0.05859 |
| RiposteB_0004 | RiposteB | RiposteB | RiposteB | RiposteB | RiposteB | 4.787 | 0.05966 |
| RiposteB_0007 | RiposteB | RiposteB | RiposteB | RiposteB | RiposteB | 2.751 | 0.03593 |
| RiposteB_0011 | RiposteB | RiposteB | RiposteB | RiposteB | RiposteB | 6.893 | 0.04725 |
| RiposteB_0057 | RiposteB | RiposteB | RiposteB | RiposteB | RiposteB | 4.11 | 0.04515 |
| RiposteB_0062 | RiposteB | RiposteB | ContrattackB | ContrattackB | ContrattackB | 3.71 | 0.05125 |
| RiposteB_0071 | RiposteB | RiposteB | AttackB | AttackB | AttackB | 5.776 | 0.07817 |
| RiposteB_0075 | RiposteB | RiposteB | RiposteB | RiposteB | RiposteB | 6.113 | 0.0655 |
| RiposteB_0078 | RiposteB | RiposteB | ContrattackB | ContrattackB | ContrattackB | 3.571 | 0.03807 |
| RiposteB_0082 | RiposteB | RiposteB | RiposteB | RiposteB | RiposteB | 3.362 | 0.0384 |
| RiposteB_0083 | RiposteB | RiposteB | RiposteB | RiposteB | RiposteB | 4.72 | 0.06062 |
