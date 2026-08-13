---
status: in-progress
created: 2026-08-13
updated: 2026-08-13
---

# Plan: empaquetado `.vibframe.zip` estándar para productores

## Objetivo

Añadir a `ams-extract` un empaquetador `.vibframe.zip` y congelar un contrato
de comportamiento común para todos los repos generadores. No se diseña un
formato nuevo: la sección *Packaging — `.vibframe.zip`* de
`vibsynth-contracts/docs/VIBFRAME.md` ya es normativa, el validador ya acepta
paquetes y `t8-extract` ofrece la primera implementación productora.

El trabajo común consiste en evitar cuatro variantes de CLI, exclusiones,
atomicidad y nombres. Compartir comportamiento y tests es obligatorio;
compartir una dependencia Python de runtime no lo es.

## Estado de partida

- `vibsynth-contracts` define el envelope y los issue codes `package.*`.
- `vibframe-validate <archivo.vibframe.zip>` valida envelope + dataset.
- `t8-extract extract --zip [FICHERO]` empaqueta el directorio ya escrito.
- `vibframe-viewer serve/report` consume paquetes de forma segura.
- DataWaver ya exporta/importa ZIP y ha alineado las desviaciones principales.
- `ams-extract` sólo escribe directorios; `vibsynth` no tiene aún una interfaz
  productora común documentada.

## Decisiones que se congelan

### El paquete

- Un ZIP contiene exactamente un dataset; `dataset.json` y `machine=*` van en
  la raíz del archivo, sin carpeta envolvente al escribir.
- Se incluyen todos los ficheros del dataset, también `ground-truth/`,
  `analysis/`, `report.html` y extensiones legítimas de raíz.
- No se añade manifiesto de paquete: el dataset ya contiene su identidad y
  procedencia.
- Sólo entradas regulares, paths POSIX relativos normalizados, sin symlinks,
  duplicados, cifrado ni tipos especiales.
- Compresión `deflate` o `store`, ZIP64 habilitado y listado ordenado.
- El directorio fuente se conserva. El paquete es otra salida, no un formato
  alternativo ni una operación destructiva.
- Si el destino cae dentro del dataset, el empaquetador lo excluye a él y a su
  temporal; nunca se autoempaqueta.

### Momento de empaquetado

Empaquetar inmediatamente después de `rbm export` es útil, pero el flujo
desplegado ejecuta luego `t8-mapper` y `vibsynth-machines enrich`. Por ello se
necesitan dos entradas equivalentes:

1. un comando que empaquete **un dataset existente**, después de todos los
   postprocesos;
2. una opción de conveniencia en `rbm export` que invoque el mismo núcleo.

El ZIP representa exactamente el estado del directorio en ese instante. No
ejecuta mapper, enriquecedor ni análisis implícitamente.

### Atomicidad

- Escribir a un temporal hermano del destino y publicar con `os.replace` sólo
  al cerrar el ZIP correctamente.
- Un fallo no destruye un paquete anterior ni deja un fichero final parcial.
- Rechazar que el dataset fuente no exista o no contenga `dataset.json` antes
  de abrir el destino.
- La implementación no sigue symlinks del dataset: falla con un mensaje que
  nombre la entrada no empaquetable.

### Reproducibilidad

El orden y contenido de entradas deben ser deterministas. La reproducibilidad
byte a byte del ZIP sólo se promete si se congela también una política común de
timestamps/permisos; esta decisión se mide en el spike y no se afirma por
accidente. La prueba mínima compara listado, CRC, tamaño y SHA-256 descomprimido
de cada entrada.

## Interfaz común de productores

La fase 0 hará un spike de CLI porque `t8-extract` usa `argparse` y
`ams-extract` usa Typer. El comportamiento, no el truco del parser, queda
fijado:

```text
<productor> package DATASET [--out ARCHIVO.vibframe.zip]
<productor> export/extract ... --zip [ARCHIVO.vibframe.zip]
```

- Sin ruta explícita: `<dataset>.vibframe.zip` junto al directorio.
- Con ruta: se honra exactamente; se crea el directorio padre.
- La salida estructurada del comando incluye `package` con la ruta final.
- Una extensión distinta puede escribirse si el usuario la pide, pero el
  validador informará `package.extension`; la generada por defecto siempre es
  `.vibframe.zip`.

Si Typer no puede expresar de forma robusta una opción con valor opcional, se
elige una pareja común (`--zip` + `--zip-out`) y se migra/documenta también en
los productores existentes. No se publica una excepción sólo para AMS.

## Propiedad del código común

`ams-extract` mantiene por decisión ADR-0009 un contrato runtime vendorizado y
`vibsynth-contracts` sólo en tests/CI. Para no romper esa frontera:

- la **norma** y los casos de conformidad viven en `vibsynth-contracts`;
- el writer de referencia es stdlib y pequeño;
- este repo implementa/vendedoriza ese núcleo con sello de procedencia, o lo
  importa sólo si antes se acepta mediante ADR una dependencia runtime común;
- `vibframe-validate` sigue siendo el oráculo de test, no una llamada necesaria
  para producir el ZIP en runtime.

Antes de copiar código se compara la referencia de `t8-extract`: atomicidad,
symlinks, temporales, reproducibilidad y mensajes. Las mejoras genéricas se
aplican primero a la referencia o se documenta por qué no.

## Fases

### 0. Contrato de productor

- Añadir a la documentación de contracts una tabla de comportamiento CLI y
  filesystem común, sin cambiar el layout VibFrame.
