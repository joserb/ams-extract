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
