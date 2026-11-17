# Puente Favero: guía para quien nunca usó Arduino

Esta guía te lleva de "tengo un Arduino UNO" a "mi Mac muestra lo que dice el Favero". Sigue los pasos en orden. Si algo no sale como dice la guía, **detente** y anota lo que viste.

**Regla de oro:** cambia cables solo con el USB del Arduino desconectado y el Favero apagado.

Qué hay en esta carpeta:

| Archivo | Para qué sirve |
|---|---|
| `arduino/puente_favero/puente_favero.ino` | El programa que se carga en el Arduino |
| `diagnostico.py` | Programa de la Mac que muestra en palabras lo que llega |
| `lector.py` | Entiende las tramas del Favero (lo usará también la captura de tocados) |

---

## 1. Abrir el programa en Arduino IDE 2

1. Abre **Arduino IDE 2**.
2. Menú **Archivo → Abrir...** y elige el archivo
   `backend/edge/favero/arduino/puente_favero/puente_favero.ino`.
3. Se abre una ventana con el código. No hace falta entenderlo ni cambiarlo.

## 2. Elegir la placa y el puerto

1. Conecta el Arduino a la Mac con el cable USB. Debe encenderse la luz verde "ON".
2. Menú **Herramientas → Placa → Arduino AVR Boards → Arduino Uno**.
3. Menú **Herramientas → Puerto →** el que diga `usbmodem` (por ejemplo `/dev/cu.usbmodem11201`).

## 3. Subirlo y reconocer que funcionó

1. Pulsa la flecha **→ (Subir)**, arriba a la izquierda.
2. Espera. Durante la subida parpadean las luces **TX** y **RX** de la placa.
3. Abajo debe aparecer **"Subido"** (en inglés: *Done uploading*).

Cómo reconocer que funcionó:

```
El Sketch usa 4938 bytes (15%) del espacio de almacenamiento de programa.
...
Subido
```

Si aparece un texto rojo con `avrdude` o `not in sync`:
1. Revisa el paso 2 (placa y puerto).
2. Cierra el **Monitor Serie** si estaba abierto.
3. Desenchufa el USB, espera 5 segundos, enchúfalo y vuelve a subir.

La prueba de verdad es el paso siguiente.

## 4. Correr el diagnóstico en autoprueba

La autoprueba hace que el Arduino **invente** tramas del Favero. Sirve para probar todo el camino sin el Favero ni cables.

1. Abre la **Terminal**.
2. Ve a la carpeta del backend y activa el entorno:

   ```bash
   cd /Users/darkarcher/Documents/Claude/Projects/Tesis/Software/backend
   source .venv/bin/activate
   ```
3. Corre el diagnóstico (se detiene solo a los 15 segundos; sin `--segundos` sigue hasta que pulses **Ctrl+C**):

   ```bash
   python -m edge.favero.diagnostico --modo autoprueba --segundos 15
   ```

Lo que debes ver:

```
Puerto: /dev/cu.usbmodem11201. Esperando al Arduino (2 s, se reinicia al abrir)...
Modo del Arduino: autoprueba.
Arduino listo: modo A, lógica normal.
Leyendo... (Ctrl+C para terminar)

OK · 24 tramas/s válidas · 0 inválidas · luces: ninguna
OK · 24 tramas/s válidas · 0 inválidas · luces: ROJA
OK · 24 tramas/s válidas · 0 inválidas · luces: ninguna
OK · 24 tramas/s válidas · 0 inválidas · luces: VERDE
OK · 24 tramas/s válidas · 0 inválidas · luces: ROJA + VERDE (doble)
```

Cada ~12 segundos el Arduino repite: una luz roja, una verde y una doble. Mientras tanto, la luz **L** de la placa parpadea. Si ves esto, **el software está listo.**

## 5. Los mensajes del diagnóstico y qué hacer

El diagnóstico escribe una línea por segundo.

| Lo que ves | Qué significa | Qué hacer |
|---|---|---|
| `OK · 24 tramas/s válidas · 0 inválidas · luces: ninguna` | Todo bien. Llegan tramas completas. `luces:` dice qué luces se encendieron en ese segundo | Nada |
| `OK · ... · luces: ROJA` / `VERDE` / `ROJA + VERDE (doble)` | Se encendió una luz o las dos | Nada. La roja es la izquierda; la verde, la derecha |
| `OK · 22 tramas/s válidas · 2 inválidas` | Casi todo bien, pero se corrompieron algunas tramas | Si pasa a cada rato: cables flojos o resistencia mal puesta (Fase 6) |
| `SIN DATOS · 0 bytes/s · revisa la conexión (Fase 6/7 del plan)` | No llega ni un byte | En modo real: apaga todo, revisa el circuito (Fase 6); si está bien, intercambia los cables de **C3 y C4** (Fase 7). En autoprueba: el Arduino no tiene el programa; repite los pasos 2 y 3 |
| `SEÑAL RARA · 380 bytes/s pero 0 tramas válidas` | Llegan bytes, pero no forman tramas: puede estar al revés (polaridad) | El programa lo prueba solo (ver más abajo). Si no lo arregla, revisa la Fase 6 |
| `→ Llegan bytes pero ninguna trama válida. Pruebo la lógica INVERTIDA...` | Tras 3 segundos así, el programa le manda la orden `I` al Arduino para darle la vuelta a la señal | Espera otros 3 segundos |
| `✓ Funcionó con la lógica INVERTIDA. Quedó guardada...` | Con la polaridad contraria sí llegaron tramas válidas | Nada. El Arduino lo recuerda aunque lo desenchufes |
| `✗ Ni la lógica normal ni la invertida dieron tramas válidas...` | Ninguna de las dos funcionó. El programa deja todo como estaba | Revisa la Fase 6; intercambia los cables de C3 y C4 (Fase 7); si sigue igual, anota lo que ves y consúltalo |
| `⚠ El Arduino no contestó...` (al empezar) | El Arduino no tiene este programa | Repite los pasos 2 y 3 de esta guía |
| `✗ No encuentro el Arduino (no hay ningún puerto /dev/cu.usbmodem*)` | La Mac no ve el Arduino | Revisa el cable USB (prueba otro) y que la luz "ON" esté encendida (Fase 1) |
| `✗ No pude abrir el puerto ...` | Otro programa lo está usando | Cierra el **Monitor Serie** del Arduino IDE y vuelve a intentar |
| `✗ Se perdió la conexión con el Arduino` | Se movió o se soltó el USB | Revisa el cable y vuelve a correr el programa |

