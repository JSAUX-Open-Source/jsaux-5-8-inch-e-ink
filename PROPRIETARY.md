# Unavailable / not open-sourced

This MIT-licensed tree does **not** include:

- Chip firmware binaries or chip firmware / OTA flashing
- Silicon vendor internals, MCU/SoC die details, PCBA schematics
- Panel driver IC programming guides, waveform / LUT tables, or flash part manuals
- Internal factory specification documents

`firmware_update_supported()` is always false. Do not expect secondary
developers to reverse-fill chip firmware update support from this repository.

Host App code that performs BLE connect, device-info query, and image transfer
lives in `eink_display.py` as part of this open App tree. Chip firmware / OTA
flashing remains unavailable.
