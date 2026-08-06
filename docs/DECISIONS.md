# Architectural Decision Records

> ADRs cortos para las decisiones técnicas no triviales del proyecto.
> Formato libre por entrada: contexto, decisión, alternativas, consecuencias.

Las decisiones consolidadas en el plan original están en
`docs/workplans/01-plan-general.md` §6 («Decisiones técnicas clave»), con el
inventario de comandos en §3 y el testing en §8; aquí se documentan las que
aparecen durante la implementación. Los punteros «§N del PLAN» de los ADRs más
antiguos citan la numeración del plan **por fases** original, reducido a estado
y arquitectura el 2026-06-14.

---

## ADR-0001 — Indexación de registros base-0

- **Fecha**: 2026-05-27
- **Estado**: aceptada (Fase 1)

### Contexto

Eka Siswanto en su _writeup_ del formato RBMware describe los números de
registro como base-1: "record N" significa "el N-ésimo registro contando desde
1", con offset en bytes calculado como `(N − 1) × 512`. Sin embargo, sus
ejemplos numéricos encajan mejor con base-0 (`N × 512`). El PLAN §4.1 marcó
esta ambigüedad como pendiente de resolver experimentalmente en Fase 1.

### Decisión

Adoptar **indexación base-0** en todo el código:

- `RbmReader.read_record(n)` interpreta `n` como índice base-0, con
  `offset = n × 512` y `n ∈ [0, record_count)`.
- El record 0 contiene la cabecera global.
- Cualquier u32 leído como "puntero a record" del fichero se interpreta
  también como base-0.

### Cómo se validó

Sobre `BUNGE CARTAGENA marzo 2.0.rbm` (1 857 595 904 bytes, 3 628 117 records):

1. El campo en `0xDC` del record 0 contiene `0x46 = 70`.
2. Interpretado base-0, el record 70 está en `offset = 70 × 512 = 0x8C00`.
3. Volcado del record 70 base-0 (primeros 256 bytes), comienza con cinco
   nombres ASCII de 32 bytes cada uno, padded con espacios:

   ```
   0000  46 55 4c 4c 2d 46 41 54 ...   |FULL-FAT        |
   0020  50 41 52 51 55 45 20 54 ...   |PARQUE TANQUES  |
   0040  4f 42 53 4f 4c 45 54 4f ...   |OBSOLETOS       |
   0060  53 45 52 56 49 43 49 4f ...   |SERVICIOS       |
   0080  4f 53 4d 4f 53 49 53 20 ...   |OSMOSIS         |
   ```

   Es exactamente la forma esperada de un "area chain record" (lista de
   nombres de área en slots de 32 bytes), y los nombres son plausibles para
   una planta industrial.
4. Interpretado base-1 (record 70 → `offset = 69 × 512 = 0x8A00`), el record
   contiene un tag de 4 chars + tabla de punteros + dos nombres de área al
   final — estructura mucho más compleja y no encaja con "lista de áreas".

### Alternativas consideradas

- **Base-1** (siguiendo literalmente a Eka). Descartada: los ejemplos
  numéricos del propio Eka encajan con base-0, y la verificación empírica
  contra el fichero real apunta a base-0.
- **Convención dual configurable**. Descartada por complejidad innecesaria:
  todos los `.rbm` que examinemos parecen seguir la misma convención y no
  hay valor en abstraerla.

### Consecuencias

- Cualquier conversión a/desde la documentación de Eka requiere restar 1 a
  sus números de registro.
- Si en el futuro aparece un `.rbm` con indexación distinta (versión más
  antigua del formato, otro vendor), habrá que detectarlo y aislar la lógica
  de indexación en `RbmReader`.

---

## ADR-0002 — Áreas: dos punteros en el header y heurística "stop after first gap"

- **Fecha**: 2026-05-27
- **Estado**: aceptada (Fase 2)

### Contexto

PLAN §4.3 (basado en Eka) describe las áreas como **una cadena enlazada**
arrancando en el puntero del header. En `BUNGE` esperábamos `area_chain_first_record = 70 → 71 → 72 → …` con los nombres distribuidos por una lista de records.

La realidad observada es diferente:

- **Record 70 (apuntado por 0xDC)**: layout "simple list". 5 nombres de área
  en slots 0..4 (FULL-FAT, PARQUE TANQUES, OBSOLETOS, SERVICIOS, OSMOSIS).
  Los slots 5..11 están vacíos. Los slots 12 y 13 contienen listas concatenadas de **códigos cortos** de 4 chars (`"CI  EXT DEP MAR NAV PAS PEL PRE"`,
  `"REF CAL FULLPTANOBS SRV OSM"`).
- **Record 69 (apuntado por 0xE4 — un segundo puntero en el header)**:
  layout "prefixed list". Un preámbulo binario en 0x00..0xBF (timestamp +
  tag `gits` + tabla de u32) y 10 nombres de área en slots 6..15
  (CONTRA INCENDIOS, EXTRACCION, …, CALDERAS).
- **Records 71..77**: vacíos con tag `gdwn` — no son continuación de la
  cadena. El "siguiente puntero" clásico no existe entre records de área.

Total real verificado contra la UI de AMS (capturas del usuario):
**15 áreas** = 10 (record 69) + 5 (record 70). El PLAN decía "14 áreas"
basado en información imprecisa; el dato correcto es 15.

### Decisión

1. **El header tiene DOS punteros a áreas, no uno**: el primario en `0xDC`
   y el secundario en `0xE4`. El walker (`walk_areas`) sigue ambos.
   Records ya visitados se dedupean por número.
2. **No hay cadena enlazada entre records de área**. Cada record contiene
   un set autocontenido de nombres de área.
3. **Heurística de detección de slots** (en `_iter_area_slots`):
   - Recorrer los 16 slots de 32 bytes del record en orden.
   - Antes de encontrar el primer nombre, saltarse los slots que no parecen
     nombres (esto absorbe el preámbulo binario del layout "prefixed list").
   - Tras emitir el primer nombre, parar en el primer slot que **no** parece
     nombre (esto evita capturar las listas de códigos cortos de los slots
     12-13 del layout "simple list" como áreas falsas).
4. **Aceptar cp1252 en el filtro de nombres**: el filtro acepta cualquier
   byte ``>= 0x20`` excepto DEL. Esto fue necesario para detectar
   `IMPULSIÓN DE MAR` (contiene `0xD3 = 'Ó'` en cp1252).
5. **Códigos cortos derivados, no extraídos**: aunque sabemos que la base
   almacena los códigos cortos en los slots 12-13 del record 70, el formato
   exacto (4-char fixed width concatenado) no permite emparejarlos
   trivialmente con los nombres del record 69. Phase 2 deriva `short_code`
   sanitizando el `long_name`; Phase 2b o posterior podrá leer los códigos
   nativos si es necesario.

### Cómo se validó

- Sobre `BUNGE`: `rbm tree` produce exactamente las 15 áreas visibles en
  el árbol de AMS Suite Machinery Health Manager (verificado por screenshot
  del navegador AMS).
- Test de integración `test_real_file_yields_fifteen_areas` compara la
  lista completa palabra por palabra.

### Alternativas consideradas

- **Seguir una cadena enlazada clásica** desde 0xDC con `--at-offset` a
  determinar. Descartada porque records 71..77 son `gdwn` vacíos, no
  continuación.
- **Asumir layout único** (solo "simple list"). Descartada porque dejaría
  fuera 10 de 15 áreas.
- **Hardcodear "salta slots 12-13" sin heurística general**. Descartada por
  ser frágil ante otros `.rbm` con otra distribución.

### Consecuencias

- Cualquier `.rbm` que use una cadena enlazada real entre records de área
  romperá el walker. Si aparece, se detectaría rápido: el conteo de áreas
  sería claramente menor de lo esperado.
- La heurística "parar en el primer gap tras emitir un nombre" puede
  truncar la lista si hay un nombre legítimamente seguido de un slot vacío
  (poco probable en la práctica). Si se observa, hay que añadir una regla
  más estricta para los gaps internos.

---

## ADR-0003 — Cadena Area→Equipo→Punto y punteros internos "+1 encoded"

- **Fecha**: 2026-05-28
- **Estado**: aceptada (Fase 2b)

### Contexto

El PLAN.md original (§4.3) describía la jerarquía como
`Area → gdts → Equipment → gdcm → gipm → mpdo`, basándose en la
documentación de Eka. La realidad encontrada en `BUNGE` resultó tener
una capa intermedia adicional (`gicm`), una convención distinta para
los punteros internos a los de la cabecera, y encadenamiento por
linked-list para áreas con más de 12 equipos. Conviene fijar el modelo
en una única ADR antes de que la implementación se ramifique.