Si hay **dos puertos** `usbmodem`, el programa muestra una lista numerada y te pide que escribas el número.

## 6. Modo LAZO: probar el pin 8 sin el Favero

Sirve para comprobar que el Arduino lee bien por el **pin 8**.

1. **Desconecta el USB.** Saca del pin 8 los cables del circuito de resistencias. **En este modo el circuito no va conectado al pin 8.**
2. Une con un cable dupont el **pin 9** con el **pin 8**.
3. Conecta el USB y corre:

   ```bash
   python -m edge.favero.diagnostico --modo lazo --segundos 15
   ```
4. Debes ver líneas parecidas a las de la autoprueba, con unas **23 tramas/s** (algo menos de 24 por una pausa corta que se deja para recibir órdenes por USB):

   ```
   OK · 23 tramas/s válidas · 0 inválidas · luces: ROJA
   ```
5. Si ves `SIN DATOS` o `SEÑAL RARA`, el cable 9-8 no está bien puesto o está en otros pines. Revisa que sean exactamente el 8 y el 9.
6. Cuando termines, **desconecta el USB**, quita el cable 9-8 y vuelve a armar el circuito de la Fase 6.

> Nota técnica: en este modo el Arduino genera la señal en el pin 9 y la lee en el pin 8 con una rutina propia, no con la librería `SoftwareSerial`. La librería no puede recibir mientras transmite. Así que esta prueba confirma el cable y el pin 8, pero **no** ejercita la recepción de `SoftwareSerial`. Esa se prueba con el Favero (Fase 7).

## 7. Modo real (con el Favero)

Con el circuito de la Fase 6 armado y el Favero encendido:

```bash
python -m edge.favero.diagnostico
```

Esperado: `OK · ~24 tramas/s válidas · 0 inválidas · luces: ninguna`. Al tocar a la izquierda sale `ROJA`; a la derecha, `VERDE`.

### Guardar los toques en un archivo (Fase 8)

```bash
python -m edge.favero.diagnostico --registrar toques.csv
```

Se crea `toques.csv` con una fila por cada **cambio de luces** y una por cada trama inválida. Columnas: `monotonic_ns` (reloj interno de alta precisión), `hora_local`, `valida` (1 = sí, 0 = no) y el estado de las 6 luces (1 = encendida). Las filas inválidas llevan las luces vacías.

Para contar los toques (usa la hora del registro, no necesita el Arduino):

```bash
python -m edge.favero.diagnostico --resumen toques.csv
```

```
Resumen del registro:
  Toques ROJOS (izquierda):  20
  Toques VERDES (derecha):   20
  Dobles (roja y verde):     10
  Tramas inválidas:          0
```

Un **toque** es un tramo con la luz roja o la verde encendida, hasta que ambas se apagan. Es **doble** si en ese tramo se vieron las dos. Las luces blancas y amarillas no se cuentan.

## 8. Los comandos del Arduino (por si quieres probar a mano)

El diagnóstico los envía solo. Son letras sueltas por USB:

| Letra | Qué hace |
|---|---|
| `P` | Modo **puente** (el normal). Es el que queda cada vez que se abre el puerto |
| `A` | Modo **autoprueba** |
| `L` | Modo **lazo** |
| `I` | **Invierte** la lógica del pin 8, cada vez que se envía |
| `?` | El Arduino responde su estado, por ejemplo `HW01 modo=P invertida=0` |

**Memoria del Arduino (EEPROM):** al usar `I`, la lógica elegida **se guarda en la EEPROM** del Arduino (una memoria que no se borra al desenchufarlo). Al encender, el Arduino lee ese valor. Por eso la prueba de polaridad se hace una sola vez. El modo (P, A o L) **no** se guarda: siempre arranca en puente.

**Luz "L"** de la placa: parpadea mientras pasan bytes y se apaga cuando no pasa nada.

## 9. Detalles que conviene saber

* Al abrir el puerto desde la Mac, el Arduino **se reinicia solo** (por eso el diagnóstico espera 2 segundos).
* No uses nunca los pines 0 y 1 del Arduino: están conectados al chip USB.
* La hora de cada fila del CSV es la de la Mac al **recibir** los bytes. El puente agrega un retraso pequeño y casi constante; la calibración de EDGE01 lo absorbe.
* En la autoprueba, cuántos segundos dura cada luz es un invento de la simulación; no es el comportamiento medido del Favero.
