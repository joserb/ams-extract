# Protocolo de verificación visual contra AMS

> Cómo validar que lo extraído por `ams-extract` coincide con lo que un
> analista vería en AMS Machinery Manager para el mismo punto y timestamp.

Estado: jerarquía verificada en 7/15 áreas; FFT (velocidad mm/s + aceleración
G's), waveform (G's / mm/s) y tendencia "Valores Globales" (mm/s, 47/47)
validados contra el gold de AMS; alarmas almacenadas (`gdnl`) cruzadas contra
los umbrales `pdla` (991/991). **Export completo validado end-to-end**
(274.478 capturas FFT + waveform, conteo exacto) y **despliegue VibFrame 0.2
revalidado** con Common Codes y waveforms completas (2026-08-12). Registro
concreto en §5.

**Cómo leer el historial.** Las filas hasta 2026-08-10 se midieron sobre
datasets **VibFrame 0.1** y siguen siendo el gold del *decode* (escalas,
conteos, timestamps y umbrales). El envoltorio cambió a **VibFrame 0.2** en
`5781773` (ADR-0019); la primera foto 0.2 quedó sólo en suite y aún marcaba el
reexport como pendiente. Esa condición fue **resuelta el 2026-08-12** por
ADR-0020/ADR-0021 y el workplan 14. El despliegue vigente es
`~/wslprojects/RESONINS/datasets/bunge_cartagena_ams`; el antiguo
`../bunge_dataset/` de junio (`manifest.parquet` + `samples/`) es un snapshot
legacy distinto y no es la publicación VibFrame.

## 1. Objetivo

Confirmar, con humano en el bucle, que la **forma, magnitud y ejes** de los
espectros FFT y las waveforms extraídos coinciden con los que muestra AMS
para el mismo punto y timestamp. La extracción estructural (jerarquía,
timestamps) se valida en los tests de integración; la calibración de
amplitudes y la coincidencia de picos requieren comparación contra
capturas de AMS.

## 2. Material necesario

- VM Windows XP con AMS Machinery Manager y la base `.rbm` original cargada
  (o capturas de pantalla ya tomadas del punto/timestamp de interés).
- El fichero `.rbm` accesible desde WSL (referenciado por `RBM_TEST_FILE`).
- `rbm extract` ejecutado contra el mismo fichero, mismo punto, mismo
  timestamp.
- La "Lista de Picos" de AMS (frecuencia + amplitud por pico) y/o los
  valores Pc(+)/Pk(-) de la waveform como gold numérico.

## 3. Pasos

1. **Localizar el punto y timestamp** en AMS y anotar el gold:
   - FFT: Fmax, n_lines, units, RPM, CARGA, y la "Lista de Picos"
     (frecuencia Hz + amplitud en unidad de display).
   - Waveform: sample_rate, n_samples, units, Pc(+) y Pk(-). Ojo: el
     `n_samples` que muestra AMS es la longitud completa (512, 4096…) y debe
     casar con `len(samples)`: 150 muestras salen de `vdfw` y el resto de
     `vcfw` (FORMAT §5.5, ADR-0020).
2. **Extraer con la herramienta**:
   ```bash
   RBM_TEST_FILE="…/BUNGE CARTAGENA marzo 2.0.rbm" \
     uv run rbm extract "$RBM_TEST_FILE" \
       --point "MOTOR LOA HORIZONTAL" --equipment "AG-100" \
       --type both --out /tmp/verif/
   ```
3. **Comparar frecuencias** (FFT): cada pico de la "Lista de Picos" de AMS
   debe caer en el bin correcto del array extraído (`bin · Fmax / n_lines`).
4. **Comparar amplitudes** (FFT): ratio gold/calibrado por pico; se espera
   ±5–10% y una correlación log alta (logcorr > 0.99). Velocidad sale en
   mm/s (×48.5), aceleración en G's (×1.30).
5. **Comparar waveform**: Pc(+) y Pk(-) calibrados (vía `vdfw.0x28`) deben
   casar con AMS dentro del ~2%.
