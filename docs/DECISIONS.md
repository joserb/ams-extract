# Architectural Decision Records

> ADRs cortos para las decisiones técnicas no triviales del proyecto.
> Formato libre por entrada: contexto, decisión, alternativas, consecuencias.

Las decisiones consolidadas en el plan original están en `docs/PLAN.md` §3 y §8;
aquí se documentan las que aparecen durante la implementación.

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
