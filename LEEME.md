# MUUN RECOVERY APP

Aplicación estructurada (núcleo desacoplado + interfaz Tkinter) para recuperar
fondos de billeteras Muun a partir de `muun.zip` o una carpeta.

## Estructura

- `core/` — núcleo: validación, carga de cuentas, servidores Electrum, escaneo
  BTC/Lightning/Muun, transferencias.
- `ui/` — interfaz Tkinter.
- `tests/` — pruebas (50 OK, 1 omitida por falta de openssl).
- `bin/recovery-tool.exe` — motor oficial de Muun (+ `.sha256`).
- `go/servers.go` — lista de servidores Electrum de Muun.

## Ejecutar

1. Descomprime el ZIP en una carpeta (ej. `D:\Humberto\MUUN_RECOVERY_APP`).
2. Doble clic en `iniciar.bat` (o `py -3 MUUN_RECOVERY_APP.py`).
3. Pulsa **ABRIR muun.zip** o **ABRIR CARPETA**.
4. Selecciona una cuenta con estado **Listo para escanear**, marca la casilla
   de confirmación y pulsa **ESCANEAR CUENTA SELECCIONADA**.
5. El resultado muestra cada UTXO detectado con sus sats y su dirección
   (p. ej. «1.600 sats en bc1q…»), además del total.
6. Para direcciones sueltas: **ESCANEAR DIRECCIONES BTC**.
7. Para Lightning: **ESCANEAR LIGHTNING** (requiere variables de entorno LNbits).
8. **EXPORTAR CSV** guarda el resumen sin Recovery Code.
9. `verificar.bat` comprueba el SHA-256 del motor y ejecuta las pruebas.

## Formato del Recovery Code

El motor oficial de Muun espera 8 grupos de 4 caracteres separados por guion:

```
ABCD-1234-POW2-R561-P120-JK26-12RW-45TT   (39 caracteres)
```

- Alfabeto: `A-Z` y `0-9` (incluye 0, 1, 8 y 9).
- La app acepta el código con o sin guiones y lo normaliza al formato oficial.

## Sobre comisiones y retiro on-chain

- Los UTXOs del kit son **on-chain**: el retiro es siempre por Bitcoin on-chain.
- En la pestaña TRANSFERENCIAS pega una dirección Bitcoin mainnet (`bc1q…`/`bc1p…`)
  y pulsa **EXTRAER UTXOs A ESTA DIRECCIÓN**. El programa abre el recovery-tool
  oficial en una consola propia e interactiva y copia la dirección al portapapeles
  para que la pegues cuando el motor pregunte por el destino.
- El motor te pedirá el Recovery Code, el destino y la comisión, y pedirá su propia
  confirmación antes de firmar y transmitir.
- La comisión on-chain la descuenta el motor del monto barrido y es ineludible.
- La app no admite transferencias Lightning del kit (los UTXOs son on-chain).
- Recibir los fondos en una wallet con dirección on-chain propia (p. ej. una
  dirección `bc1…` de tu wallet de Lightning que también reciba on-chain) sirve
  como destino; verifica siempre que la dirección es mainnet y tuya.

## Configuración (variables de entorno, no en el código)

- LNbits: `MUUN_LNBITS_URL`, `MUUN_LNBITS_INVOICE_KEY`
- Bitcoin Core: `MUUN_BITCOIN_RPC_URL`, `MUUN_BITCOIN_RPC_USER`,
  `MUUN_BITCOIN_RPC_PASSWORD`; opcional `MUUN_BITCOIN_RPC_WALLET`.

## Seguridad

- El escaneo es de solo lectura; nunca envía fondos.
- La transferencia exige casilla de propiedad + frase `AUTORIZO ENVIAR`.
- El Recovery Code solo se pasa por stdin al motor y nunca se guarda ni muestra completo.
- El motor es el binario oficial de Muun: envía en cuanto aceptas la comisión,
  sin pregunta final propia; la app lo advierte y exige autorización.
