# UML de SABRE.AI (backend)

Fuentes PlantUML y PNG generados con `java -jar plantuml.jar -tpng -charset UTF-8 docs/uml/*.puml` (requiere Graphviz). Reflejan el código de `main`; solo incluyen componentes existentes.

| Archivo | Contenido |
|---|---|
| `UML1_Clases_Fog` | Fog: API, casos de uso de procesamiento, puertos y adaptadores |
| `UML1b_Clases_Fog_Persistencia` | Fog: unidad de trabajo, repositorios PostgreSQL, consultas, evidencia |
| `UML2_Clases_Cloud` | Cloud: consumidor, clasificador BiLSTM de 6 clases, publicador |
| `UML3_Clases_Edge_Frontend` | Edge y frontend (pantallas, contextos, `fogApi`) |
| `UML4_Secuencia_Carga_Clip` | Carga de clip con persistencia, veredicto de Cloud y decisión del árbitro |
| `UML5_Secuencia_WebRTC` | Flujo WebRTC (no lo usa el frontend actual) |
| `UML6_Actividad_Revision_VAR` | Actividad de la revisión VAR asistida |