### Decisión

**Cadena canónica** desde una `Area` hasta un `Point`:

```
Area
  └─ gdts record           (uno por área; localizado vía la tabla de
                            punteros del record "prefix-list" de áreas,
                            offset 0x10..0x4F, decode_inner_pointer)
       └─ gicm record      (chunks de hasta 12 equipos; primero en
                            gdts.0x18; lista enlazada vía gicm.0x0C
                            para áreas con > 12 equipos)
            └─ gdcm record (uno por equipo; punteros en gicm.0x10..0x3F;
                            nombre del equipo en slot de 28 bytes en
                            gicm.0xB0 + i*28)
                 └─ gipm record  (uno por equipo; gdcm.0x14)
                      └─ vdpm record   (uno por punto; tabla de punteros
                                        en gipm.0x1C0..0x1FF,
                                        decode_inner_pointer)
                          → long_name en vdpm.0x18 (32 bytes cp1252
                            padded)
```

**Convención de punteros**:

- Los **dos punteros de cabecera** (offsets `0xDC` y `0xE4` del record 0)
  son **base-0** directos. ADR-0001 ya lo había fijado.
- **Todos los punteros que viven dentro de records tipados** (gdts, gicm,
  gdcm, gipm, vdpm, y la propia tabla 0x10 del area prefix-list) se
  almacenan con un offset de **+1** sobre el número de record base-0,
  reservando `0` como sentinela de fin-de-lista / puntero nulo. El helper
  `ams_extract.reader.decode_inner_pointer` aplica la conversión.

**Encadenamiento de gicm**: una `gicm` apunta a la siguiente del chunk
vía u32 LE en offset `0x0C` (mismo encoding "+1", `0` = última). El
walker recorre la lista, dedupando records ya visitados para tolerar
ficheros corruptos.

### Cómo se validó

Sobre `BUNGE CARTAGENA marzo 2.0.rbm` (3 628 117 records):

1. **Pointer #0 en rec 69 = 298** → record 297 base-1 → tag `gdts` ✓
   (record 297 base-0 está vacío; base-1 acierta).
2. **gdts 297 offset 0x18 = 1533** → record 1532 base-1 → tag `gicm`,
   con 4 nombres "Bomba Centrifuga PM-0CI/{1,2,3,JO}" — exactamente los
   equipos esperados para CONTRA INCENDIOS.
3. **gicm 1532 offsets 0x10..0x1C** → 4 punteros (+1 encoded) →
   records 300, 1534, 2766, 3998 base-0 → todos `gdcm` ✓.
4. **gdcm 300 offset 0x14 = 432** → record 431 base-0 → `gipm`. Su tabla
   0x1C0+ contiene 15 punteros (terminados por 0), apuntando todos a
   records con tag `vdpm` cuyo offset 0x18 contiene nombres como
   "MOTOR LOA HORIZONTAL", "BOMBA LA VERTICAL PEAKVUE", … los puntos
   típicos de una bomba centrífuga.
5. **gicm chain**: EXTRACCION tiene 36 equipos. Su primer gicm (record
   4949) tiene 12 nombres y `0x0C = 134319` → siguiente gicm. La cadena
   acaba en `0x0C = 0`. El campo `0x1C` del gdts (259105 base-1)
   coincide con el ÚLTIMO gicm de la cadena, lo que confirma la
   interpretación "first / last" para gdts 0x18 / 0x1C.
6. **Recuento sobre BUNGE**: `walk_hierarchy` entrega 15 áreas,
   252 equipos, 3795 puntos totales, **869 puntos con "PEAKVUE" en el
   nombre** — dentro del ±5% de la cifra "~895 PEAKVUE" que aparecía en
   el plan original (DoD de Fase 2b cumplida).
7. **`rbm-dev scan --tags` sobre BUNGE**: aparecen 6141 records `vdpm`
   en disco, pero el walker sólo alcanza 3795. La diferencia (~2346)
   corresponde a plantillas de análisis (DEP-M, IBL-REACC S1…) y a
   versiones históricas de puntos editados, no a fallo del walker.

### Alternativas consideradas

- **Una única convención de indexación (base-0 o base-1) para todo el
  fichero**: descartada empíricamente — la combinación
  (cabecera base-0, internos +1-encoded) es la que pasa todos los
  smoke-tests contra `BUNGE`. Forzar una sola convención implicaría
  asumir que el encoding "+1" es realmente "base-1 sin sentinela", lo
  que rompería en gicm/gipm donde el `0` SÍ es sentinela.
- **Modelar `Equipment.record_num = gicm_record + slot_index`**:
  descartada por inestable — cambia si el gicm se rebalancea. Usamos el
  `gdcm_record` como identidad estable del equipo.
- **Filtrar plantillas del output**: aplazada — requiere detectar el
  marker que distingue equipo real de plantilla (todavía no
  identificado). Fase 2b emite todo lo alcanzable desde la jerarquía de
  áreas; las plantillas, al no estar enlazadas vía un área, no llegan al
  output.

### Consecuencias

- El walker es robusto a áreas con cualquier número de equipos sin
  cambios al schema.
- Cualquier nuevo tipo de record cuyas tablas internas usen el mismo
  encoding +1 puede reutilizar `decode_inner_pointer` sin duplicar
  lógica.
- Si en el futuro descubrimos otro caso donde un puntero interno NO usa
  el +1 (por ejemplo, un offset en bytes en vez de record_num), habrá
  que aislarlo y nombrarlo aparte para no contaminar la convención
  actual.

---

## ADR-0004 — Un `gicm` lógico tiene 20 slots y usa un registro de continuación

- **Fecha**: 2026-05-28
- **Estado**: aceptada (post-Fase 2b, fix de cuentas)

### Contexto

Al cotejar capturas de AMS contra el `tree.json` extraído de
`BUNGE CARTAGENA marzo 2.0.rbm`, DEPURADORA en AMS muestra **28 equipos**
mientras el walker emitía 20. Los 8 que faltaban (`PM-501`, `PM-700`,
`PM-701`, `PM-4500`, `PM-5400`, `PM-5500`, `PM-5502`, `RAS-500`) son
contiguos en orden de AMS, justo entre el bloque que sí extraíamos
(AG-100 … PM-500) y el siguiente (RAS-5500 …).

La ADR-0003 había documentado el `gicm` con la regla "hasta 12 slots por
chunk", derivada de la observación de que en `0xB0 + 12 × 28 = 0x200`
se rellenaba exactamente el record físico de 512 bytes. Esa regla era
correcta para los chunks pequeños observados en Fase 2b pero incompleta:
chunk 0 de DEP tiene 20 punteros vivos en la tabla `0x10`–`0x5F`, no 12,
y los nombres 13-20 viven en el registro físico inmediatamente siguiente.

El error se reprodujo a escala con `rbm-dev` + un script ad-hoc: 5 de
las 15 áreas tenían chunks de más de 12 equipos (EXTRACCION 53,
DEPURADORA 28, NAVES 18, PREPARACION 87, REFINERIA 90). En total
faltaban **91 equipos (26%)** y los puntos asociados.

### Decisión

Un chunk lógico `gicm` se modela como un **par de registros físicos**:

- **Registro principal** (con tag `gicm`): hasta 20 punteros `gdcm` en
  `0x10`–`0x5F` y los primeros 12 nombres en `0xB0`–`0x1FF`.
- **Registro de continuación** (sin tag, en `gicm_record + 1`, sólo si
  el chunk tiene > 12 equipos): nombres 13-20 en `0x000`–`0x0DF` y los
  20 short codes nativos en `0x0E0`–`0x1A7`.

El parser de slots (`_parse_single_gicm_slots`) lee el principal,
detecta si hay > 12 punteros vivos y, si los hay, abre el siguiente
record físico para los nombres restantes. La cadena entre chunks
lógicos sigue siendo el puntero `gicm.0x0C` → next gicm.

### Alternativas consideradas

- **Asumir 12 slots por chunk y leer más records "next" hasta cubrir
  todo**: descartada — la cadena `gicm.0x0C` apunta al siguiente chunk
  lógico, no a la continuación. Confundir ambos haría que el chunk
  siguiente fuese mal-interpretado como continuación del primero.
- **Definir el registro de continuación como un nuevo tag de record
  con su propia estructura**: descartada — no tiene tag en disco. Se
  modela como un bloque mudo cuyo offset depende exclusivamente del
  registro principal.
