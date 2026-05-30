# Protocolo de verificación visual contra AMS

> Cómo validar que lo extraído por `ams-extract` coincide con lo que un
> analista vería en AMS Machinery Manager para el mismo punto y timestamp.

Estado: **Fase 4 ejecutada (parcial)**. Jerarquía verificada en 7/15 áreas;
FFT (velocidad mm/s + aceleración G's) y waveform (G's) validados a ±5–10%
contra el gold de AMS. Calibración cerrada el 2026-05-30. Registro de
verificaciones concretas en §5.

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
   - Waveform: sample_rate, n_samples, units, Pc(+) y Pk(-).
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

### Waveform (G's)

| Fecha | Punto | Timestamp | Métrica | AMS | Decodificado | Match |
|---|---|---|---|---|---|---|
| 2026-05-29 | AG-100 M1H | 2020-02-19 | Pc(+) | 0.483 G | 0.483 G | ✓ <0.3% (calibrado `vdfw.0x28`) |
| 2026-05-29 | AG-100 M1H | 2020-02-19 | Pk(-) | -0.510 G | -0.510 G | ✓ |

### Pendiente de verificación visual

- 8 áreas grandes restantes (conteos locked en tests de integración, pero
  sin cotejo visual nombre-a-nombre): EXTRACCION, PREPARACION, REFINERIA,
  IMPULSIÓN DE MAR, PARQUE TANQUES, FULL-FAT, OBSOLETOS, OSMOSIS.
- `vddt` (Valores Globales / tendencias): pendiente de decodificar antes de
  poder verificar (Fase 7).
