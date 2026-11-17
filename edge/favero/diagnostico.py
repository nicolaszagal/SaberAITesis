"""Herramienta de diagnóstico del puente Favero (HW01).

Uso (desde la carpeta `backend`, con el `.venv` activado):

    python -m edge.favero.diagnostico                       # modo real
    python -m edge.favero.diagnostico --modo autoprueba     # sin el Favero
    python -m edge.favero.diagnostico --modo lazo           # cable 9-8, sin el Favero
    python -m edge.favero.diagnostico --registrar toques.csv
    python -m edge.favero.diagnostico --resumen toques.csv

Cada segundo imprime una línea en palabras. Ver `LEEME.md` para qué hacer con cada mensaje.
"""

from __future__ import annotations

import argparse
import csv
import glob
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from edge.favero.lector import Luces, ParserTramas, Trama

PATRON_PUERTO = "/dev/cu.usbmodem*"
BAUDIOS_USB = 115200
SEGUNDOS_SIN_TRAMAS_VALIDAS = 3  # bytes sin ninguna trama válida durante este tiempo -> probar polaridad
ESPERA_ARRANQUE_S = 2.0  # al abrir el puerto el Arduino se reinicia solo
MODOS = {"puente": "P", "autoprueba": "A", "lazo": "L"}

COLUMNAS_CSV = [
    "monotonic_ns",
    "hora_local",
    "valida",
    "roja",
    "verde",
    "blanca_d0",
    "blanca_d1",
    "amarilla_d4",
    "amarilla_d5",
]

_PATRON_ESTADO = re.compile(r"HW01 modo=(\w) invertida=([01])")


class PuertoSerie(Protocol):
    """Lo mínimo que se usa de pyserial (así se puede reemplazar por un doble en pruebas)."""

    def read(self, size: int = 1) -> bytes: ...
    def write(self, data: bytes) -> int | None: ...
    def reset_input_buffer(self) -> None: ...
    def close(self) -> None: ...

    @property
    def in_waiting(self) -> int: ...


class ErrorDiagnostico(Exception):
    """Error pensado para mostrarse tal cual al autor (mensaje en español llano)."""


# --------------------------------------------------------------------------- puerto


def elegir_puerto(
    candidatos: list[str] | None = None,
    preguntar: Callable[[str], str] = input,
    salida: Callable[[str], None] = print,
) -> str:
    """Encuentra el puerto del Arduino (`/dev/cu.usbmodem*`).

    Args:
        candidatos: lista de puertos; si es `None` se buscan con glob.
        preguntar: función para pedir una opción cuando hay varios.
        salida: función para mostrar mensajes.

    Returns:
        La ruta del puerto elegido.

    Raises:
        ErrorDiagnostico: si no hay ninguno, o la opción elegida no es válida.
    """
    puertos = sorted(candidatos if candidatos is not None else glob.glob(PATRON_PUERTO))
    if not puertos:
        raise ErrorDiagnostico(
            "No encuentro el Arduino (no hay ningún puerto /dev/cu.usbmodem*).\n"
            "  1. Revisa que el cable USB esté bien enchufado en el Arduino y en la Mac.\n"
            "  2. Prueba otro cable USB (algunos solo cargan y no pasan datos).\n"
            "  3. Mira que el LED verde 'ON' del Arduino esté encendido.\n"
            "  Más detalle: Fase 1 del plan, pasos 2 y 3."
        )
    if len(puertos) == 1:
        return puertos[0]
    salida("Hay varios puertos posibles:")
    for numero, ruta in enumerate(puertos, start=1):
        salida(f"  {numero}. {ruta}")
    respuesta = preguntar("Escribe el número del que quieres usar: ").strip()
    if not respuesta.isdigit() or not 1 <= int(respuesta) <= len(puertos):
        raise ErrorDiagnostico(f"'{respuesta}' no es una opción válida. Vuelve a correr el programa.")
    return puertos[int(respuesta) - 1]


