#!/usr/bin/env python3
"""
bru_tea.py - BRU Maker One Teemaschine per Bluetooth LE steuern.

Protokoll rekonstruiert aus der BRU-App 1.13.0 (Hermes-Bytecode v96).

Voraussetzungen:
    pip install bleak

Erstes Koppeln (einmalig, wichtig!):
    Die Maschine verlangt BLE-Pairing mit Code (verschlüsselte Characteristics).
    Am besten zuerst über das Betriebssystem koppeln:
      Linux:   bluetoothctl -> scan on -> pair <MAC>  (Code von der Maschine eingeben)
      Windows: Einstellungen -> Bluetooth -> Gerät hinzufügen
      macOS:   Der Pairing-Dialog erscheint automatisch beim ersten Verbinden.
    Auf der Maschine ggf. vorher Setup -> Bluetooth -> Pairing aktivieren.

Beispiele:
    python bru_tea.py scan
    python bru_tea.py status
    python bru_tea.py brew --temp 80 --time 3:00 --water 200
    python bru_tea.py brew --temp cold --time 0:30 --water 100
    python bru_tea.py brew --temp 95 --time 4:00 --water 250 --address AA:BB:CC:DD:EE:FF
"""

import argparse
import asyncio
import hashlib
import struct
import sys
import time
import uuid

from bleak import BleakClient, BleakScanner

# --------------------------------------------------------------------------
# BLE-Konstanten
# --------------------------------------------------------------------------
SERVICE_UUID = "aae28f00-71b5-42a1-8c3c-f9cf6ac969d0"
NOTIFY_UUID  = "aae28f01-71b5-42a1-8c3c-f9cf6ac969d0"   # "readUUID"  (Notifications)
WRITE_UUID   = "aae28f02-71b5-42a1-8c3c-f9cf6ac969d0"   # "writeUUID" (write without response)
FW_REV_UUID  = "00002a26-0000-1000-8000-00805f9b34fb"   # Device Info 180A / Firmware Revision
NAME_PREFIX  = "BRU"

# Kommandos (App -> Maschine)
CMD_SET_TIME      = 0x08
CMD_GET_SETUP     = 0x2A
CMD_SET_SETUP     = 0x2C
CMD_BREW_START    = 0x40
CMD_CANCEL        = 0x42
CMD_BRU_STATUS    = 0x44
CMD_BUTTON_PRESS  = 0x46
CMD_GET_PRESET    = 0x50
CMD_UPDATE_PRESET = 0x52

# Antworten (Maschine -> App), Byte [2] ist die Kommando-ID
RSP_BREW_RESULT   = 0x41
RSP_STATUS        = 0x45
RSP_BUTTON_RESULT = 0x47

BREW_RESULT = {
    0: "OK – Brühvorgang gestartet",
    1: "Befehlsformat abgelehnt (passt nicht zur Firmware)",
    3: "Temperatur von dieser Firmware nicht unterstützt",
    4: "Brühzeit von dieser Firmware nicht unterstützt",
    5: "Wassermenge nicht unterstützt (25-ml-Schritte brauchen neuere Firmware)",
    16: "Maschine nicht bereit – Deckel zu? Wassertank voll? Tasse drunter?",
}

STATUS = {1: "StandbyMode", 2: "FunctionMenu", 3: "MachineSetup", 4: "MachineSetupHidden",
          5: "Brewing", 6: "Dispensing", 7: "AlarmTimer", 8: "ColdTea", 9: "SplitCup",
          10: "MultiSteeping", 11: "InfoMessage", 12: "WarningMessage", 13: "ErrorMessage",
          14: "HotTea", 15: "ManufTest", 16: "ManualTest", 21: "Drying", 22: "Descaling",
          23: "LidReminder", 24: "BluetoothMenu"}

SUBSTATUS = {0: "null", 2: "homeScreensaver", 4: "homeScreen", 25: "brewingFillingUp",
             26: "brewingSteeping", 27: "brewingRinseDelay", 28: "brewingServing",
             29: "brewingRinse", 30: "brewingEnjoy", 31: "brewingColdWater",
             32: "brewingHotWater", 33: "dispensing", 112: "setupBlePairing",
             120: "msgPlaceCup", 121: "msgRemoveCup", 122: "msgCloseLid", 123: "msgOpenLid",
             124: "msgAddWater", 125: "msgInsertChamber", 126: "msgNoNozzle", 127: "msgError",
             130: "msgNextCup", 131: "msgCupRemoved", 233: "firmwareUpdate"}