- **Detectar continuación por contenido (presencia de espacios al
  inicio, etc.) en vez de por `len(pointers) > 12`**: descartada por
  ambigüedad — el contenido del bloque siguiente es legítimo nombre de
  equipo para chunks grandes y bytes basura para chunks pequeños; sólo
  el conteo de punteros distingue uno de otro de forma fiable.

### Consecuencias

- Los conteos por área cuadran con AMS (verificado contra capturas para
  DEPURADORA; locked en `test_real_file_equipment_count_per_area`).
- El layout `0x40`–`0x5F` que ADR-0003 anotaba como "reservado" eran
  punteros válidos (slots 12-19); ese error queda corregido aquí.
- Los short codes nativos (`AG-100`, `PM-501`, …) están ahora a un
  parser de distancia — viven en `continuation[0xE0:]` con stride 10
  bytes. Pendiente de aprovechar: hoy es la línea «short codes nativos» de
  `docs/workplans/01-plan-general.md` §7 («Trabajo restante / opcional»),
  antes §4.6 del plan por fases.
- Esquema JSON bumpeado: `schema_version = 3`, `phase =
  "phase-2b-equipment-count-fix"`. Consumidores que viesen v2 detectan
  fácilmente que están leyendo un extracto incompleto y deben
  re-procesar.

---

## ADR-0005 — Reconstrucción y calibración del espectro FFT (banda baja + cadena + escala única por unidad)

- **Fecha**: 2026-05-30
- **Estado**: aceptada (cierre funcional de Fase 4)

### Contexto

Durante meses la calibración de amplitudes del FFT se registró como una
"discrepancia estructural irrecuperable" (`FORMAT.md §5.6`): los ratios
AMS/decoded parecían no constantes (16 a 2330) y el pico dominante de AMS
(M1H 14.68 Hz) aparecía "ausente" del array decodificado. Se llegó a
documentar como no recuperable. La hipótesis "AMS reconstruye la FFT desde
la waveform" ya se había descartado en sub-5a (488 muestras / 0.19 s no
dan 1600 líneas a 0.625 Hz/bin).

El error real era doble: (1) comparábamos un espectro **incompleto**
—sólo la cadena `vcps`, que arranca en la línea 78— contra el gold, que
incluye las líneas 0–77 (1X/2X de giro, donde suele caer el pico mayor);
y (2) no se aplicaba ninguna escala.

### Decisión

**Reconstrucción.** El espectro de display de AMS se ensambla en dos piezas:

1. **Bins 0..77 (0–48.75 Hz)** — 78 float32 contiguos en la **cola del
   propio record `vdps`**, offsets `0xC8..0x1FF` (`(0x200-0xC8)/4 = 78`).
2. **Bins 78..1663** — la cadena `vcps` (≈1586 floats).

`espectro = concat(vdps[0xC8:0x200], cadena_vcps)` truncado a `n_lines`
(1600). Frecuencia del bin `i` = `i · Fmax / n_lines` (sin offset una vez
antepuesta la banda baja).

**Calibración — una escala constante por tipo de unidad**, no por-muestra:

- **Velocidad** (units crudas `plg/segs` / `in/sec` / `pul/sg`):
  `mm/s = 48.5 · raw` (`VELOCITY_SCALE_MM_S`). Pooled median 48.8 sobre 72
  picos; ≈ 25.4 pulgadas→mm × ~1.9 ventana/normalización. Valores tipo PC.
- **Aceleración** (units `G's`; puntos PeakVue fmax 1000 + alta frecuencia
  fmax 6000): `G's = 1.30 · raw` (`ACCEL_SCALE_G`). Sin conversión de unidad;
  valores RMS (de ahí que el factor difiera del de velocidad). El mismo
  ×1.30 vale para PeakVue y HF → es una constante de digitización del
  formato, independiente de Fmax.

Implementado en `records/sample.py` (`read_vdps_low_band`,
`assemble_spectrum`, `VELOCITY_SCALE_MM_S`, `ACCEL_SCALE_G`) y aplicado en
`tree.walk_spectra`. Las units se emiten ya calibradas (`mm/s`, `G's`).

### Cómo se validó

- **Test de nulidad del offset**: barriendo offsets 0..160 bins al
  anteponer la banda baja, **78 es el único** con logcorr > 0.90 contra el
  gold. Confirma que la cadena empieza exactamente en la línea 78.
- **Velocidad, 3 máquinas / 3 RPM** (gold = "Lista de Picos" de AMS):
  AG-100 M1H (1455 rpm, logcorr +0.999, escala 48.0), PM-6901-A M1H
  (3000 rpm, +0.999, 48.7), AR-1211 M1H (1500 rpm, +0.998, 47.9). Picos
  por pico ±5–10%.
- **Aceleración, dos tipos**: PM-6901-A M2P/B1P (PeakVue, fmax 1000,
  median 0.998, logcorr +0.995) y PM-6901-B M1F (alta frecuencia,
  fmax 6000, median 1.009, 24/24 picos ±10%, logcorr +0.998).

Registro completo en `docs/VERIFICATION.md §5`.

### Alternativas consideradas

- **"FFT reconstruida desde la waveform"**: descartada en sub-5a — la
  waveform almacenada no tiene resolución para 1600 líneas a 0.625 Hz/bin.
- **Escala por-muestra (factor en algún offset del `vdps`, análogo a
  `vdfw.0x28` de la waveform)**: investigada (script throwaway
  `scripts/investigate_fft_calibration.py`, que también barrió cadenas
  `vcps` vecinas y canales `pdcd` alternativos) y descartada — una sola
  constante por unidad reproduce el gold en todas las máquinas probadas.
- **Marcar la calibración como no recuperable**: era la conclusión previa,
  refutada al detectar la banda baja faltante.

### Consecuencias

- El FFT deja de tener deuda de calibración: `rbm extract` y `rbm export`
  emiten mm/s (velocidad) y G's (aceleración) directamente.
- AMS muestra para puntos de velocidad una "aceleración" derivada
  (`a = v·2πf`, ratio constante 0.716 ≈ 1/√2 RMS-vs-pico) que **no** está
  almacenada; no la emitimos (sería una columna derivada de la velocidad).
- Si aparece un `.rbm` con otra digitización, las escalas 48.5 / 1.30
  podrían no transferir; están aisladas como constantes en `sample.py`
  para recalibrar con un gold nuevo.

---

## ADR-0006 — Layout de las tendencias `vddt` (slots de 41 B, timestamp "del siguiente")

- **Fecha**: 2026-05-30
- **Estado**: aceptada (Fase 7)

### Contexto

Los records `vddt` (apuntados por `pdcd.0x3C`/`0x40`) almacenan la
tendencia de **Valores Globales** (overall RMS velocity) + bandas con
nombre que AMS pinta como serie temporal de años. La estructura de cadena
ya se conocía (chain por `0x10`, rango de fechas en `0x18`/`0x1C`), y la
escala del overall también (in/s × 25.4 → mm/s). Lo que llevaba meses sin
resolver era el **layout interno**: cómo se indexan valor y timestamp por
muestra. Intentos previos con stride fijo de 36 B fallaban, los timestamps
parecían "off-by-one" respecto al valor, y `0x24 = 7` no cuadraba como
número de muestras.

El bloqueo era falta de gold suficiente. El 2026-05-30 el usuario aportó la
tabla PLOTDATA "Valore Globale" completa de M1H AG-100 (47 filas
fecha→valor), que permitió fuerza-bruta-alinear el layout.

### Decisión

Un `vddt` es una secuencia de **slots de 41 bytes** (stride `0x29`), el
primero en offset `0x2F`, cada uno con marcador `d3 fa ff 00`:

- `+0x00` marcador `d3 fa ff 00`
- `+0x04` float32 **overall** (Valores Globales); `mm/s = float × 25.4`
- `+0x08` 7 × float32 — bandas (etiquetado pendiente)
- `+0x24` u32 — Unix timestamp de la muestra **siguiente**

11 slots por record (el último de la cadena, menos). Se descartan
marcadores espurios antes de `0x2F` y slots con overall fuera de rango.

**Regla de fechas** (clave): el timestamp de un slot apunta a la muestra
siguiente, no a la suya:

```
fecha[0] = vddt.0x18 (d0)               # primera muestra del record
fecha[k] = slot[k-1].+0x24  (k ≥ 1)     # ts almacenado en el slot anterior
```

La primera muestra de cada record toma su fecha del `d0` de ese record;
el `+0x24` del último slot es `0`.

