# Límite físico de la señal Favero y propuesta sobre RF-06 (EDGE01)

**Estado: sin medir.** Falta el aparato real. Los números de la sección 2 salen de una simulación a partir del protocolo, no de la pista. Hay que reemplazarlos por los de `edge/calibrar_latencia.py` (sección 3) antes de decidir. Según `EDGE01`, no se asume nada: la decisión sobre RF-06 es del autor.

## 1. Por qué el límite es mayor que una trama

El Favero manda tramas de 10 bytes a 2400 baudios, una detrás de otra. Cada trama tarda 10 × 10 bits / 2400 = **41,67 ms** en transmitirse y no hay pausa entre ellas. Cuando se enciende una luz en el aparato (instante real R):

1. La trama que ya está saliendo lleva el estado viejo. La luz aparece en la **siguiente**, que empieza entre 0 y 41,67 ms después de R.
2. El lector marca el flanco al llegar el **último byte** de esa trama, 41,67 ms después de que empezó.

Por eso el instante serie es `R + U(0; 41,67) + 41,67 ms`: llega entre 41,7 y 83,3 ms tarde, con una **incertidumbre uniforme de 41,67 ms** que ninguna calibración quita (la media sí se resta; el reparto no). El puente Arduino suma una latencia pequeña y casi constante, que la calibración absorbe.

La cámara agrega su propia latencia (constante, también calibrable) y una **cuantización de un frame** (33,3 ms a 30 fps) al ver la luz.

## 2. Error esperado tras calibrar (simulación, 10^6 toques, 30 fps)

| Medida | Valor |
|---|---|
| Desviación del error (serie + frame) | 15,4 ms |
| Error máximo | ±37,5 ms |
| Percentil 95 de \|error\| | 29,2 ms |
| Toques con \|error\| ≤ 16 ms (RF-06 actual) | 66,7 % |
| Toques con \|error\| ≤ 33,3 ms (1 frame a 30 fps) | 98,8 % |
| Toques con \|error\| ≤ 41,7 ms (1 trama Favero) | 100 % |

Supone latencia de cámara constante y sin pérdida de tramas. El desfase medio que mide la calibración suma la latencia de cámara y la del camino serie; **puede salir negativo** (aquí la simulación da −45,9 ms con cámara sin latencia) y `CapturaTocados` lo suma tal cual con su signo.

Conclusión provisional: **≤ 16 ms (RF-06 actual) no se puede garantizar solo con la señal serie**, ni con calibración perfecta. Con 30 fps tampoco es alcanzable para el video: un frame son 33,3 ms.

## 3. Cómo medir el error real

```bash
python -m edge.calibrar_latencia --puerto '/dev/cu.usbmodem*' --camara 0 \
    --roi-roja x,y,w,h --roi-verde x,y,w,h --toques 20
```

Requisitos: repetidor de luces o las luces del aparato dentro del cuadro; iluminación fija; reiniciar el aparato entre toques; ≥ 20 toques por luz. El script imprime y guarda en `datos/edge/latencia_camara.json`, por cámara y por luz: `n`, `desfase_ms` (media), `desviacion_ms`, `minimo_ms`, `maximo_ms`, `residuo_max_ms` (el error que queda tras restar la media), toques sin pareja, tramas inválidas y huecos. Comparar la desviación y el residuo con la tabla de la sección 2.

## 4. Opciones para RF-06 (decide el autor)

- **A. Redactar RF-06 como "≤ 1 trama Favero (~42 ms) tras corregir la latencia de la cámara".** Es lo que la señal serie sostiene (en la simulación, 100 % de los toques). No exige cambios de hardware ni de código. Pierde la meta de ≤ 16 ms.
- **B. Refinar el instante con la luz vista en el video** cuando el repetidor esté en cuadro. Quita la incertidumbre de 41,67 ms de la serie, pero queda limitada por la cámara a **un frame** (33,3 ms a 30 fps, 16,7 ms a 60 fps), así que ≤ 16 ms solo sería posible con ≥ 60 fps. Requiere un repetidor visible, detección de brillo en la inferencia y un criterio para cuando la luz no se ve; no está implementado.

Ninguna de las dos garantiza 16 ms a 30 fps. Si la meta de 16 ms se mantiene, haría falta una cámara de 60 fps o más (el RNF-13 pide ≥ 30 fps) y la opción B.

Una cosa que sí cambia poco: el modelo solo usa **qué luces** se encendieron, y los instantes no entran a las features ni a la ventana (CONTRATO_API §4). El efecto práctico de 42 ms de incertidumbre es la posición del frame del tocado dentro del clip, no la clasificación.