# Firmware-Grenzen (Format der Firmware-Version: "DDMMYY-...")
WATER_25ML_MIN_DATE           = "280526"
EXTENDED_BREW_PAYLOAD_MIN_DATE = "290626"


# --------------------------------------------------------------------------
# Frame-Aufbau
# --------------------------------------------------------------------------
def checksum(frame: bytes, length: int) -> int:
    """_calcChecksum: (0 - Summe der ersten length-1 Bytes) XOR 0x3A, als uint8."""
    s = sum(frame[: length - 1])
    return ((-s) & 0xFF) ^ 0x3A


def build_frame(cmd: int, payload: bytes = b"", length: int | None = None) -> bytes:
    """[0xFF, Länge, Cmd, Payload..., 0-Padding..., Checksumme]  (Länge = Gesamtlänge)."""
    if length is None:
        length = len(payload) + 4
    body = bytearray([0xFF, length, cmd]) + bytearray(payload)
    while len(body) < length - 1:
        body.append(0)
    body.append(checksum(body, length))
    return bytes(body)


# --------------------------------------------------------------------------
# Werte-Kodierung (aus temperaturePickerData / timePickerData / waterPickerData)
# --------------------------------------------------------------------------
def temp_code(t: str) -> int:
    """cold -> 0, 45..95 °C in 5er-Schritten -> 1..11, max/100 -> 12."""
    t = str(t).lower().strip().rstrip("c").rstrip("°")
    if t in ("cold", "kalt", "0"):
        return 0
    if t in ("max", "maximum", "100"):
        return 12
    c = int(t)
    if c < 45 or c > 95 or c % 5:
        raise ValueError("Temperatur: cold, 45-95 in 5er-Schritten oder max")
    return (c - 40) // 5