- Crear casos/vectores reutilizables: dataset mínimo, sidecars, Unicode,
  destino interno, symlink, fichero especial, fallo a mitad y ZIP64 simulado.
- Resolver la interfaz CLI portable entre Typer y argparse.

### 1. Núcleo AMS

- `src/ams_extract/export/package.py`: path por defecto, censo seguro y
  escritura atómica.
- Sin `pyarrow`, Pydantic ni contracts en runtime; sólo stdlib.
- Errores tipados para fuente inválida, entrada insegura y publicación fallida.

### 2. CLI

- Comando sobre dataset existente.
- Opción de conveniencia en `rbm export` ejecutada al final de una extracción
  satisfactoria.
- Resumen/log con ruta, entradas, tamaño expandido/comprimido y duración.
- La política de `--strict` del export no se mezcla con la validación del
  paquete.

### 3. Conformidad cruzada

- Validar el paquete AMS con API y CLI de `vibsynth-contracts`.
- Abrir el mismo paquete con `vibframe-viewer report` y comparar el HTML con el
  generado desde el directorio.
- Empaquetar goldens `ams-rbm`, `t8-backup` y `vibsynth` con el writer común y
  comparar contenido.
- Alinear `t8-extract`, `vibsynth` y DataWaver mediante workplans/commits en sus
  repos; este plan no modifica silenciosamente esos checkouts.

### 4. Dataset real

- Empaquetar una extracción pequeña y después Bunge completo.
- Validar sin muestreo de arrays y comprobar que viajan las capas preservadas.
- Medir tiempo, tamaño, ratio y pico de disco; decidir `store` frente a
  `deflate` con datos, manteniéndose dentro de la spec.
- Probar el paquete en Linux, Windows y macOS mediante tests sin depender del
  `.rbm` real.

## Tests

- Path por defecto y destino explícito.
- Raíz canónica, paths POSIX y orden estable.
- Inclusión byte a byte de `ground-truth/` y `analysis/`.
- Rechazo de symlink, especial, path inseguro y dataset sin `dataset.json`.
- Exclusión del propio paquete/temporal.
- ZIP64 habilitado y métodos de compresión permitidos.
- Atomicidad con fallo inyectado.
- Equivalencia de hashes de cada fichero fuente/entrada.
- `vibframe-validate --strict` y consumo por viewer.
- CLI con/sin ruta y no creación del ZIP cuando falla el export.

## Documentación transversal

- `README.md` y `AGENTS.md`: comando común, momento correcto respecto a mapper
  y enriquecedor, y ejemplos de entrega.
- `DECISIONS.md`: ADR de la interfaz productora y de la frontera runtime.
- Workplans 05 y 06: marcar el empaquetado AMS como resuelto.
- `vibsynth-contracts/docs/VIBFRAME.md`/`ECOSYSTEM.md`: distinguir norma de
  paquete, writer de referencia y convención CLI.
- Documentación de t8-extract, vibsynth y DataWaver: mismo nombre, semántica y
  comportamiento.

## Fuera de alcance

- Partir automáticamente un dataset en varios ZIP; un paquete por máquina se
  crea primero como dataset válido de una máquina.
- Cifrado, firma, subida multipart o almacenamiento remoto.
- Ejecutar postprocesos dentro del empaquetador.
- Aceptar un ZIP como destino mutable de `analyze` o `enrich`.

## Criterios de aceptación

1. Directorio y ZIP contienen exactamente los mismos ficheros y bytes.
2. Un fallo no deja paquete parcial ni borra uno anterior.
3. El paquete AMS pasa `vibframe-validate --strict` y lo abren los consumidores
   existentes.
4. La interfaz documentada es común a los productores o existe un plan de
   migración explícito para cada excepción temporal.
5. `ams-extract` no adquiere una dependencia runtime de contracts sin ADR.
6. Las menciones históricas de “ZIP pendiente” quedan cerradas en toda la
   documentación.

## Avance 2026-08-13

Implementadas en este repo las fases 1 y 2: núcleo stdlib con censo sin seguir
symlinks, entradas ordenadas, ZIP64, escritura a temporal hermano y publicación
atómica; `rbm package DATASET [--out ARCHIVO]`; y la pareja portable
`rbm export ... --zip [--zip-out ARCHIVO]`. La salida informa de ruta, número
de entradas, bytes expandidos/empaquetados y duración.

Los tests cubren conformidad estricta, igualdad de bytes, sidecars, Unicode,
destino interno, symlink, fichero especial, nombre inseguro y fallos inyectados
de escritura/publicación; además ejercitan el CLI instalado de contracts y
comparan el HTML del viewer desde el directorio y desde el paquete. Quedan
abiertas las fases transversales: llevar los vectores y la convención CLI a
contracts y los demás productores, probar datasets reales, medir Bunge, y
actualizar la documentación de los demás repos. README/AGENTS, ADR-0022 y las
menciones históricas de este repo quedaron actualizadas en esta sesión.

La prueba real empaquetó el Bunge desplegado, sin modificar RESONINS: **1.761
entradas**, 1.444.234.607 bytes expandidos y 1.295.722.789 bytes de ZIP
(`deflate`) en **44,83 s**. El validador leyó el paquete completo con 347
máquinas, 7 documentos DiagGT y 2 capas de análisis: **0 errores**, los mismos
730 avisos conocidos del directorio y 5 mensajes informativos. Quedan por
medir otros sistemas operativos y comparar la política con los productores
hermanos; la fase de dataset real AMS sí queda cubierta.
