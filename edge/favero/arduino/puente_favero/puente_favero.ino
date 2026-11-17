/*
 * puente_favero.ino · HW01 · Puente Favero -> USB para Arduino UNO
 *
 * Qué hace:
 *   Lee la señal del Favero Full-Arm-05 (2400 baudios, 8N1) por el PIN 8 y la
 *   reenvía por USB a 115200, byte por byte y sin interpretarla. El análisis de
 *   las tramas lo hace el programa de Python (edge/favero/lector.py).
 *
 * Pines:
 *   8  = entrada de la señal del Favero (RX de SoftwareSerial).
 *   9  = TX de SoftwareSerial, sin uso real salvo en el modo LAZO.
 *   0 y 1 NO se usan: están conectados al chip USB.
 *
 * Comandos (de un carácter, por USB; sirven mayúsculas y minúsculas):
 *   P = modo PUENTE (por defecto al encender): reenvía lo que llega al pin 8.
 *   A = modo AUTOPRUEBA: inventa tramas válidas (~24 por segundo). No usa el pin 8.
 *   L = modo LAZO: emite tramas por el pin 9 y las lee por el pin 8 (une 9 con 8).
 *   I = invertir la lógica del pin 8 (SoftwareSerial inverse_logic). Se GUARDA en la
 *       EEPROM del Arduino: queda así aunque lo desenchufes. Cada 'I' alterna.
 *   ? = el Arduino responde una línea de texto con su estado, por ejemplo:
 *       HW01 modo=P invertida=0
 *
 * Luz "L" (la de la placa): parpadea mientras pasan bytes, y se apaga si no hay.
 * Al abrir el puerto desde la Mac el Arduino se reinicia solo y vuelve a PUENTE.
 *
 * Trama del Favero (10 bytes): byte 1 = 0xFF; byte 6 = luces (D2 roja, D3 verde,
 * D0 y D1 blancas, D4 y D5 amarillas); byte 10 = suma de los bytes 1 a 9 módulo 256.
 */

#include <SoftwareSerial.h>
#include <EEPROM.h>

// ---- Configuración -------------------------------------------------------
const uint8_t PIN_RX = 8;
const uint8_t PIN_TX = 9;
const long BAUDIOS_FAVERO = 2400;
const long BAUDIOS_USB = 115200;

// EEPROM: dirección 0 = marca de "ya guardé algo", dirección 1 = lógica invertida (0/1).
const int EEPROM_DIR_MARCA = 0;
const int EEPROM_DIR_INVERTIDA = 1;
const uint8_t EEPROM_MARCA = 0x48;

const uint8_t LARGO_TRAMA = 10;
const uint8_t INDICE_LUCES = 5;  // byte 6
const uint8_t LUZ_ROJA = 1 << 2;
const uint8_t LUZ_VERDE = 1 << 3;

// Autoprueba: 24 tramas por segundo = una cada 41 667 microsegundos.
const unsigned long PERIODO_TRAMA_US = 41667UL;

// Escenario de simulación (se repite): cuántas tramas dura cada paso y qué luces lleva.
// 24 tramas ~ 1 segundo. Ciclo total: 288 tramas ~ 12 segundos.
struct Paso {
  uint16_t tramas;
  uint8_t luces;
};
const Paso ESCENARIO[] = {
  {72, 0},                    // 3 s sin luces
  {24, LUZ_ROJA},             // 1 s roja
  {48, 0},                    // 2 s sin luces
  {24, LUZ_VERDE},            // 1 s verde
  {48, 0},                    // 2 s sin luces
  {24, LUZ_ROJA | LUZ_VERDE}, // 1 s doble
  {48, 0},                    // 2 s sin luces
};
const uint8_t NUM_PASOS = sizeof(ESCENARIO) / sizeof(ESCENARIO[0]);

// ---- Estado --------------------------------------------------------------
SoftwareSerial *favero = NULL;  // solo existe en modo PUENTE
char modo = 'P';
bool invertida = false;

unsigned long ultimaTramaUs = 0;
uint8_t pasoActual = 0;
uint16_t tramasEnPaso = 0;

uint8_t bytesParaLed = 0;
bool ledEncendido = false;
unsigned long ultimoByteMs = 0;

// ---- Utilidades ----------------------------------------------------------

// Arma una trama válida con las luces dadas (bytes sin significado documentado = 0).
void armarTrama(uint8_t luces, uint8_t *trama) {
  uint8_t suma = 0;
  for (uint8_t i = 0; i < LARGO_TRAMA - 1; i++) {
    trama[i] = 0;
  }
  trama[0] = 0xFF;
  trama[INDICE_LUCES] = luces;
  for (uint8_t i = 0; i < LARGO_TRAMA - 1; i++) {
    suma += trama[i];  // uint8_t: se desborda solo, equivale a "módulo 256"
  }
  trama[LARGO_TRAMA - 1] = suma;
}

// Devuelve las luces de la trama que toca enviar según el escenario y avanza el paso.
uint8_t lucesDelEscenario() {
  uint8_t luces = ESCENARIO[pasoActual].luces;
  tramasEnPaso++;
  if (tramasEnPaso >= ESCENARIO[pasoActual].tramas) {
    tramasEnPaso = 0;
    pasoActual = (pasoActual + 1) % NUM_PASOS;
  }
  return luces;
}

// Cada 24 bytes cambia la luz "L": se ve parpadear sin que sea un temblor.
void contarByte() {
  ultimoByteMs = millis();
  bytesParaLed++;
  if (bytesParaLed >= 24) {
    bytesParaLed = 0;
    ledEncendido = !ledEncendido;
    digitalWrite(LED_BUILTIN, ledEncendido ? HIGH : LOW);
  }
}