def time_code(t: str) -> int:
    """0:10-9:50 in 10-s-Schritten, danach 10:00-60:00 in Minutenschritten."""
    if ":" in t:
        m, s = t.split(":")
        secs = int(m) * 60 + int(s)
    else:
        secs = int(t)
    if 10 <= secs < 600:
        if secs % 10:
            raise ValueError("Unter 10 min nur 10-Sekunden-Schritte")
        m, s10 = divmod(secs // 10, 6)       # Minuten, Zehnersekunden
        return 6 * m + s10 - 1
    if 600 <= secs <= 3600:
        if secs % 60:
            raise ValueError("Ab 10 min nur volle Minuten")
        return 59 + (secs // 60 - 10)
    raise ValueError("Brühzeit muss zwischen 0:10 und 60:00 liegen")


WATER_50 = {50: 0, 100: 1, 150: 2, 200: 3, 250: 4, 300: 5, 350: 6}
WATER_25 = {75: 128, 125: 129, 175: 130, 225: 131, 275: 132, 325: 133}


def water_code(ml: int, fw: str | None) -> int:
    if ml in WATER_50:
        return WATER_50[ml]
    if ml in WATER_25:
        if not fw_at_least(fw, WATER_25ML_MIN_DATE):
            raise ValueError(f"{ml} ml braucht Firmware >= {WATER_25ML_MIN_DATE}")
        return WATER_25[ml]
    raise ValueError("Wassermenge: 50-350 ml (50er-Schritte, neue Firmware auch 25er)")


# --------------------------------------------------------------------------
# Firmware-Vergleich (firmwareDatestamp / firmwareDateKey / firmwareAtLeast)
# --------------------------------------------------------------------------
def _fw_key(datestamp: str | None):
    if not datestamp or len(datestamp) != 6 or not datestamp.isdigit():
        return None
    return int(datestamp[4:6] + datestamp[2:4] + datestamp[0:2])   # YYMMDD


def fw_at_least(fw: str | None, min_date: str) -> bool:
    if not fw:
        return False
    stamp = fw.replace("\x00", "").strip().split("-")[0]
    a, b = _fw_key(stamp), _fw_key(min_date)
    return a is not None and b is not None and a >= b


# --------------------------------------------------------------------------
# Kommandos
# --------------------------------------------------------------------------
def name_utf16(name: str) -> bytes:
    """stringToWcharUTF8: 48 Bytes, max. 24 Zeichen, je [charCode & 0xFF, 0]."""
    out = bytearray(48)
    for i, ch in enumerate(name[:24]):
        out[2 * i] = ord(ch) & 0xFF
    return bytes(out)


def app_install_id8() -> bytes:
    """App: sha256(getUniqueId())[:8]. Hier stabil aus der MAC dieses Rechners abgeleitet."""
    return hashlib.sha256(str(uuid.getnode()).encode()).digest()[:8]


def brew_command(temp: int, time_: int, water: int, rinse: bool = False,
                 buzzer: bool = True, fw: str | None = None,
                 preset_name: str = "Freestyle", tea_id: int = 0) -> bytes:
    params = bytes([
        0,                  # presetId-Slot (App sendet 0 = "instant brew")
        temp,               # Temperatur-Code
        time_,              # Zeit-Code
        water,              # Wasser-Code
        1 if rinse else 0,  # Spülen
        0,                  # Spülintensität
        0,                  # Spülverzögerung
        1 if buzzer else 0, # Buzzer
        0, 0, 0,
    ])
    payload = params
    if fw_at_least(fw, EXTENDED_BREW_PAYLOAD_MIN_DATE):
        identity = app_install_id8() + name_utf16(preset_name) + struct.pack("<I", tea_id)
        payload += identity
    return build_frame(CMD_BREW_START, payload, len(payload) + 4)


def status_command() -> bytes:
    return build_frame(CMD_BRU_STATUS, b"", 4)


def set_time_command() -> bytes:
    # getUnixTimeMSB: Ortszeit als Unix-Sekunden, uint32 little-endian
    local = int(time.time() - time.timezone + (3600 if time.localtime().tm_isdst > 0 else 0))
    return build_frame(CMD_SET_TIME, struct.pack("<I", local & 0xFFFFFFFF), 8)


def button_command(button: int) -> bytes:
    return build_frame(CMD_BUTTON_PRESS, bytes([button]), 5)


# --------------------------------------------------------------------------
# BLE
# --------------------------------------------------------------------------
async def find_machine(address: str | None, timeout: float = 6.0):
    if address:
        dev = await BleakScanner.find_device_by_address(address, timeout=timeout)
    else:
        dev = await BleakScanner.find_device_by_filter(
            lambda d, ad: (d.name or ad.local_name or "").startswith(NAME_PREFIX)
            or SERVICE_UUID in [u.lower() for u in ad.service_uuids],
            timeout=timeout)
    if dev is None:
        sys.exit("Keine BRU-Maschine gefunden. Bluetooth an? Maschine eingeschaltet?")
    return dev


class Bru:
    def __init__(self, client: BleakClient):
        self.c = client
        self.fw: str | None = None
        self.queue: asyncio.Queue = asyncio.Queue()

    def _on_notify(self, _sender, data: bytearray):
        data = bytes(data)
        print("  <-", data.hex(" ").upper(), "|", self.describe(data))
        self.queue.put_nowait(data)

    @staticmethod
    def describe(d: bytes) -> str:
        if len(d) < 4:
            return "?"
        cmd = d[2]
        if cmd == RSP_STATUS and len(d) > 4:
            return f"Status: {STATUS.get(d[3], d[3])} / {SUBSTATUS.get(d[4], d[4])}"
        if cmd == RSP_BREW_RESULT:
            return f"Brüh-Ergebnis: {BREW_RESULT.get(d[3], f'unbekannt ({d[3]})')}"
        if cmd == RSP_BUTTON_RESULT:
            return f"Button-Ergebnis: {d[3]}"
        return f"Antwort 0x{cmd:02X}"

    async def setup(self):
        try:
            raw = await self.c.read_gatt_char(FW_REV_UUID)
            self.fw = raw.decode("utf-8", "ignore").replace("\x00", "").strip()
        except Exception as e:
            print("  Firmware-Version nicht lesbar:", e)
        print(f"  Firmware: {self.fw or 'unbekannt'}")
        await self.c.start_notify(NOTIFY_UUID, self._on_notify)
        await self.write(set_time_command())   # wie die App; erste verschlüsselte Op

    async def write(self, frame: bytes):
        print("  ->", frame.hex(" ").upper())
        await self.c.write_gatt_char(WRITE_UUID, frame, response=False)

    async def wait_for(self, cmd_id: int, timeout: float = 5.0):
        end = asyncio.get_event_loop().time() + timeout
        while (left := end - asyncio.get_event_loop().time()) > 0:
            try:
                d = await asyncio.wait_for(self.queue.get(), left)
            except asyncio.TimeoutError:
                break
            if len(d) > 3 and d[2] == cmd_id:
                return d
        return None

    async def status(self):
        await self.write(status_command())
        return await self.wait_for(RSP_STATUS)


async def run(args):
    if args.cmd == "scan":
        for d, ad in (await BleakScanner.discover(timeout=6, return_adv=True)).values():
            name = d.name or ad.local_name or ""
            if name.startswith(NAME_PREFIX):
                print(f"{d.address}  {name}  RSSI {ad.rssi}")
        return

    dev = await find_machine(args.address)
    print(f"Verbinde mit {dev.name} ({dev.address}) ...")
    async with BleakClient(dev, timeout=15.0) as client:
        try:
            await client.pair()           # löst ggf. den Pairing-Code-Dialog aus
        except Exception:
            pass
        bru = Bru(client)
        await bru.setup()

        if args.cmd == "status":
            if await bru.status() is None:
                print("Keine Statusantwort.")

        elif args.cmd == "brew":
            frame = brew_command(
                temp_code(args.temp), time_code(args.time),
                water_code(args.water, bru.fw), rinse=args.rinse,
                buzzer=not args.no_buzzer, fw=bru.fw, preset_name=args.name)
            await bru.write(frame)
            res = await bru.wait_for(RSP_BREW_RESULT, 6)
            if res is None:
                print("Keine Bestätigung erhalten – Status prüfen.")
                await bru.status()
            elif res[3] != 0:
                sys.exit(1)
            elif args.follow:
                print("Verfolge Brühvorgang (Strg+C zum Beenden) ...")
                while True:
                    await asyncio.sleep(3)
                    st = await bru.status()
                    if st and len(st) > 3 and st[3] == 1:   # zurück im Standby
                        print("Fertig. Guten Appetit! 🍵")
                        break

        elif args.cmd == "cancel":
            await bru.write(build_frame(CMD_CANCEL, b"", 4))   # cancelProcess() der App
            await asyncio.sleep(0.3)
            await bru.status()

        await asyncio.sleep(0.5)


def main():
    p = argparse.ArgumentParser(description="BRU Maker One per BLE steuern")
    p.add_argument("--address", help="MAC-Adresse (Linux/Windows) bzw. UUID (macOS)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="BRU-Maschinen in der Nähe suchen")
    sub.add_parser("status", help="Maschinenstatus abfragen")
    sub.add_parser("cancel", help="Laufenden Vorgang abbrechen")
    b = sub.add_parser("brew", help="Tee zubereiten")
    b.add_argument("--temp", default="80", help="cold, 45-95 (5er-Schritte) oder max  [80]")
    b.add_argument("--time", default="3:00", help="m:ss, 0:10-9:50 / 10:00-60:00  [3:00]")
    b.add_argument("--water", type=int, default=200, help="ml: 50,100,...,350  [200]")
    b.add_argument("--rinse", action="store_true", help="Spülen nach dem Brühen")
    b.add_argument("--no-buzzer", action="store_true", help="Ohne Signalton")
    b.add_argument("--name", default="Freestyle", help="Name (nur neue Firmware)")
    b.add_argument("--follow", action="store_true", help="Status bis zum Ende verfolgen")
    for sp in sub.choices.values():
        sp.add_argument("--address", help=argparse.SUPPRESS, default=argparse.SUPPRESS)
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