6. **Inspección visual del PNG** contra el screenshot de AMS (forma general,
   posición del pico dominante, fondo de ruido).
7. **Registrar** el resultado en la tabla §5.

## 4. Criterios de aceptación

- **Frecuencias**: todos los picos de la "Lista de Picos" de AMS caen en el
  bin correcto (tolerancia ±1 bin).
- **Amplitudes FFT**: residual gold/calibrado median ≈ 1.0; cada pico dentro
  de ±5–10%; logcorr ≥ 0.99 sobre la lista de picos.
- **Waveform**: Pc(+) y Pk(-) dentro del ~2% del gold.
- **Jerarquía**: lista de áreas/equipos/puntos coincide nombre-a-nombre con
  el árbol de AMS (orden puede diferir: AMS ordena alfabéticamente,
  nosotros por chain-order — decisión consciente).

## 5. Registro de verificaciones realizadas

### Informes Preditec — auditoría 0.5.0 (2026-08-13)

El script reproducible `scripts/audit_informes_unmapped.py` leyó los seis
documentos archivados de la generación determinista 0.4.0: **6.669
observaciones**, **61 findings `unmapped` en 22 textos** y masa 44,999997.
Con las reglas del extractor 0.5.0 quedan **24 `unmapped`** y masa 20,333332.
La clasificación exclusiva de las 61 observaciones de partida fue: 18 fallos
explícitos, 25 estados sanos/estables, 17 peticiones administrativas y 1 caso
sin contexto suficiente. `pdfplumber` fue 0.11.10; el auditor registra además
hashes de cada documento, reglas, vetos, cláusulas y observaciones afectadas.

La relectura geométrica completa de las **921 páginas** conservó anclas y
conteos, y recuperó desbordes de `ANÁLISIS` demostrables en `CF.9110S1`,
`TC.1523A2`, `PM.4500`, `PM.9700A` y `LA.1249A2`. La asignación exige una
etiqueta de modalidad explícita o un ancla léxica inequívoca; un `_pre`
ambiguo no se incorpora.

La publicación del 2026-08-13 archivó la determinista 0.5.0 y desplegó la
contextual 0.1.2 tanto junto a los informes como en Bunge. La adenda revisa
**13 textos / 42 observaciones**: 11 textos cambian claves en 35 observaciones
y dos textos de estado desaparecen del overlay al quedar `findings=[]` en 7.
Quedan **133 juicios / 415 observaciones y 0 remapeos manuales**. Los seis
documentos validan contra `DiagGTDocument`; preservan los seis `source_sha256`,
los 6.669 `observation_id` y producen 1.308 findings. Frente a 0.4.0 cambian
76 observaciones: 65 en findings, 11 en `analysis_text`, 6 en estado y 1 en
alarma (con solapamiento entre campos).

El dataset materializa 7 documentos, 7.642 observaciones, 3.620 consolidadas
y 2.281 findings. Conserva la proyección del crosswalk: 6.349/6.669
observaciones de informe y 973/973 alarmas tienen `dataset_machine_id`, igual
que el backup. `vibframe-validate`: **0 errores**, 731 avisos y 5 informativos;
el aviso nuevo es el hash honestamente obsoleto de
`analysis/diaggt-contrast`, cuya entrada cambió. Backup previo:
`/tmp/ams-wp16-backup-20260813.lD7m8e/`.

El spike reproducible `scripts/audit_informes_status_matrix.py` leyó las 102
páginas de «Resumen Estado de Máquinas» (17 por informe): 12.102 iconos, que
son seis copias idénticas de **1.660 celdas históricas** y 357 estados
actuales sobre **354 máquinas**. Los siete iconos raster tienen hashes
estables y 0 firmas desconocidas; 283 máquinas ya aparecen en DiagGT, 71 son
exclusivas de la matriz y el crosswalk vigente resuelve 273. No hubo ninguna
discrepancia entre informes. El JSON completo no normativo está desplegado
como `ground-truth/audit-status-matrix-2026-08-13.json` junto a los PDF
(SHA-256 `5b937aaef2f4cb699d7a25e4425bdf8de50cb7da4cfeeb6608f217fd1e817a81`).

