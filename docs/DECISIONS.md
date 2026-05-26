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