### Cómo se validó

Decodificados 62 puntos para M1H AG-100 con la regla anterior; los
primeros 47 coinciden **exacto** (fecha + valor) con el gold de AMS,
incluido el duplicado del 13-jul-2017 (6.01 y 36.43 mm/s el mismo día).
Anclas: `slot@0x58 +0x04 = 0.6038 → 15.34 mm/s` (20-abr-2017) y
`slot@0xFC +0x04 = 1.4341 → 36.43 mm/s` (13-jul-2017, pico). Script de
cracking: `scripts/investigate_vddt_layout.py`.

### Alternativas consideradas

- **Stride fijo de 36 B sin marcador**: descartada — parseaba unas muestras
  y rompía otras; el stride real es 41 B y el marcador `d3 fa ff 00` lo
  delimita de forma fiable.
- **Timestamp del slot = fecha de su propio valor**: descartada — produce
  un desfase sistemático de una muestra contra el gold. El ts es "del
  siguiente"; la primera fecha viene de `d0`.
- **`0x24` = número de muestras**: descartada — vale 7 constante mientras
  hay 11 slots; es nº de columnas/bandas, no de muestras.
- **Implementar a ciegas sin gold** (§7.4 del PLAN): se evitó a propósito;
  se esperó a tener la tabla gold para no emitir tendencias mal alineadas.

### Consecuencias

- La tendencia de Valores Globales es ahora extraíble y verificada.
- Implementado (`records/trend.py`, `tree.walk_trends`, `models.Trend`,
  export `__trend.parquet` una fila por lectura, CLI `--type/--types trend`).

### Actualización (misma fecha, tras cotejar más puntos)

Lo de "slots de 41 B con marcador `d3 fa ff 00`" era una sobre-generalización
de AG-100. Corregido:

- Los 4 bytes iniciales del slot son **flags por slot**, no un marcador fijo
  (el `d3 fa ff 00` es dato de AG-100; otros puntos muestran `fe ff ff 00`…).
- El stride es **`13 + band_count·4`** (band_count en `0x24`), no 41 fijo: 41
  para 7 bandas, 29 para 4, 17 para 1. Un mismo punto mezcla records con
  distinto `band_count` a lo largo del tiempo; `band_count` **no** discrimina
  la unidad.
- La **unidad** se decide por el espectro del punto (`vdps.0x78`): velocidad
  → mm/s (×25.4, validado); aceleración → G's (se salta de momento, escala
  del overall sin gold, §7.4).