### Empaquetado VibFrame real (2026-08-13)

`rbm package` leyó el Bunge desplegado directamente desde RESONINS y escribió
una copia temporal fuera del dataset: **1.761 entradas**, 1.444.234.607 bytes
expandidos, 1.295.722.789 bytes comprimidos con `deflate` y **44,83 s**. La
validación completa del `.vibframe.zip` encontró 347 máquinas, 7 documentos
DiagGT y 2 capas de análisis con **0 errores**, 730 avisos y 5 informativos.
Los 730 avisos son exactamente las dos deudas ya registradas para el
directorio (588 `analysis.stale-input` + 142 tipos de nodo abiertos), no
problemas del envelope. El paquete temporal se eliminó después de validar.

### Jerarquía (Fase 2 / 2b)

| Fecha | Alcance | Resultado | Notas |
|---|---|---|---|
| 2026-05-27 | 15 áreas vs árbol AMS | ✓ match exacto | `test_real_file_yields_fifteen_areas` |
| 2026-05-28 | DEPURADORA 28 equipos | ✓ tras fix gicm 20-slot | ADR-0004; antes faltaban 8 |
| 2026-05-29 | 7/15 áreas nombre-a-nombre | ✓ 4/5 incl. orden | CALDERAS swap A↔B en PM-6904 (AMS ordena alfabético) |

### FFT — velocidad (mm/s)

| Fecha | Punto | RPM | Timestamp | logcorr | escala | Resultado |
|---|---|---|---|---|---|---|
| 2026-05-30 | AG-100 M1H | 1455 | 2020-02-19 | +0.999 | 48.0 | ✓ 24 picos ±5–10% (dominante 14.68 Hz: 5.059 gold vs 4.76) |
| 2026-05-30 | PM-6901-A M1H | 3000 | 2026-01-20 | +0.999 | 48.7 | ✓ |
| 2026-05-30 | AR-1211 M1H | 1500 | 2026-03-26 | +0.998 | 47.9 | ✓ |

### FFT — aceleración (G's)

| Fecha | Punto | Tipo | Fmax | residual | logcorr | Resultado |
|---|---|---|---|---|---|---|
| 2026-05-30 | PM-6901-A M2P | PeakVue | 1000 | ±8% (24 picos) | — | ✓ |
| 2026-05-30 | PM-6901-A B1P | PeakVue | 1000 | median 0.998 | +0.995 | ✓ |
| 2026-05-30 | PM-6901-B M1F | HF (alta frec.) | 6000 | median 1.009 | +0.998 | ✓ 24/24 ±10% |

### Waveform

| Fecha | Punto | Timestamp | Métrica | AMS | Decodificado | Match |
|---|---|---|---|---|---|---|
| 2026-05-29 | AG-100 M1H | 2020-02-19 | Pc(+) | 0.483 G | 0.483 G | ✓ <0.3% (calibrado `vdfw.0x28`) |
| 2026-05-29 | AG-100 M1H | 2020-02-19 | Pk(-) | -0.510 G | -0.510 G | ✓ |
| 2026-05-31 | CONTRA INCENDIOS PM-0CI/1 M LOA H | — | unidades | mm/s | mm/s | ✓ velocidad ×25.4 (regresión del leak in/s) |
| 2026-07-27 | BUNGE completo (137.208 waveforms) | todos | longitud de cadena `vcfw` | n_samples nominal (256…16384) | `244 · ceil((nominal − 150) / 244)` | ✓ 137.208/137.208; dato correcto, interpretación histórica sustituida por ADR-0020: medía la continuación, no la waveform completa |
| 2026-08-12 | BUNGE completo (137.208 waveforms) | todos | reconstrucción `vdfw` + `vcfw` | n_samples nominal (256…16384) | `concat(vdfw[0xD4:], vcfw)[:n_samples]` | ✓ 137.208/137.208 con longitud nominal; las 150 cabeceras contienen señal y todo el exceso `vcfw` es cero (verificación estructural, ADR-0020) |
| 2026-08-12 | AG-100 M1H | 2020-02-19 | secuencia completa | 512 muestras; Pc/Pk 0,483/−0,510 G | 512 muestras; Pc/Pk 0,483/−0,510 G | ✓ extremos conservados; RMS corregido de 0,15749 a 0,18746 G |

