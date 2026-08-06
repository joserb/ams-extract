# Protocolo de verificación visual contra AMS

> Cómo validar que lo extraído por `ams-extract` coincide con lo que un
> analista vería en AMS Machinery Manager para el mismo punto y timestamp.

Estado: jerarquía verificada en 7/15 áreas; FFT (velocidad mm/s + aceleración
G's), waveform (G's / mm/s) y tendencia "Valores Globales" (mm/s, 47/47)
validados contra el gold de AMS; alarmas almacenadas (`gdnl`) cruzadas contra
los umbrales `pdla` (991/991). **Export completo validado end-to-end**
(274.478 muestras, conteo exacto, 2026-05-31). Registro concreto en §5.

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
     `n_samples` que muestra AMS es el **bloque nominal** (512, 4096…); lo
     emitido es la longitud almacenada (488, 4148…), que es lo que debe
     casar con `len(samples)` (FORMAT §5.5, ADR-0017).
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
| 2026-07-27 | BUNGE completo (137.208 waveforms) | todos | longitud almacenada | n_samples nominal (256…16384) | `244 · ceil((nominal − 150) / 244)` | ✓ 137.208/137.208, sin excepciones (FORMAT §5.5, ADR-0017) — verificación estructural sobre el binario, no gold de AMS |

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