// Si hace rato que no pasa nada, apaga la luz "L".
void actualizarLed() {
  if (ledEncendido && (millis() - ultimoByteMs) > 300) {
    ledEncendido = false;
    digitalWrite(LED_BUILTIN, LOW);
  }
}

// ---- Modos ---------------------------------------------------------------

// (Re)crea SoftwareSerial con la lógica actual. inverse_logic solo se fija al crearlo.
void iniciarSoftwareSerial() {
  if (favero != NULL) {
    delete favero;  // (el compilador avisa del destructor; es seguro: no hay clases derivadas)
  }
  favero = new SoftwareSerial(PIN_RX, PIN_TX, invertida);
  favero->begin(BAUDIOS_FAVERO);
}

void detenerSoftwareSerial() {
  if (favero != NULL) {
    delete favero;
    favero = NULL;
  }
}

void cambiarModo(char nuevo) {
  modo = nuevo;
  if (modo == 'P') {
    iniciarSoftwareSerial();
  } else {
    // AUTOPRUEBA y LAZO no usan la librería: se libera el pin 8 y se maneja el 9 a mano.
    detenerSoftwareSerial();
    pinMode(PIN_RX, INPUT);
    pinMode(PIN_TX, OUTPUT);
    digitalWrite(PIN_TX, HIGH);  // reposo
  }
  pasoActual = 0;
  tramasEnPaso = 0;
  ultimaTramaUs = micros();
}

void guardarInversion() {
  EEPROM.update(EEPROM_DIR_MARCA, EEPROM_MARCA);
  EEPROM.update(EEPROM_DIR_INVERTIDA, invertida ? 1 : 0);
}

void responderEstado() {
  Serial.print(F("HW01 modo="));
  Serial.print(modo);
  Serial.print(F(" invertida="));
  Serial.println(invertida ? 1 : 0);
}

void leerComandos() {
  while (Serial.available() > 0) {
    char c = toupper(Serial.read());
    if (c == 'P' || c == 'A' || c == 'L') {
      cambiarModo(c);
    } else if (c == 'I') {
      invertida = !invertida;
      guardarInversion();
      if (modo == 'P') {
        iniciarSoftwareSerial();  // reinicia con la lógica nueva
      }
    } else if (c == '?') {
      responderEstado();
    }
    // Cualquier otro carácter (saltos de línea, etc.) se ignora.
  }
}

// PUENTE: lo que llega por el pin 8 sale tal cual por USB.
void puente() {
  while (favero != NULL && favero->available() > 0) {
    Serial.write(favero->read());
    contarByte();
  }
}

// AUTOPRUEBA: una trama válida cada ~41,7 ms.
void autoprueba() {
  if (micros() - ultimaTramaUs >= PERIODO_TRAMA_US) {
    ultimaTramaUs += PERIODO_TRAMA_US;
    uint8_t trama[LARGO_TRAMA];
    armarTrama(lucesDelEscenario(), trama);
    Serial.write(trama, LARGO_TRAMA);
    for (uint8_t i = 0; i < LARGO_TRAMA; i++) {
      contarByte();
    }
  }
}

// LAZO: manda un byte por el pin 9 a 2400 baudios y, en el mismo instante, mira el pin 8.
//
// Por qué no se usa SoftwareSerial aquí: al transmitir apaga las interrupciones y, con
// ellas, su propia recepción; con el cable 9-8 nunca vería sus propios bytes.
// Esta rutina hace las dos cosas a la vez, con interrupciones apagadas ~4 ms por byte.
// Prueba que el cable 9-8 y el pin 8 funcionan; NO ejercita la recepción de SoftwareSerial.
// Devuelve true si la lectura tuvo bit de inicio (0) y de parada (1) correctos.
bool lazoByte(uint8_t enviar, uint8_t *leido) {
  uint8_t d = 0;
  bool ok = true;
  noInterrupts();
  for (uint8_t i = 0; i < 10; i++) {
    // i=0 inicio (0), i=1..8 datos (bit menos significativo primero), i=9 parada (1)
    uint8_t nivel = (i == 0) ? LOW : (i == 9) ? HIGH : ((enviar >> (i - 1)) & 1);
    digitalWrite(PIN_TX, nivel);
    delayMicroseconds(203);                  // mitad del bit
    uint8_t muestra = digitalRead(PIN_RX);   // se lee en medio del bit
    delayMicroseconds(203);                  // resto del bit (1 bit ~ 417 us a 2400)
    if (i == 0 && muestra != LOW) ok = false;
    else if (i == 9 && muestra != HIGH) ok = false;
    else if (i >= 1 && i <= 8) d |= (muestra ? 1 : 0) << (i - 1);
  }
  interrupts();
  *leido = d;
  return ok;
}

void lazo() {
  uint8_t trama[LARGO_TRAMA];
  armarTrama(lucesDelEscenario(), trama);
  for (uint8_t i = 0; i < LARGO_TRAMA; i++) {
    uint8_t leido;
    if (lazoByte(trama[i], &leido)) {
      Serial.write(leido);
      contarByte();
    }
  }
  // Pausa corta con interrupciones activas para que lleguen los comandos USB.
  // La trama dura ~41,7 ms; con la pausa salen ~23 por segundo.
  delayMicroseconds(2000);
}

// ---- Arduino -------------------------------------------------------------

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(BAUDIOS_USB);
  if (EEPROM.read(EEPROM_DIR_MARCA) == EEPROM_MARCA) {
    invertida = EEPROM.read(EEPROM_DIR_INVERTIDA) == 1;
  }
  cambiarModo('P');
}

void loop() {
  leerComandos();
  if (modo == 'P') {
    puente();
  } else if (modo == 'A') {
    autoprueba();
  } else {
    lazo();
  }
  actualizarLed();
}
