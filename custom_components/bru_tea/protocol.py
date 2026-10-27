"""BRU Maker One BLE-Protokoll (rekonstruiert aus BRU-App 1.13.0)."""
from __future__ import annotations

import hashlib
import re
import struct
import time
import uuid

SERVICE_UUID = "aae28f00-71b5-42a1-8c3c-f9cf6ac969d0"
NOTIFY_UUID = "aae28f01-71b5-42a1-8c3c-f9cf6ac969d0"
WRITE_UUID = "aae28f02-71b5-42a1-8c3c-f9cf6ac969d0"
FW_REV_UUID = "00002a26-0000-1000-8000-00805f9b34fb"
NAME_PREFIX = "BRU"

CMD_SET_TIME = 0x08
CMD_BREW_START = 0x40
CMD_BRU_STATUS = 0x44
CMD_BUTTON_PRESS = 0x46

RSP_BREW_RESULT = 0x41
RSP_STATUS = 0x45
RSP_BUTTON_RESULT = 0x47

BREW_RESULT = {
    0: "OK",
    1: "Befehlsformat abgelehnt (Firmware passt nicht)",
    3: "Temperatur von der Firmware nicht unterstützt",
    4: "Brühzeit von der Firmware nicht unterstützt",
    5: "Wassermenge nicht unterstützt (25-ml-Schritte brauchen neuere Firmware)",
    16: "Maschine nicht bereit – Deckel, Wassertank, Tasse prüfen",
}

STATUS = {1: "StandbyMode", 2: "FunctionMenu", 3: "MachineSetup", 4: "MachineSetupHidden",
          5: "Brewing", 6: "Dispensing", 7: "AlarmTimer", 8: "ColdTea", 9: "SplitCup",
          10: "MultiSteeping", 11: "InfoMessage", 12: "WarningMessage", 13: "ErrorMessage",
          14: "HotTea", 15: "ManufTest", 16: "ManualTest", 17: "DurabPVtest",
          18: "DurabPumptest", 19: "DurabHeatertest", 20: "DurabFulltest", 21: "Drying",
          22: "Descaling", 23: "LidReminder", 24: "BluetoothMenu"}
STATUS_STANDBY = 1

SUBSTATUS = {0: "null", 1: "languageChoice", 2: "homeScreensaver", 3: "introScreen",
             4: "homeScreen", 5: "editBrewingTime", 6: "editTemperature", 7: "editWaterAmount",
             10: "presetStatus", 11: "multiSteeping", 13: "dispenserStatus", 14: "timerScreen",
             15: "timerRunning", 16: "coldTeaScreen", 18: "splitCupScreen", 19: "hotTeaScreen",
             25: "brewingFillingUp", 26: "brewingSteeping", 27: "brewingRinseDelay",
             28: "brewingServing", 29: "brewingRinse", 30: "brewingEnjoy",
             31: "brewingColdWater", 32: "brewingHotWater", 33: "dispensing",
             40: "setupScreen", 90: "descalingIntro", 91: "descalingStatus", 99: "descalingEnd",
             110: "setupBle", 112: "setupBlePairing", 120: "msgPlaceCup", 121: "msgRemoveCup",
             122: "msgCloseLid", 123: "msgOpenLid", 124: "msgAddWater",
             125: "msgInsertChamber", 126: "msgNoNozzle", 127: "msgError", 128: "msgContinue",
             129: "msgCancel", 130: "msgNextCup", 131: "msgCupRemoved", 229: "waterFilter",
             233: "firmwareUpdate"}

WATER_25ML_MIN_DATE = "280526"
EXTENDED_BREW_PAYLOAD_MIN_DATE = "290626"

# ---- Optionen für die HA-Auswahllisten --------------------------------------
TEMP_OPTIONS = ["Kalt"] + [f"{c} °C" for c in range(45, 100, 5)] + ["Max"]
TIME_OPTIONS = (
    [f"{s // 60}:{s % 60:02d}" for s in range(10, 600, 10)]
    + [f"{m}:00" for m in range(10, 61)]
)
WATER_OPTIONS = [f"{ml} ml" for ml in (50, 75, 100, 125, 150, 175, 200, 225, 250,
                                       275, 300, 325, 350)]