- **Bandas etiquetadas** (template velocidad, 62/62 vs PLOTDATA por banda):
  col0 = Mp Wave (**G's**), col1 SUBSINCRONO, col2 DESEQUILIBRIO, col3
  DESALINEACION, col4 HOLGURAS, col5 11-40X RPM (mm/s), col6 1-20 KHz (sin
  confirmar). Unidades mixtas → emitir las bandas queda pendiente.

### Nota 2026-08-05 — los tres pendientes de esta entrada están resueltos

- **Emitir las bandas** (unidades mixtas): hecho en **ADR-0010** (2026-07-18),
  como métricas VibFrame propias (`band_<slug>__<punto>` en `trends.parquet`
  con descriptor en `metrics.parquet`); las etiquetas dejaron de ser fijas en
  **ADR-0012** (se resuelven contra la plantilla `pdpa` del punto).
- **Tendencias de aceleración** («se salta de momento, escala del overall sin
  gold»): emitidas en **ADR-0014** (2026-07-20), overall crudo en G's, con el
  gold de DT-0070 M1P (147/147).
- **Columna «1 - 20 KHz» sin confirmar**: emitida en **ADR-0013**
  (2026-07-19), cruda en g, con la captura «RMS Aceleración» como gold.

Las referencias «§7.4 del PLAN» apuntan al plan por fases original, hoy
reducido (ver cabecera de este fichero).

---

## ADR-0007 — Export de tendencias (una fila por lectura) y unidades de velocidad

- **Fecha**: 2026-05-31
- **Estado**: aceptada

### Contexto

Al cablear `vddt` (tendencias) al export había que elegir formato; y la
validación del export completo destapó 503 waveforms de velocidad emitidas
en pulgadas/segundo, inconsistentes con el FFT/trend (mm/s).

### Decisión

1. **Tendencias: una fila por lectura** (no una fila por serie con arrays).
   Cada lectura del `vddt` = una fila `(timestamp_utc, overall, units)` en
   `…__trend.parquet`, igual que cualquier otra muestra → filtrable por fecha
   y join 1:1 con `manifest.parquet` (columna nullable `overall`). El
   `sample_id` lleva el índice de lectura como discriminador.
2. **Unidades de velocidad unificadas a mm/s**. Las waveforms de velocidad
   (units `plg/segs`/`in/sec`) se convierten **×25.4 → mm/s** en
   `walk_waveforms`, igual que el FFT y el trend de velocidad. Aceleración
   (G's) se deja tal cual. Motivo: una migración no debe mezclar in/s y mm/s
   para la misma magnitud física.
3. **Solo se emiten tendencias de velocidad**. El layout `vddt` decodifica
   también aceleración (PeakVue/HF), pero su escala de overall no está
   validada contra gold, así que se salta con log (no emitir lo no validado).

### Consecuencias

- `rbm export --types …,trend` y `rbm extract --type trend` producen mm/s.
- Tras el fix, 0 muestras salen en in/s; el export completo (274.478
  FFT+wv) se validó end-to-end (ver `VERIFICATION.md`).
- Pendiente: emitir bandas con nombre (unidades mixtas) y tendencias de
  aceleración cuando haya gold.

### Nota 2026-08-05 — el pendiente está resuelto

Las bandas con nombre se emiten desde **ADR-0010** (2026-07-18) y las
tendencias de aceleración desde **ADR-0014** (2026-07-20, gold de DT-0070 M1P,
147/147): el punto 3 de la decisión —«solo se emiten tendencias de
velocidad»— ya no describe el comportamiento. Lo que sí sigue en pie es el
criterio que lo justificaba (no emitir lo no validado): los 322 puntos con
cadena `vddt` pero sin espectro FFT, cuya unidad no se puede determinar, se
siguen saltando.

---

## ADR-0008 — Viewer interactivo: render bajo demanda y `rbm serve` directo del `.rbm`

- **Fecha**: 2026-06-13
- **Estado**: aceptada

### Contexto

Tras tener el export validado faltaba una forma de **inspeccionar** la base sin
abrir AMS ni cargar los Parquet en otra herramienta. Las opciones eran
pregenerar PNG de cada muestra (inviable: 274.478+ gráficas), exportar siempre a
Parquet antes de mirar, o renderizar al vuelo. Además el inventario (`rbm
report`) y el viewer (`rbm serve`) comparten la misma reconstrucción de
jerarquía/muestras que el export.

### Decisión

1. **Nada se pregenera**. Las gráficas (FFT/onda/tendencia) se renderizan
   **bajo demanda** cuando el usuario abre un punto, reutilizando los mismos
   plotters del export (`spectrum_plot`/`waveform_plot`/`trend_plot`), que
   pueden escribir a un path o a un buffer en memoria.
2. **`rbm serve` autodetecta el backend** según el argumento: un **`.rbm`**
   renderiza directo de la BD (arranque solo con la jerarquía área→máquina;
   puntos/muestras cargados lazy al drillear, cada plot al vuelo desde el
   `.rbm`) o un **dataset exportado** (lee `manifest.parquet`). No hace falta
   `export` para mirar una base.
3. **`rbm report` lee el `.rbm` directamente** y escribe un HTML autocontenido
   (árbol localizaciones→máquinas con conteos + fechas por tipo y filtro de
   máquinas); el mismo `report.html` se deja en el dataset por `rbm export` y
   sirve de base al viewer.
4. **Solo loopback por defecto** (`--host` para exponer); tema claro.

### Consecuencias

- Inspección instantánea de una base de 1,8 GiB sin paso de export ni PNG en
  disco; arranque acotado a la jerarquía gracias a la carga lazy.
- `report.html`, viewer y export comparten una sola ruta de reconstrucción y
  de plotting (menos divergencia, una sola cosa que validar).
- Capa de presentación pura: no toca el formato binario ni la calibración, así
  que `FORMAT.md`/`VERIFICATION.md` no cambian.

---

## ADR-0009 — `rbm export` escribe VibFrame sin dependencia de vibsynth

- **Fecha**: 2026-07-09
- **Estado**: aceptada

### Contexto

El ecosistema `vibsynth` consolidó en `vibsynth-contracts.dataset` un formato
estándar de intercambio de vibración: `dataset.json` en raíz y un directorio
`machine=<id>` por asset con `machine.json`, `metrics.parquet`,
`spectra.parquet`, `waves.parquet` y `trends.parquet`. `ams-extract` debe
producir ese formato, pero no debe depender en runtime del monorepo
`vibsynth`.

### Decisión

1. **Sustituir el export masivo**. `rbm export` deja de escribir
   `manifest.parquet` + `samples/` y pasa a escribir VibFrame. El formato
   anterior queda obsoleto.
2. **Contrato local mínimo**. Se copian localmente las constantes de layout y
   columnas necesarias desde `vibsynth-contracts.dataset`, con comentario de
   procedencia. No se añade dependencia Python a `vibsynth-contracts`.
3. **Carpetas por asset**. El `Equipment` de AMS se modela como asset/machine:
   `machine=<equipment.short_code>`. El dispositivo de adquisición queda
   desconocido (`SourceInfo.device = null`) hasta que AMS revele esa metadata.
4. **Viewer actualizado**. `rbm serve dataset/` lee VibFrame directamente.
   Los IDs de muestra para enlaces del viewer se generan en memoria; no forman
   parte del contrato de intercambio.
5. **`--out` se regenera completo**. `rbm export` borra siempre la carpeta de
   salida antes de escribir, con guardas para evitar rutas peligrosas.

### Consecuencias

- El dataset exportado es compatible por estructura con el formato compartido
  por `vibsynth`, sin acoplamiento runtime.
- Los exports legacy deben regenerarse; el viewer de datasets ya no soporta
  `manifest.parquet`.
- `report.html` sigue escribiéndose como archivo extra de conveniencia, aunque
  no forme parte del contrato VibFrame.
- Gaps pendientes para enriquecer `machine.json`/`metrics.parquet`: sensores,
  direcciones de puntos, modos reales de adquisición, configuración `pdpa`,
  alarmas, RPM en FFT, tendencias por banda y contexto operativo.

## ADR-0010 — Bandas `vddt` como métricas VibFrame y `machine.path` solo con niveles de ubicación

- **Fecha**: 2026-07-18
- **Estado**: aceptada

### Contexto

Los records `vddt` decodifican, además del overall, las bandas con nombre del
template de velocidad (`band_count = 7`), cada columna validada 62/62 contra
el PLOTDATA por-banda de M1H AG-100 (FORMAT §5.7): `Mp Wave` (pico de
aceleración en G's, sin ×25.4), `SUBSINCRONO`, `DESEQUILIBRIO`,
`DESALINEACION`, `HOLGURAS` y `11-40 X RPM` (velocidades ×25.4 → mm/s). Hasta
ahora solo se emitía el overall. Además, `machine.json` escribía
`machine.path = [área, máquina]`, y los visores jerárquicos del ecosistema
(`vibframe_viewer`, entonces subpaquete de t8-extract — **nota 2026-08-05**:
desde el 2026-07-27 es repo propio, `vibframe-viewer`, y este repo lo consume
como dependencia editable) interpretan `path` como niveles de
*ubicación* (location → sublocation) con la máquina como nivel propio, con lo
que la máquina aparecía duplicada como pseudo-sububicación.

### Decisión

1. **Emitir las bandas del template de velocidad** como métricas propias:
   `Trend.bands` (nuevo `TrendBand` en models) con filas en `trends.parquet`
   (`metric_id = band_<slug>__<punto>`, p.ej. `band_subsincrono__M1H`) y
   descriptor en `metrics.parquet` con `name` = etiqueta original AMS.
2. **Descriptores**: bandas de velocidad → `statistic="spectrum_rms"`,
   `detector="rms"`, `band_type="single"`; `Mp Wave` → `statistic="true_peak"`,
   `detector="peak"`, `band_type="none"`, unidad canónica `g` (es un pico de
   forma de onda, no una banda espectral).
3. **Límites de banda**: null salvo los derivables sin decodificar `pdpa`:
   `11-40 X RPM` lleva `band_low_order=11` / `band_high_order=40` (declarados
   por el nombre y corroborados por los bordes 40×RPM aislados en las
   plantillas `pdpa`, FORMAT §5.8). El resto quedará pendiente del decode de
   `pdpa`; se asume la desviación temporal de la spec ("single requiere
   límites") antes que inventar límites o negar que sean bandas.
4. **Columna 6 ("1-20 KHz") no se emite**: unidad y escala sin confirmar
   (la tabla gold está vacía). Lecturas de épocas con `band_count ≠ 7` solo
   aportan el overall (columnas sin etiquetar).
5. **`machine.path = [área]`**: solo niveles de ubicación; la máquina es su
   propio nivel en los visores.

### Consecuencias

- `trends.parquet` multiplica filas (62 lecturas × 6 bandas extra en M1H);
  los consumidores que asumían una métrica por punto deben filtrar por
  `name`/`metric_id` (test de integración actualizado).
- El mapper (`t8-metrics-mapper`) recibe descriptores estructurales de banda
  con nombre original y podrá etiquetarlos canónicamente; aquí no se mapea
  semántica de nombres (workplans/03-vibframe-conformidad.md §4).
- Los datasets exportados antes de este ADR deben regenerarse para obtener
  bandas y el `path` corregido.

## ADR-0011 — Etiquetado canónico como post-proceso con `t8-mapper vibframe --write`

- **Fecha**: 2026-07-19
- **Estado**: aceptada

### Contexto

Los descriptores estructurales del export (ADR-0010) dejaban
`canonical_metric`/`proxy_quality`/`mapping_rule` en null: sin etiquetado
canónico el visor no puede agrupar ni comparar las métricas AMS con las de
los datasets T8/vibsynth. El plan (workplans/03 §4) contemplaba dos encajes:
post-proceso sobre el dataset o paso opcional de `rbm export` si el mapper
está instalado.

### Decisión

1. **Post-proceso, no paso de export**: el etiquetado lo hace
   `t8-mapper vibframe <dataset> --write` (repo `t8-metrics-mapper`),
   que reconstruye la firma estructural desde `metrics.parquet` +
   `machine.json` y escribe las etiquetas de vuelta. `ams-extract` no
   depende del mapper ni del monorepo vibsynth (se mantiene la decisión de
   contrato local copiado); el comando es idempotente y `--diff` valida el
   round-trip. Es el encaje más simple: cero dependencias nuevas aquí y un
   único punto de verdad de las reglas de mapeo para los tres orígenes.
2. **Velocidad de referencia**: el dataset AMS no emite la métrica reservada
   `speed`; el mapper usa como fallback la mediana de `spectra.speed_hz`
   (global y por punto), que es donde este repo emite las RPM por FFT
   (`vdps.0x28`). Cuando se emita el contexto de operación (pendiente), la
   tendencia reservada `speed` tendrá prioridad.
3. **Bandas sin límites**: vibsynth-contracts acepta desde 2026-07-19
   `band_type="single"` sin límites (par incompleto sigue siendo inválido),
   así que la "desviación temporal" asumida en ADR-0010 §3 ya es conforme a
   la spec. El mapper las deja honestamente sin canónica (R099, nota
   explícita): el nombre nunca decide semántica.

### Consecuencias

- BUNGE CARTAGENA completo (347 máquinas, 15 612 métricas): 45.0 %
  etiquetado — 4 882 direct (overall → `vel_overall_rms` IR004v2, Mp Wave →
  `waveform_peak` IR003D), 2 146 approximate (11-40 X RPM →
  `band_sync_high_rms` IR029), 8 584 null (las 4 bandas vddt con nombre,
  SUBSINCRONO/DESEQUILIBRIO/DESALINEACION/HOLGURAS, sin límites).
- El decode de `pdpa` (FORMAT §5.8) es ahora el único bloqueo para etiquetar
  esas 8 584 filas: con límites Hz el mapper las clasificaría por estructura.
- Cada regeneración del dataset (`rbm export`) exige repasar el mapper
  (`--write`); documentado en workplans/03 §4.

## ADR-0012 — Bandas y alarmas desde las plantillas `pdpa`/`pdla`; columna `alarm` derivada

- **Fecha**: 2026-07-19
- **Estado**: aceptada

### Contexto

Las bandas `vddt` se emitían con etiquetas fijas del template de velocidad
(ADR-0010) y sin límites de frecuencia: el mapper dejaba 8 584 filas sin
canónica (55 % del gap de etiquetado, ADR-0011). El decode de `pdpa`
(FORMAT §5.8) era el bloqueo. El análisis de 2026-07-19 resolvió el layout
completo: plantillas `pdpa` (bandas + rangos), sets `pdla` (umbrales C/D),
directorios `gipa`/`gila` y el enlace `pdcd.0xAC/0xAE`. La validación fue
numérica: el valor de cada columna vddt reproduce EXACTO (mediana < 0.1 %)
la RSS de los bins crudos del espectro dentro de `[lo, hi)`, y los umbrales
del set 5 (1.4 / 2.2 mm/s) reproducen las transiciones C/D del gold de M1H.

### Decisión

1. **Etiquetado por plantilla, no hardcodeado**: `walk_trends` resuelve la
   plantilla del punto (`pdcd.0xAC` → directorio `gipa` → `pdpa`) y emite
   las columnas de las lecturas cuyo nº de columnas coincide con los slots
   activos de la plantilla ACTUAL. Lecturas de épocas con otro nº de
   columnas (configuraciones históricas) solo aportan el overall — no hay
   registro de la plantilla histórica y no se inventa. Riesgo residual
   documentado: una época antigua con el mismo nº de columnas y otra
   plantilla se etiquetaría con la actual (es lo que muestra el propio AMS).
2. **Límites de banda en el descriptor**: bandas en órdenes (tipo `0x02`)
   → `band_low_order`/`band_high_order`; bandas en Hz fijos (`0x01`) →
   `band_low_hz`/`band_high_hz`; `band_type="single"`. "Mp Wave" (tipo
   `0x0B`, pico de forma de onda) sigue como `true_peak`/`band_type="none"`.
   La columna "1-20 KHz" (tipo `0x04`) **no se emite**: su valor va en G's
   según el código de unidad `pdla` y los informes `gdnl`, pero sin gold
   numérico que valide la escala.
3. **Columna `alarm` DERIVADA de umbrales**: VibFrame no tiene columnas de
   umbral, así que los umbrales `pdla` se materializan como la columna
   `alarm` de `trends.parquet` (overall y bandas): `0` normal, `2` alerta
   (AMS "C Alarm"), `3` peligro (AMS "D Alarm"); el nivel `1` no se usa
   (AMS no tiene escalón intermedio). Es un valor **calculado aquí**
   comparando `valor >= umbral` en unidades crudas — NO leído de los flags
   por slot del `vddt` (constantes en toda la cadena: no llevan la alarma
   por lectura). `None` cuando el punto no tiene umbral configurado para
   ese slot o el código de unidad no cuadra con la columna.
4. **Umbrales expuestos en el modelo**: `Trend.alert/danger` y
   `TrendBand.alert/danger` en unidades de display (mm/s o G's), por si un
   consumidor quiere los límites además del nivel.

### Consecuencias

- Los puntos HF ("Alta frecuencia 6 KHz", plantillas 4 columnas) emiten
  ahora sus bandas correctamente etiquetadas (10 Hz-2 kHz, 2-4 kHz,
  4-6 kHz en mm/s + Mp Wave) — antes ninguna, porque solo se emitía
  `band_count == 7`. Las variantes "11-60 X RPM" ya no se etiquetan
  "11-40 X RPM".
- `trends.parquet` lleva `alarm` poblado donde hay umbrales; los datasets
  anteriores deben regenerarse (`rbm export` + `t8-mapper vibframe --write`).
- El mapper puede clasificar por estructura las bandas antes null; la
  cobertura de etiquetado de BUNGE sube (ver workplans/03 §4).
- La validación numérica queda como técnica reutilizable: banda =
  RSS de bins crudos in/s en `[lo, hi)`; ×25.4 → mm/s (scripts del
  análisis, no comiteados; método documentado en FORMAT §5.8).

## ADR-0013 — `spectra.speed_hz` = RPM del análisis sin dividir; banda "1 - 20 KHz" emitida en g

- **Fecha**: 2026-07-19
- **Estado**: aceptada

### Contexto

Dos capturas de AMS aportadas por el usuario (PM-9101-A / M1H, área REF)
cerraron dos incógnitas a la vez:

1. La pantalla del espectro (19/05/2021) muestra "RPM = 2900,0 (48,33 Hz)"
   con las familias de armónicos calculadas sobre esa base — exactamente el
   crudo de `vdps.0x28`. El export dividía ese campo por 2 (suposición
   histórica "RPM × 2"), emitiendo la mitad (24,17 Hz) e inconsistente con
   las waveforms (`vdfw`, que nunca se dividían). La identidad RSS de las
   bandas pdpa (ADR-0012) ya había demostrado que AMS usa el crudo como
   base de órdenes.
2. La tendencia de la banda "1 - 20 KHz" en G's ("RMS Aceleración")
   coincide valor a valor con la columna cruda del `vddt`
   (0.229→0.463, 2016→2025): la escala es **cruda en G's, sin factor**.

### Decisión

1. `Spectrum.rpm` = crudo de `vdps.0x28` (la **RPM del análisis** que fija
   AMS). Sin división. OJO: puede diferir de la velocidad física (AG-100
   M1H: análisis a 2920, física/nominal 1455 según `vdpm.0x164` y sus
   `vdfw`) — se emite lo que declara el origen, que es además la base con
   la que AMS evalúa sus bandas por órdenes.
2. Las bandas tipo `0x04` (HF, "1 - 20 KHz") se emiten: `unit=g`,
   `statistic=spectrum_rms`, `band_type=single` con límites Hz del pdpa, y
   umbrales/alarma derivada del pdla en G's. En los descriptores, "pico de
   aceleración" (Mp Wave) queda reservado a bandas de aceleración SIN
   límites.

### Consecuencias

- `spectra.speed_hz` y `waves.speed_hz` quedan coherentes entre sí donde el
  analista fijó bien la RPM (PM-9101-A: 48,33 ambas) y delatan las máquinas
  con RPM de análisis doblada (AG-100: 48,67 vs 24,25).
- El mapper (fallback de velocidad por spectra) pasa a usar la misma base
  de órdenes que AMS; hay que re-etiquetar los datasets exportados.
- Nivel "Advertencia" de las gráficas (~0,95 G's en la captura) ≠ C/D del
  pdla: pendiente de localizar (FORMAT §5.8).

### Nota 2026-08-04 (workplan 07) — el ejemplo de AG-100 no se sostiene

Al decodificar `vdpm.0x164` se comprobó el contraste que este ADR daba por
supuesto: **no hay ni una sola RPM de análisis doblada en BUNGE**. Los 5
espectros del punto piloto de AG-100 llevan 1 455 crudo, igual que sus
`vdfw` y que su nominal; y en los 137 270 espectros de la base, `vdps.0x28`
coincide con `vdpm.0x164` en 134 183 (97,8 %), sin ningún caso de razón 2.
La decisión (emitir el crudo, sin dividir) no cambia — el gold de
PM-9101-A la sostiene, y su nominal es también 2 900 — pero el "OJO" del
punto 1 y la frase "delatan las máquinas con RPM de análisis doblada" del
tercer punto describen algo que esta base no contiene. Donde crudo y
nominal difieren es en máquinas de velocidad variable, con el analista
tecleando la velocidad medida.

## ADR-0014 — Tendencias de aceleración (PeakVue/HF) emitidas: overall crudo en G's

- **Fecha**: 2026-07-20
- **Estado**: aceptada

### Contexto

`walk_trends` emitía solo puntos de velocidad (overall ×25.4 → mm/s,
validado 47/47 con M1H AG-100); los ~2 073 puntos de aceleración de BUNGE
(PeakVue / alta frecuencia, units `G's`) decodificaban estructuralmente
pero se saltaban por no tener gold de escala (ADR-0010 §3).

Dos evidencias del usuario sobre DT-0070 M1P ("Motor Lado Libre Peakvue",
área EXT) lo zanjaron:

1. Captura "Gráf. tendencia / Valore Globale" + "RutaEspectro" (25-mar-26):
   el GLOBAL del espectro PkVue-HP (0.1846 A-DG) coincide a 4 decimales
   con el `overall_raw` de la última lectura del `vddt`, y la forma/pico
   de la curva (máx ~0.92 al día ~564) con la serie decodificada.
2. Informe "Lista Ptos de Tendc" con la tabla completa fecha+valor:
   **147/147 lecturas idénticas** (desviación máx 0.00005 = redondeo a 4
   decimales del informe; fechas con desfase ≤2 h por hora local vs UTC).

Además, los umbrales del set pdla "Peakvue HP 1kHz (P)" (overall 1.5/3.0
G's, Mp Wave 8.0/12.0 G's, unit_code 3) son las líneas ALERTA/Falla del
plot — la derivación de alarma de ADR-0012 aplica sin cambios.

### Decisión

1. **El overall de los trends de aceleración se emite crudo en G's**
   (escala ×1, sin ×25.4). `Trend.units = "G's"`; umbral overall del pdla
   comprobado contra `unit_code` de aceleración (3), no de velocidad.
2. La métrica VibFrame se llama **`overall_acceleration_rms`**
   (`unit=g`, `signal_family=acceleration`, `statistic=spectrum_rms`,
   `detector=rms`) — la de velocidad sigue siendo `overall_velocity_rms`.
3. La banda del template PeakVue ("Mp Wave", tipo 0x0B) sale por el camino
   ya validado de ADR-0010/0012: `band_mp_wave__<punto>`, true_peak en g,
   umbrales 8/12 G's.

### Consecuencias

- BUNGE pasa de ~2 897 series de tendencia (velocidad) a ~4 648: se
  suman 1 751 puntos PeakVue/HF con cadena `vddt`. Los 322 puntos con
  cadena pero sin espectro FFT (unidad indeterminable) se siguen saltando.
  Hay que re-exportar y re-etiquetar con el mapper (regla nueva para
  `overall_acceleration_rms`).
- La columna ALARM del informe trae marcas "Bs" (9 lecturas, Mp Wave
  2.7–5.8 G's) y "Vl" (overall 0.0213, anómalamente bajo) que NO cruzan
  los umbrales C/D del pdla: son otros tipos de alarma de AMS (¿baseline
  superado / valor bajo?), como la "Advertencia" ~0,95 G's de ADR-0013.
  Siguen sin localizar en el binario; la columna `alarm` derivada no los
  refleja.

## ADR-0015 — Contexto de operación: métricas reservadas `speed`/`load` a nivel de máquina

- **Fecha**: 2026-07-20
- **Estado**: aceptada

### Contexto

VibFrame reserva ids de métrica de contexto de operación a nivel de máquina
(spec §"Reserved context metrics"): `speed`, `load` y `state`, con
`metric_id` literal (sin sufijo de punto) y `point_id` null. t8-extract ya
los emite desde sus snapshots; `rbm export` no emitía ninguno y el mapper
tenía que estimar la velocidad de referencia con la mediana de
`spectra.speed_hz` (workplan 03 §4).

AMS sí trae el dato: cada captura de espectro (`vdps.0x28` RPM,
`vdps.0x2C` CARGA %) y de waveform (`vdfw.0x38`, `vdfw.0x3C`) lleva RPM y
CARGA. No hay estado de máquina en el `.rbm` → no hay `state` que emitir.

### Decisión

1. `rbm export` emite POR MÁQUINA las métricas reservadas `speed` y `load`
   con una lectura de contexto por captura (espectros y waveforms):
   - `speed`: valor = rpm / 60.0 en **Hz**. OJO: esa RPM es la **RPM de
     análisis que fija AMS** (ADR-0013), puede diferir de la velocidad
     física — se emite lo que declara el origen. Lecturas con rpm ≤ 0 no
     se emiten.
   - `load`: el campo CARGA % tal cual, unidad `%` (0.0 y 100.0 son
     lecturas válidas).
2. Descriptor machine-level en `metrics.parquet`: `metric_id` literal
   (`"speed"`/`"load"`), `point_id=None`, `path="<machine>:<id>"`,
   `statistic="value"`, `signal_family="non_vibration"`,
   `band_type="none"`. `canonical_metric`/`proxy_quality`/`mapping_rule`
   quedan null como el resto: el etiquetado es post-proceso con t8-mapper
   (ADR-0011), cuyo motor resuelve estos ids por la regla RESERVED
   (`CONTEXT_CANONICAL_METRICS`).
3. Filas en `trends.parquet`: `t` (µs UTC), `value`, `alarm=None`,
   `config_id=""`. Dentro de una máquina se deduplican filas exactas
   (mismo `t` + `metric_id` + `value`): espectro y waveform del mismo
   punto/timestamp comparten rpm.
4. **No se emite `state`**: AMS no tiene estados de máquina.

### Consecuencias

- El mapper deja de depender del fallback por mediana de
  `spectra.speed_hz` en datasets AMS: la reserva `speed` da la velocidad
  declarada por captura.
- Nota sobre AG-100 (DEPURADORA): sus capturas almacenan rpm=1455 en
  TODAS las cadenas (vdps y vdfw) → `speed` = 24.25 Hz uniforme; el
  desdoble análisis 2920 / física 1455 citado en ADR-0013 no aparece en
  las capturas almacenadas de esa máquina.
- `trends.parquet` de máquinas exportadas solo con `--types fft,waveform`
  deja de estar vacío: lleva las filas de contexto.

---

## ADR-0016 — DiagGT: modelos normativos en `vibsynth-contracts`, spec de referencia aquí

- **Fecha**: 2026-07-27
- **Estado**: aceptada

### Contexto

`docs/GROUND_TRUTH.md` define DiagGT, el formato de ground truth de
diagnóstico externo (informes de analista, etiquetas de campo) que faltaba en
el ecosistema, y este repo lo produce desde los informes Preditec de BUNGE
Cartagena (workplan 04). El formato lo consumirán varios repos —
vibsynth-diagnostics para evaluar, t8-extract para emitir GT desde
`alarms.db`/`annotations`, el visor para pintar bandas de estado — y todos
ellos ya dependen de `vibsynth-contracts` para el layout VibFrame. Mantener
el esquema sólo como prosa en ams-extract obligaría a cada consumidor a
reimplementar su propia validación, con deriva garantizada.

Es la misma situación que resolvió ADR-0009 con VibFrame: el formato lo
define contracts, este repo lo produce sin depender de él en runtime.

### Decisión

1. **Los modelos normativos de DiagGT viven en `vibsynth-contracts`**
   (`vibsynth_contracts/diagnosis/external.py`, Pydantic v2 frozen):
   documento raíz, `provenance`, `observation`, `machine`, `finding` y los
   vocabularios (`status`, `fault_group`, `label_quality`, `record_kind`,
   `origin`). Ante discrepancia con la prosa, gana el modelo.
2. **`docs/GROUND_TRUTH.md` queda como spec de referencia**: el porqué, los
   vocabularios, las reglas GTxxx de mapeo y CWxxx de crosswalk, y el
   texto que `docs/VIBFRAME.md` de contracts cita como referencia normativa
   del contenido de los ficheros. Sube a **v0.1.1** con las fricciones
   detectadas al hacer el crosswalk real (reglas CW001–CW004 en §2.4,
   `dataset_machine_id` en las columnas del consolidado §5, `crosswalk.csv`
   y `crosswalk_ambiguities.md` en §4).
3. **Sin dependencia runtime**: el extractor de informes
   (`../Informes Bunge Cartagena 2026/ground-truth/extract_informes_gt.py`)
   sigue siendo stdlib + pdfplumber + pandas, sin importar
   `vibsynth_contracts`. La conformidad se comprueba desde fuera, con el CLI
   `vibframe-validate` de contracts sobre el `ground-truth/` del dataset.
4. **El crosswalk no es destructivo**: `crosswalk.csv` es la fuente del mapeo
   TAG ↔ `machine_id` y el consolidado su proyección; los `*.diaggt.json` no
   se reescriben nunca tras la extracción.

### Consecuencias

- Un consumidor valida un DiagGT con
  `DiagGTDocument.model_validate_json(...)` en vez de confiar en la prosa;
  los 6 informes BUNGE validan contra los modelos sin cambios.
- Un cambio de esquema DiagGT es ahora un PR a contracts (modelos + spec
  citada) y no una edición suelta de este repo; el número de versión del
  documento y el de los modelos deben moverse juntos.
- La copia de cortesía
  `../Informes Bunge Cartagena 2026/ground-truth/FORMATO_GROUND_TRUTH.md`
  es un snapshot de v0.1.0 y queda desalineada hasta que se regenere; la
  copia normativa es `docs/GROUND_TRUTH.md`.

---

## ADR-0017 — `waves.n_samples` es la longitud del array; el bloque nominal de AMS es prosa

- **Fecha**: 2026-07-27
- **Estado**: aceptada

### Contexto

`vibframe-validate` marcaba `waves.data-length` (severidad *error*) en 311
de las 347 máquinas de `bunge_cartagena_ams`: `len(data) != n_samples`. El
export escribía en `waves.n_samples` el `vdfw.0x2C` del descriptor —el
**bloque nominal de adquisición** (256, 512, … 16384 = 2,56 × líneas del
FFT)— mientras el array emitido tiene otra longitud (488, 4148, 244…).

La causa está caracterizada sobre las 137.208 waveforms de BUNGE
(FORMAT §5.5): AMS **no escribe las últimas 150 muestras** del bloque
nominal y redondea el almacenamiento al múltiplo de 244 (la capacidad de
un `vcfw`) que cubre ese payload, rellenando la cola con ceros:
`stored = 244 · ceil((nominal − 150) / 244)`. Por eso lo decoded sale
más corto que el nominal (488 < 512) o más largo (4148 > 4096). No es
recorte de calibración ni bins de cabecera.

El contrato VibFrame deriva el eje temporal de `t + i / sample_rate_hz`,
así que `n_samples` sólo puede significar una cosa: cuántas muestras hay.
Con el nominal, la duración declarada (0,200 s) no era la del wave emitido
(0,191 s) — incoherencia interna, no sólo un campo mal.

### Decisión

1. **`Waveform.n_samples` = `len(samples)`** (lo decodificado y emitido).
   Arrastra a todo lo derivado sin más cambios: `waves.n_samples`,
   `manifest.parquet`, el parquet de `rbm extract`, el eje temporal de los
   PNG y el visor, que ya usaban ese campo o la longitud del array.
2. **El nominal no se pierde**: `Waveform.nominal_n_samples` lo conserva
   verbatim desde `vdfw.0x2C`. En `machine.json`, el `proc_mode` del
   waveform lleva `n_samples` = longitud emitida y el nominal en `notes`
   ("AMS acquisition block is 512 samples; 488 are stored and emitted").
   Se prefiere prosa a un campo del contrato: `AcquisitionModeDoc` no tiene
   hueco para "bloque pedido vs bloque almacenado", y meter el nominal en
   `n_samples` reproduciría la incoherencia un nivel más arriba.
3. **No se recorta el array**: la cola de ceros (`nominal − 150` en
   adelante) se sigue emitiendo. Cambiar los datos exige gold de AMS
   propio ("no emitir lo no validado"); queda registrado en FORMAT §5.5
   con la constante `VDFW_TAIL_NOT_STORED = 150`.

### Consecuencias

- `vibframe-validate` deja de reportar `waves.data-length`; el productor
  AMS queda sin incumplimientos.
- Los datasets exportados antes de este ADR llevan el nominal en
  `waves.n_samples` y hay que **re-exportarlos** para que validen
  (`bunge_cartagena_ams` completo: ~19 s con `--parallel 4`).
- Un consumidor que quiera el bloque nominal lo lee de las notas del
  `proc_mode`, no de una columna.
- Pendiente separado: decidir, con gold, si el array emitido debe
  recortarse al payload real (`nominal − 150`); hasta entonces un RMS o
  factor de cresta calculado aguas abajo sobre `waves.data` incluye la
  cola de ceros (~26% de las muestras en el caso 512 → 488).

## ADR-0018 — Las alarmas `gdnl` de AMS se emiten como DiagGT `origin="system-alarm"`

- **Fecha**: 2026-07-27
- **Estado**: aceptada

### Contexto

Cada punto de un `.rbm` guarda el veredicto de su última «Medición de
Análisis por Excepción» en un record `gdnl` — el informe literal
`"SUBSINCRONO - 1.986 mm/Seg - C Alarm"` — fechado y graduado por su
`gdsc` (FORMAT §5.9, resuelto el mismo día). Son **991 alarmas** sobre
4.970 puntos en BUNGE: un juicio sobre el estado de una máquina en un
instante, es decir, exactamente lo que DiagGT representa, y la fuente que
el workplan 04 §4 tenía apuntada como «GT de alarma nativo del sistema».

A diferencia del GT del analista (6 informes PDF, 2.321 observaciones),
este juicio es **automático por umbral**: no dice qué falla, dice que una
banda cruzó su límite. El vocabulario `origin` de la spec DiagGT ya
reserva `"system-alarm"` para esto (§2.2, v0.1.1).

### Decisión

1. **Un documento DiagGT por `.rbm`**, `origin="system-alarm"`, escrito
   por el comando nuevo `rbm alarms` en `<dataset>/ground-truth/`. La
   unidad de intercambio de DiagGT es el documento fuente y aquí el
   documento fuente es la base de datos: `source_ref` = el `.rbm` y
   `source_sha256` su hash (16 s para 1,8 GB; `--skip-hash` lo evita).
2. **Una observación por punto en alarma**, no por máquina: una máquina
   puede tener varios puntos en alarma con bandas y fechas distintas, y
   agregarlas perdería el dato. El punto va en `analysis_text` (DiagGT
   v0.1 no tiene referencia de componente, spec §6) y la máquina es la
   clave de join: `dataset_machine_id` = `equipment.short_code`, que es
   literalmente el nombre de la partición `machine=` que produce
   `rbm export` — este productor **sí** conoce el `machine_id`, así que
   lo rellena en origen y no necesita crosswalk (las 347 particiones de
   `bunge_cartagena_ams` resuelven, 0 dangling). El `external_tag` (TAG
   de planta extraído del nombre AMS) y su `normalized_tag` se emiten
   igual, para poder unir con el GT del analista: `AG-100` y `AG.100`
   normalizan ambos a `AG100`.
3. **Mapeo de estado**: `C Alarm` → `ALERT` / `alarm=2`, `D Alarm` →
   `DANGER` / `alarm=3`. Es la misma escala 0/2/3 que ya deriva la
   columna `alarm` de las tendencias (ADR-0012) y la traducción directa
   de la spec §3.1 («Alerta»/«Peligro»). `WATCH`/1 queda sin usar porque
   AMS no tiene escalón entre normal y alerta. Los puntos calmados **no**
   generan observación: la ausencia significaría «no en alarma **o** no
   analizado», y un OK falso es peor que un hueco.
4. **Sólo se emite lo validado** (regla del repo): la alarma debe caer
   donde su nivel dice, contra los umbrales `pdla` del punto y en la
   misma unidad. Las **18** alarmas cuyo código de unidad del `pdla`
   contradice la unidad del texto (plantillas mal configuradas en AMS,
   FORMAT §5.9) se cuentan, se registran y **no se emiten** → 973 de 991.
5. **Findings con reglas propias GT050-GT053**: una banda en alarma es
   *evidencia*, no diagnóstico. Las bandas cuyo nombre nombra un fallo
   (DESEQUILIBRIO, DESALINEACION, HOLGURAS, FALLO ELECTRIC) se mapean con
   `label_quality="weak"` (o `"group"`), un escalón por debajo de lo que
   las reglas de prosa de analista (GT001/GT002/GT004/GT013) declaran
   para el mismo texto; el resto (SUBSINCRONO, OVERALL VALUE, Mp Wave,
   `11-40 X RPM`, `1 - 20 KHz`) produce el finding `unmapped` obligatorio.
   Nuevo id de regla en vez de reusar el de analista con otra calidad:
   cambiar la calidad de una regla existente rompería su versionado.
6. **Consolidado aparte y opcional**: `--consolidate` escribe
   `observations_system.parquet`/`.csv` con las columnas de la spec §5.
   Nunca se toca `observations.parquet`, que es el consolidado del
   analista.
7. **Sin dependencia de contracts en runtime** (ADR-0009): el documento
   se construye con dicts y los modelos normativos se aplican en los
   tests (`test_diag_gt.py`, `test_integration_alarms.py`).

### Consecuencias

- `bunge_cartagena_ams/ground-truth/` gana un séptimo `*.diaggt.json`
  con **973 observaciones** (461 ALERT + 512 DANGER) sobre 235 máquinas,
  2013-08-14 → 2026-03-26, junto a los 6 del analista;
  `vibframe-validate` sigue en PASS.
- Los dos ground truths conviven y se distinguen por `provenance.origin`:
  un consumidor puede evaluar contra el analista, contra el sistema, o
  medir el acuerdo entre ambos (el segundo es más denso en el tiempo y
  más débil como diagnóstico).
- `extraction_method` queda **`null`**: el vocabulario de la spec
  (`pdf_text_parse` | `manual` | `llm`) no contempla un decode binario.
  Añadir `binary_decode` es un cambio menor de contracts y queda
  propuesto, no forzado.
- La nota es una foto: si AMS reanaliza, la alarma anterior desaparece
  del fichero. El documento no es reproducible desde un `.rbm` posterior,
  de ahí que el hash del fichero sea parte de la procedencia.