def abrir_puerto(ruta: str, baudios: int = BAUDIOS_USB) -> Any:
    """Abre el puerto serie (acepta también URLs de pyserial como `loop://`).

    Args:
        ruta: ruta del dispositivo, p. ej. `/dev/cu.usbmodem1101`.
        baudios: velocidad del lado USB del puente.

    Returns:
        El objeto de pyserial, con lectura de espera corta (50 ms).

    Raises:
        ErrorDiagnostico: si no se puede abrir (con el paso del plan donde mirar).
    """
    import serial  # import local: las pruebas del parser no necesitan pyserial

    try:
        return serial.serial_for_url(ruta, baudrate=baudios, timeout=0.05)
    except serial.SerialException as error:
        raise ErrorDiagnostico(
            f"No pude abrir el puerto {ruta}: {error}\n"
            "  1. Cierra el 'Monitor Serie' del Arduino IDE (si está abierto ocupa el puerto).\n"
            "  2. Cierra cualquier otro programa que use el Arduino.\n"
            "  3. Desenchufa el USB, espera 5 segundos y vuelve a enchufarlo.\n"
            "  Más detalle: Fase 1 del plan, paso 3."
        ) from error


# --------------------------------------------------------------------------- registro CSV


class RegistroCSV:
    """Escribe una fila por cada cambio de luces y por cada trama inválida.

    Las filas de tramas inválidas llevan `valida=0` y las luces vacías (no se confía
    en ellas). Una fila de trama válida se escribe solo si las luces cambiaron respecto
    de la última trama válida (la primera siempre se escribe).
    """

    def __init__(self, ruta: Path) -> None:
        self._archivo = open(ruta, "w", newline="", encoding="utf-8")  # noqa: SIM115
        self._escritor = csv.writer(self._archivo)
        self._escritor.writerow(COLUMNAS_CSV)
        self._ultimo_estado: int | None = None

    def anotar(self, trama: Trama, instante_ns: int, hora_local: datetime) -> None:
        """Anota la trama si corresponde.

        Args:
            trama: trama recién interpretada.
            instante_ns: `time.monotonic_ns()` de cuando llegó.
            hora_local: hora de pared de ese mismo momento.
        """
        hora = hora_local.isoformat(timespec="milliseconds")
        if not trama.valida:
            self._escritor.writerow([instante_ns, hora, 0, "", "", "", "", "", ""])
        else:
            luces = trama.luces
            if luces.estado == self._ultimo_estado:
                return
            self._ultimo_estado = luces.estado
            self._escritor.writerow(
                [instante_ns, hora, 1]
                + [int(x) for x in (luces.roja, luces.verde, luces.blanca_d0, luces.blanca_d1,
                                     luces.amarilla_d4, luces.amarilla_d5)]
            )
        self._archivo.flush()

    def cerrar(self) -> None:
        self._archivo.close()


@dataclass(frozen=True)
class Resumen:
    """Conteo de toques de un CSV de `--registrar`."""

    rojas: int
    verdes: int
    dobles: int
    invalidas: int


def resumir_csv(ruta: Path) -> Resumen:
    """Cuenta toques rojos, verdes y dobles, y tramas inválidas.

    Un *toque* es un tramo seguido con alguna luz roja o verde encendida, desde que se
    enciende hasta que ambas se apagan. Es doble si en ese tramo se vio la roja y la
    verde (a la vez o una tras otra). Las luces blancas y amarillas no cuentan.

    Args:
        ruta: CSV escrito por `--registrar`.

    Returns:
        El conteo.

    Raises:
        ErrorDiagnostico: si el archivo no existe o no tiene las columnas esperadas.
    """
    try:
        with open(ruta, newline="", encoding="utf-8") as archivo:
            lector = csv.DictReader(archivo)
            if lector.fieldnames is None or not set(COLUMNAS_CSV) <= set(lector.fieldnames):
                raise ErrorDiagnostico(
                    f"{ruta} no parece un CSV de este programa (faltan columnas). "
                    "Debe haberse creado con --registrar."
                )
            filas = list(lector)
    except FileNotFoundError as error:
        raise ErrorDiagnostico(
            f"No existe el archivo {ruta}. Revisa el nombre (¿lo creaste con --registrar?)."
        ) from error

    rojas = verdes = dobles = invalidas = 0
    vio_roja = vio_verde = False

    def cerrar_toque() -> None:
        nonlocal rojas, verdes, dobles, vio_roja, vio_verde
        if vio_roja and vio_verde:
            dobles += 1
        elif vio_roja:
            rojas += 1
        elif vio_verde:
            verdes += 1
        vio_roja = vio_verde = False

    for fila in filas:
        if fila["valida"] != "1":
            invalidas += 1
            continue
        roja, verde = fila["roja"] == "1", fila["verde"] == "1"
        if roja or verde:
            vio_roja |= roja
            vio_verde |= verde
        else:
            cerrar_toque()
    cerrar_toque()  # un toque que sigue encendido al terminar el registro también cuenta
    return Resumen(rojas, verdes, dobles, invalidas)