def checksum(frame: bytes, length: int) -> int:
    return ((-sum(frame[: length - 1])) & 0xFF) ^ 0x3A


def build_frame(cmd: int, payload: bytes = b"", length: int | None = None) -> bytes:
    if length is None:
        length = len(payload) + 4
    body = bytearray([0xFF, length, cmd]) + bytearray(payload)
    while len(body) < length - 1:
        body.append(0)
    body.append(checksum(body, length))
    return bytes(body)


def temp_code(t) -> int:
    t = re.sub(r"[^0-9a-z]", "", str(t).lower()).rstrip("c")
    if t in ("cold", "kalt", "0"):
        return 0
    if t in ("max", "maximum", "100"):
        return 12
    c = int(t)
    if c < 45 or c > 95 or c % 5:
        raise ValueError("Temperatur: Kalt, 45–95 °C in 5er-Schritten oder Max")
    return (c - 40) // 5


def time_code(t) -> int:
    t = str(t).strip()
    if ":" in t:
        m, s = t.split(":")
        secs = int(m) * 60 + int(s)
    else:
        secs = int(t)
    if 10 <= secs < 600:
        if secs % 10:
            raise ValueError("Unter 10 min nur 10-Sekunden-Schritte")
        m, s10 = divmod(secs // 10, 6)
        return 6 * m + s10 - 1
    if 600 <= secs <= 3600:
        if secs % 60:
            raise ValueError("Ab 10 min nur volle Minuten")
        return 59 + (secs // 60 - 10)
    raise ValueError("Brühzeit muss zwischen 0:10 und 60:00 liegen")


WATER_50 = {50: 0, 100: 1, 150: 2, 200: 3, 250: 4, 300: 5, 350: 6}
WATER_25 = {75: 128, 125: 129, 175: 130, 225: 131, 275: 132, 325: 133}


def water_code(ml, fw: str | None) -> int:
    ml = int(re.sub(r"\D", "", str(ml)))
    if ml in WATER_50:
        return WATER_50[ml]
    if ml in WATER_25:
        if not fw_at_least(fw, WATER_25ML_MIN_DATE):
            raise ValueError(f"{ml} ml braucht Firmware ab {WATER_25ML_MIN_DATE}")
        return WATER_25[ml]
    raise ValueError("Wassermenge: 50–350 ml")


def _fw_key(stamp: str | None):
    if not stamp or len(stamp) != 6 or not stamp.isdigit():
        return None
    return int(stamp[4:6] + stamp[2:4] + stamp[0:2])


def fw_at_least(fw: str | None, min_date: str) -> bool:
    if not fw:
        return False
    a = _fw_key(fw.replace("\x00", "").strip().split("-")[0])
    b = _fw_key(min_date)
    return a is not None and b is not None and a >= b


def _name_utf16(name: str) -> bytes:
    out = bytearray(48)
    for i, ch in enumerate(name[:24]):
        out[2 * i] = ord(ch) & 0xFF
    return bytes(out)


def _install_id8() -> bytes:
    return hashlib.sha256(str(uuid.getnode()).encode()).digest()[:8]


def brew_command(temp: int, time_: int, water: int, rinse=False, buzzer=True,
                 fw: str | None = None, name: str = "Freestyle", tea_id: int = 0) -> bytes:
    payload = bytes([0, temp, time_, water, 1 if rinse else 0, 0, 0,
                     1 if buzzer else 0, 0, 0, 0])
    if fw_at_least(fw, EXTENDED_BREW_PAYLOAD_MIN_DATE):
        payload += _install_id8() + _name_utf16(name) + struct.pack("<I", tea_id)
    return build_frame(CMD_BREW_START, payload, len(payload) + 4)


def status_command() -> bytes:
    return build_frame(CMD_BRU_STATUS, b"", 4)


def set_time_command() -> bytes:
    lt = time.localtime()
    local = int(time.time() + (lt.tm_gmtoff or 0))
    return build_frame(CMD_SET_TIME, struct.pack("<I", local & 0xFFFFFFFF), 8)


def button_command(button: int) -> bytes:
    return build_frame(CMD_BUTTON_PRESS, bytes([button]), 5)