### Tendencia "Valores Globales" (`vddt`)

| Fecha | Punto | Gold | Resultado |
|---|---|---|---|
| 2026-05-30 | AG-100 M1H | PLOTDATA "Valore Globale" (47 filas) | **47/47** exacto (fecha + valor, incl. duplicado 13-jul-2017 y pico 36.43 mm/s) |
| 2026-05-30 | AG-100 M1H (bandas) | PLOTDATA por banda (5 ficheros + Mp Wave) | **62/62** por banda (etiquetado de columnas) |
| 2026-07-20 | DT-0070 M1P (PeakVue, G's) | "Lista Ptos de Tendc" (147 filas, 2013–2026) | **147/147** overall crudo = G's del informe (desv. máx 0.00005, el redondeo a 4 decimales); fechas ≤2 h (local vs UTC); umbrales pdla 1.5/3.0 G's = líneas ALERTA/Falla del plot (ADR-0014) |

### Alarmas almacenadas por AMS (`gdnl` / `gdsc`)

Validación **estructural sobre el binario** (no gold de pantalla): las notas
de alarma se cotejan contra decodificaciones ya validadas del mismo fichero
— los umbrales `pdla` (§5.8, con su propio gold M1H) y los timestamps de las
muestras (§5.3/§5.5/§5.7, validados contra AMS). Es el mismo criterio de la
fila de "longitud almacenada" de la waveform.

| Fecha | Alcance | Comprobación | Resultado |
|---|---|---|---|
| 2026-07-27 | 4 970 notas de puntos vivos de BUNGE | `gdsc.0x1C` = timestamp de una muestra del punto (±1 s) | **4 648/4 648** de los puntos con muestras (100 %); 4 627 son exactamente la muestra más reciente |
| 2026-07-27 | 991 alarmas de BUNGE | valor del texto dentro del intervalo de su nivel según el `pdla` del punto (`C` → `[C, D)`, `D` → `[D, ∞)`), sin tolerancia | **991/991 (100 %)**. Test de nulidad barajando el set `pdla`: 53,8 % en las alarmas C (intervalo cerrado), 66,2 % en total |
| 2026-07-27 | 991 alarmas de BUNGE | zona del índice de severidad `gdsc.0x1A` (1-40 = C, 41+ = D) = nivel del texto | **991/991 (100 %)** — dos campos independientes coinciden |
| 2026-07-27 | 462 alarmas C de BUNGE | modelo de severidad `1 + 40·(v − C)/(D − C)` | **461/462 dentro de ±1** (el texto redondea a 3 decimales). La zona D no se ajusta: pendiente |
| 2026-07-27 | 347 equipos de BUNGE | TAG extraído del nombre AMS vs `crosswalk.csv` del GT del analista | **270 de acuerdo, 1 discrepancia** (`MA-9606` duplicado en AMS: el crosswalk eligió el gemelo sin sufijo), 68 TAGs que el informe no nombra |

**No emitido**: 18 alarmas (1,8 %) cuyo código de unidad del `pdla` no
coincide con la unidad del texto (15 `1 - 20 KHz` de PM-0CI/1-3, 3
`Mp Wave` en sets HF). Documentadas en FORMAT §5.9 y ADR-0018.

### Export DiagGT de alarmas (`rbm alarms`)

| Fecha | Alcance | Resultado |
|---|---|---|
| 2026-07-27 | BUNGE completo → `bunge_cartagena_ams/ground-truth/Alarmas AMS BUNGE CARTAGENA marzo 2.0.diaggt.json` | **973 observaciones** `origin="system-alarm"` (461 ALERT + 512 DANGER) sobre **235 máquinas** (202 de ellas también en el GT del analista), 2013-08-14 → 2026-03-26; 31 s de reloj incluido el sha256 de 1,8 GB. Todas con `dataset_machine_id` resuelto (0 dangling) |
| 2026-07-27 | `vibframe-validate` sobre el dataset, antes y después | **antes**: PASS, 347 máquinas, 6 DiagGT, 2.321 obs, 0 errores / 0 avisos. **después**: **PASS**, 347 máquinas, **7 DiagGT, 3.294 obs**, **0 errores / 0 avisos** (los 2.321 «without dataset_machine_id» siguen siendo los del analista, cuyo mapeo vive en `crosswalk.csv`) |

### Export masivo (validación end-to-end)

| Fecha | Alcance | Resultado |
|---|---|---|
| 2026-05-31 | BUNGE completo, `--parallel 4` | **18,6 s**; 15 áreas, 311/347 equipos con datos, **0 fallos**; **137.270 FFT + 137.208 waveform = 274.478** (cuadra exacto con AMS); 622 Parquet, 1,3 GB; carga Hive OK |
| 2026-07-27 | Área CONTRA INCENDIOS (4 equipos, `--types fft,waveform,trend`), conformidad `vibframe-validate` | **antes** (dataset publicado, copia): FAIL, 4/4 máquinas con `waves.data-length`; **después** (ADR-0017): **PASS 4/4**, 0 errores / 0 avisos con `--sample-rows 100000` (todas las filas). 34 s de reloj incl. arranque (0,2 s de export) |
| 2026-08-12 | BUNGE completo VibFrame 0.2, `--types fft,waveform,trend --parallel 4` (ADR-0020) | **0 fallos**; 311/347 equipos con datos; 137.270 FFT + **137.208 waveform** + 1.571.433 trend, 1.735 Parquet. Auditoría por lotes de todos los `waves.parquet`: **137.208/137.208** filas con `len(data) == n_samples`, distribución exacta 256…16.384. **Foto intermedia del mismo día**: el checkout editable ya exigía Common Codes y dejó visibles dos tests rojos de unidad; ADR-0021/workplan 14 los resolvió antes del cierre y la fila final de la sección registra el PASS. |

### Migración a VibFrame 0.2 (`5781773`)

| Fecha | Alcance | Resultado |
|---|---|---|
| 2026-08-10 | Código del export y del materializador GT migrados a VibFrame 0.2 (commit `5781773` «Export VibFrame 0.2 datasets», ADR-0019) | **Foto histórica, superada el 2026-08-12.** En ese commit sólo se verificó la suite: `tests/test_vibframe_conformance.py` validaba los fixtures y hacía round-trip de los tres goldens 0.2 (`ams-rbm`, `t8-backup`, `vibsynth`). Todavía no se había ejecutado la base real ni regenerado el despliegue. |
| 2026-08-10 | Re-validación end-to-end 0.2 del despliegue Bunge | **Pendiente en esta fecha; completada el 2026-08-12.** La fila siguiente sustituye este estado y aporta los conteos actuales. Se conserva la fila para explicar el intervalo entre migrar el writer y regenerar la publicación. |
| 2026-08-12 | BUNGE desplegado, reexport VibFrame 0.2 con Common Codes (ADR-0021) y postprocesos | **COMPLETADO**. 347 máquinas; 137.270 spectra + 137.208 waves + 1.571.433 trends; 24.684 métricas. Unidades del catálogo: 15.367 `C16`, 8.695 `K40`, 311 `HTZ`, 311 `P1`; spectra: 85.698 `C16` + 51.572 `K40`; waves: 503 `C16` + 136.705 `K40`. Auditoría completa: 0 ondas con `len(data) != n_samples`. `t8-mapper`: 23.590/24.684 labels (95,6 %), 0 diferencias en segunda pasada. `enrich`: definición en 347 máquinas, 3.728 frecuencias en 91 máquinas, 0 cambios en segunda pasada y 56 designaciones sin resolver. Los 24 ficheros preservados de `ground-truth/` y `analysis/` coinciden byte a byte. Validador: **0 errores**, 730 avisos conocidos (588 hashes obsoletos de las capas de análisis conservadas y 142 tipos de nodo del enriquecedor aún no documentados); por ello `--strict` falla deliberadamente y no se falsearon los hashes para hacerlo pasar. |

### Auditoría del corpus RESONINS (2026-08-12)

Se inspeccionaron las 32 raíces bajo `~/wslprojects/RESONINS/datasets`, sus
catálogos y las columnas `unit` de 1.543.477 espectros y 1.534.375 ondas, y se
ejecutó el validador actual sin muestreo de arrays:

- las 32 declaran VibFrame `0.2.0`, usan `metric_catalog.json` y no contienen
  `metrics.parquet`;
- Bunge/AMS y los 29 datasets T8 terminan con **0 errores**; los avisos de
  esos 30 pertenecen a procedencia, crosswalk, leyendas de estado o
  vocabulario abierto, no a unidades;
- `vibsynth_fleet_demo` y `vibsynth_opmodes_demo` fallan con 12 errores cada
  uno porque conservan labels (`mm/s`, `g`, `Hz`, `°`, `adim`, `id`) en el
  catálogo y los Parquet. Son deuda de regeneración de `vibsynth`, no del
  productor AMS;
- los `load` T8 con `M39` son conformes y deliberados: el backup declara la
  carga en `cm/s²`, y la métrica reservada conserva la magnitud del origen.

### Máquinas sin muestras (GT 2026-07-20)

36/347 equipos de BUNGE exportan 0 filas en todos sus parquets. Verificado
contra AMS (screenshot PM-500 vs PM-501): son máquinas **vacías también en
AMS** — puntos definidos pero sin ningún espectro/waveform/tendencia
guardados. En el binario: 15 tienen puntos sin cadenas (`pdcd` sin heads,
como PM-501) y 21 tienen cadenas de configuración cuyos walkers producen 0
muestras (spot-check: CF-4900, PM-9765-A, PM-9606-A y el gemelo duplicado
REDUCTOR TOASTER DT-0070). 11 de las 36 están en OBSOLETOS. El export no
pierde nada.

### Pendiente de verificación visual

- 8 áreas grandes restantes (conteos locked en tests de integración, pero
  sin cotejo visual nombre-a-nombre): EXTRACCION, PREPARACION, REFINERIA,
  IMPULSIÓN DE MAR, PARQUE TANQUES, FULL-FAT, OBSOLETOS, OSMOSIS.
- **Nota (2026-08-05)** — `pdpa`/`pdla` **ya no están pendientes de gold**: el
  análisis del 2026-07-19 (FORMAT §5.8, ADR-0012) cerró las plantillas de banda
  con sus rangos y los sets de umbrales, validados numéricamente contra
  decodificaciones ya validadas del mismo fichero — el valor de cada columna
  `vddt` reproduce la RSS de los bins crudos del espectro en `[lo, hi)`
  (mediana < 0,1 %) y los umbrales del set 5 (1,4 / 2,2 mm/s) reproducen las
  transiciones C/D del gold de M1H, coherente con la fila de alarmas `gdnl` de
  arriba (991/991 contra `pdla`).
- Lo que sigue **sin localizar** en el binario son los **otros tipos de alarma**
  de AMS, que la columna `alarm` derivada no refleja: el nivel «Advertencia»
  (~0,95 G's en la captura de ADR-0013) y las marcas «Bs» / «Vl» del informe
  de tendencias de DT-0070 (ADR-0014). Necesitan gold del diálogo de bandas/
  alarmas de AMS.