def texto_resumen(resumen: Resumen) -> str:
    """Formatea el resumen para mostrarlo al autor."""
    return (
        "Resumen del registro:\n"
        f"  Toques ROJOS (izquierda):  {resumen.rojas}\n"
        f"  Toques VERDES (derecha):   {resumen.verdes}\n"
        f"  Dobles (roja y verde):     {resumen.dobles}\n"
        f"  Tramas inválidas:          {resumen.invalidas}"
    )


# --------------------------------------------------------------------------- diagnóstico


class Diagnostico:
    """Lee el puerto, cuenta tramas por segundo y detecta la polaridad.

    El reloj y la función de salida se inyectan para poder probarlo sin hardware ni esperas.

    Args:
        puerto: puerto serie (real o falso).
        reloj_ns: función que da el tiempo en nanosegundos (por defecto `time.monotonic_ns`).
        salida: función para imprimir una línea.
        registro: registro CSV opcional.
        autodetectar_polaridad: si es False nunca envía `I`.
    """

    def __init__(
        self,
        puerto: PuertoSerie,
        reloj_ns: Callable[[], int] = time.monotonic_ns,
        salida: Callable[[str], None] = print,
        registro: RegistroCSV | None = None,
        autodetectar_polaridad: bool = True,
        hora_local: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._puerto = puerto
        self._reloj = reloj_ns
        self._salida = salida
        self._registro = registro
        self._autodetectar = autodetectar_polaridad
        self._hora_local = hora_local
        self._parser = ParserTramas()
        self.total_validas = 0
        self.total_invalidas = 0
        self._reiniciar_segundo()
        # Estado de la autodetección: None = aún no probó; "probando" = envió I; "hecho".
        self._fase_polaridad: str | None = None
        self._segundos_sin_validas = 0
        self._logica_inicial_invertida: bool | None = None
        self._logica_actual_invertida: bool | None = None

    # -- comandos al Arduino

    def enviar_comando(self, comando: str) -> None:
        """Envía un comando de un carácter al firmware (`P`, `A`, `L`, `I`, `?`)."""
        self._puerto.write(comando.encode("ascii"))

    def consultar_estado(self, espera_s: float = 0.5) -> tuple[str, bool] | None:
        """Pregunta al firmware su modo y su lógica (comando `?`).

        Args:
            espera_s: cuánto esperar la respuesta.

        Returns:
            `(modo, invertida)` o `None` si el Arduino no contestó como el programa HW01.
        """
        self._puerto.reset_input_buffer()
        self.enviar_comando("?")
        limite = self._reloj() + int(espera_s * 1e9)
        texto = ""
        while self._reloj() < limite:
            texto += self._puerto.read(max(1, self._puerto.in_waiting)).decode("ascii", "replace")
            encontrado = _PATRON_ESTADO.search(texto)
            if encontrado:
                modo, invertida = encontrado.group(1), encontrado.group(2) == "1"
                self._logica_inicial_invertida = self._logica_actual_invertida = invertida
                return modo, invertida
        return None

    # -- ciclo principal

    def _reiniciar_segundo(self) -> None:
        self._bytes = 0
        self._validas = 0
        self._invalidas = 0
        self._luces_segundo: Luces | None = None

    def procesar(self, datos: bytes) -> None:
        """Procesa bytes recién leídos (actualiza contadores y el registro CSV)."""
        instante = self._reloj()
        self._bytes += len(datos)
        for trama in self._parser.alimentar(datos):
            if trama.valida:
                self._validas += 1
                self.total_validas += 1
                # Se juntan (OR) las luces vistas en el segundo: un toque corto no se pierde.
                previas = self._luces_segundo.byte if self._luces_segundo else 0
                self._luces_segundo = Luces(previas | trama.luces.byte)
            else:
                self._invalidas += 1
                self.total_invalidas += 1
            if self._registro is not None:
                self._registro.anotar(trama, instante, self._hora_local())

    def cerrar_segundo(self) -> str:
        """Cierra el segundo actual: imprime su línea y evalúa la polaridad.

        Returns:
            La línea impresa.
        """
        if self._bytes == 0:
            linea = "SIN DATOS · 0 bytes/s · revisa la conexión (Fase 6/7 del plan)"
        elif self._validas == 0:
            linea = (
                f"SEÑAL RARA · {self._bytes} bytes/s pero 0 tramas válidas · "
                f"{self._invalidas} inválidas · puede ser la polaridad (Fase 7 del plan)"
            )
        else:
            luces = self._luces_segundo.texto() if self._luces_segundo else "?"
            linea = (
                f"OK · {self._validas} tramas/s válidas · {self._invalidas} inválidas · luces: {luces}"
            )
        self._salida(linea)
        self._evaluar_polaridad()
        self._reiniciar_segundo()
        return linea

    def _evaluar_polaridad(self) -> None:
        """Si llegan bytes pero ninguna trama válida durante 3 s, prueba la lógica invertida."""
        if not self._autodetectar or self._fase_polaridad == "hecho":
            return
        if self._validas > 0:
            if self._fase_polaridad == "probando":
                self._anunciar_polaridad_que_funciono()
            self._fase_polaridad = "hecho"
            self._segundos_sin_validas = 0
            return
        if self._bytes == 0:
            self._segundos_sin_validas = 0  # sin bytes no es un problema de polaridad
            return
        self._segundos_sin_validas += 1
        if self._segundos_sin_validas < SEGUNDOS_SIN_TRAMAS_VALIDAS:
            return
        self._segundos_sin_validas = 0
        if self._fase_polaridad is None:
            self._salida(
                "→ Llegan bytes pero ninguna trama válida. Pruebo la lógica INVERTIDA "
                "(le envío 'I' al Arduino)..."
            )
            self.enviar_comando("I")
            if self._logica_actual_invertida is not None:
                self._logica_actual_invertida = not self._logica_actual_invertida
            self._fase_polaridad = "probando"
        else:
            self._salida(
                "✗ Ni la lógica normal ni la invertida dieron tramas válidas. Dejo la lógica como estaba.\n"
                "  Revisa el circuito (Fase 6) y prueba intercambiar los cables de C3 y C4 (Fase 7)."
            )
            self.enviar_comando("I")  # vuelve a la lógica original
            self._fase_polaridad = "hecho"

    def _anunciar_polaridad_que_funciono(self) -> None:
        invertida = self._logica_actual_invertida
        if invertida is None:
            nombre = "la OTRA (la contraria a la de antes)"
        else:
            nombre = "INVERTIDA" if invertida else "NORMAL"
        self._salida(
            f"✓ Funcionó con la lógica {nombre}. Quedó guardada en el Arduino: no hace falta repetir la prueba."
        )

    def ejecutar(self, segundos: float | None = None) -> None:
        """Lee sin parar e imprime una línea por segundo.

        Args:
            segundos: duración; `None` = hasta que se pulse Ctrl+C.

        Raises:
            ErrorDiagnostico: si el Arduino se desconecta durante la lectura.
        """
        import serial

        inicio = self._reloj()
        proximo_corte = inicio + 1_000_000_000
        fin = None if segundos is None else inicio + int(segundos * 1e9)
        while True:
            try:
                datos = self._puerto.read(max(1, self._puerto.in_waiting))
            except (serial.SerialException, OSError) as error:
                raise ErrorDiagnostico(
                    f"Se perdió la conexión con el Arduino ({error}).\n"
                    "  Revisa que el cable USB no se haya movido y vuelve a correr el programa "
                    "(Fase 1 del plan, paso 2)."
                ) from error
            if datos:
                self.procesar(datos)
            ahora = self._reloj()
            while ahora >= proximo_corte:
                self.cerrar_segundo()
                proximo_corte += 1_000_000_000
            if fin is not None and ahora >= fin:
                return


# --------------------------------------------------------------------------- línea de comandos


def _argumentos(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnóstico del puente Favero: muestra en palabras qué llega por el Arduino."
    )
    parser.add_argument("--puerto", help="ruta del puerto (si no se indica, se busca /dev/cu.usbmodem*)")
    parser.add_argument(
        "--modo",
        choices=sorted(MODOS),
        help="pone el Arduino en ese modo al empezar (sin esto, queda en el que esté: puente al reiniciar)",
    )
    parser.add_argument("--segundos", type=float, help="terminar solo tras N segundos (sin esto, Ctrl+C)")
    parser.add_argument("--registrar", metavar="ARCHIVO.csv", help="guarda un CSV con cada cambio de luces")
    parser.add_argument(
        "--resumen", metavar="ARCHIVO.csv", help="cuenta toques rojos, verdes y dobles de un CSV y termina"
    )
    parser.add_argument(
        "--sin-autodeteccion", action="store_true", help="no probar la lógica invertida automáticamente"
    )
    parser.add_argument("--espera-arranque", type=float, default=ESPERA_ARRANQUE_S, help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def principal(argv: list[str] | None = None) -> int:
    """Punto de entrada.

    Args:
        argv: argumentos (por defecto, los de la línea de comandos).

    Returns:
        Código de salida: 0 bien, 1 si hubo un error que se explicó en pantalla.
    """
    args = _argumentos(argv)
    try:
        if args.resumen:
            print(texto_resumen(resumir_csv(Path(args.resumen))))
            return 0
        ruta = args.puerto or elegir_puerto()
        puerto = abrir_puerto(ruta)
        registro = RegistroCSV(Path(args.registrar)) if args.registrar else None
        try:
            # En autoprueba y lazo no entra la señal del Favero: la polaridad no importa.
            probar_polaridad = not args.sin_autodeteccion and args.modo not in ("autoprueba", "lazo")
            diagnostico = Diagnostico(puerto, registro=registro, autodetectar_polaridad=probar_polaridad)
            print(f"Puerto: {ruta}. Esperando al Arduino ({args.espera_arranque:g} s, se reinicia al abrir)...")
            time.sleep(args.espera_arranque)
            if args.modo:
                diagnostico.enviar_comando(MODOS[args.modo])
                print(f"Modo del Arduino: {args.modo}.")
            estado = diagnostico.consultar_estado()
            if estado is None:
                print(
                    "⚠ El Arduino no contestó. Puede que no tenga cargado el programa puente_favero.\n"
                    "  Súbelo de nuevo con el Arduino IDE (LEEME.md, paso 3). Sigo igual, por si acaso."
                )
            else:
                modo, invertida = estado
                print(f"Arduino listo: modo {modo}, lógica {'invertida' if invertida else 'normal'}.")
            print("Leyendo... (Ctrl+C para terminar)\n")
            try:
                diagnostico.ejecutar(args.segundos)
            except KeyboardInterrupt:
                print("\nTerminado por el usuario.")
            print(
                f"\nTotal: {diagnostico.total_validas} tramas válidas, "
                f"{diagnostico.total_invalidas} inválidas."
            )
        finally:
            if registro is not None:
                registro.cerrar()
            puerto.close()
        if args.registrar:
            print(f"Registro guardado en {args.registrar}. Para contar toques: --resumen {args.registrar}")
        return 0
    except ErrorDiagnostico as error:
        print(f"\n✗ {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(principal())
