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
CMD_CANCEL = 0x42
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

# Aus der BRU-App 1.13.0 übernommen
SUBSTATUS = {0: 'null',
 1: 'languageChoice',
 2: 'homeScreensaver',
 3: 'introScreen',
 4: 'homeScreen',
 5: 'editBrewingTime',
 6: 'editTemperature',
 7: 'editWaterAmount',
 10: 'presetStatus',
 11: 'multiSteeping',
 12: 'multiSteepingEdit',
 13: 'dispenserStatus',
 14: 'timerScreen',
 15: 'timerRunning',
 16: 'coldTeaScreen',
 17: 'coldTeaEdit',
 18: 'splitCupScreen',
 19: 'hotTeaScreen',
 20: 'hotTeaEdit',
 21: 'hotTea2Screen',
 22: 'hotTea2Edit',
 25: 'brewingFillingUp',
 26: 'brewingSteeping',
 27: 'brewingRinseDelay',
 28: 'brewingServing',
 29: 'brewingRinse',
 30: 'brewingEnjoy',
 31: 'brewingColdWater',
 32: 'brewingHotWater',
 33: 'dispensing',
 40: 'setupScreen',
 41: 'setupCurrentTime',
 42: 'setupTimeHours',
 43: 'setupTimeMinutes',
 44: 'setupTimeAmPm',
 45: 'setupRinse',
 46: 'setupRinseEdit',
 47: 'setupRinseIntensity',
 48: 'setupRinseIntensityEdit',
 49: 'setupRinseWaitTime',
 50: 'setupRinseWaitTimeEdit',
 51: 'setupMultiSteeping',
 52: 'setupMultiSteepingEdit',
 53: 'setupDispenser',
 54: 'setupDispenserEdit',
 55: 'setupAlarm',
 56: 'setupAlarmEdit',
 57: 'setupAlarmHours',
 58: 'setupAlarmMinutes',
 59: 'setupAlarmAmPm',
 60: 'setupCooldown',
 61: 'setupCooldownEdit',
 62: 'setupSplitCup',
 63: 'setupSplitCupEdit',
 64: 'setupHotTea',
 65: 'setupHotTeaEdit',
 66: 'setupScreensaver',
 67: 'setupScreensaverEdit',
 68: 'setupRgb',
 69: 'setupRgbEdit',
 70: 'setupBuzzer',
 71: 'setupBuzzerEdit',
 72: 'setupLanguage',
 73: 'setupLanguageEdit',
 74: 'setupUnits',
 75: 'setupUnitsEdit',
 76: 'setupTimeFormat',
 77: 'setupTimeFormatEdit',
 78: 'setupLidReminder',
 79: 'setupLidReminderEdit',
 80: 'setupHotTea2',
 81: 'setupHotTea2Edit',
 90: 'descalingIntro',
 91: 'descalingStatus',
 92: 'descalingRinsePumpOn',
 93: 'descaleWithAdapter',
 94: 'descaleAdapterInst',
 95: 'descaleInCup',
 96: 'descaleScanQr',
 97: 'descaleInstallAdapter',
 98: 'descaleAddDescaler',
 99: 'descalingEnd',
 100: 'descalingRinseSystem',
 101: 'descalingCheckWater',
 102: 'descalingRefillWater',
 103: 'descalingCheckLid',
 104: 'descalingPila',
 105: 'descalingRinseEnd',
 106: 'setupPresetAmount',
 107: 'setupPresetAmountEdit',
 108: 'descalingRinsePumpOff',
 110: 'setupBle',
 111: 'setupBleEdit',
 112: 'setupBlePairing',
 113: 'setupBlePairingEdit',
 120: 'msgPlaceCup',
 121: 'msgRemoveCup',
 122: 'msgCloseLid',
 123: 'msgOpenLid',
 124: 'msgAddWater',
 125: 'msgInsertChamber',
 126: 'msgNoNozzle',
 127: 'msgError',
 128: 'msgContinue',
 129: 'msgCancel',
 130: 'msgNextCup',
 131: 'msgCupRemoved',
 132: 'msgPlaceDescaling',
 133: 'checkEngineInfo',
 140: 'setupChamber',
 141: 'setupChamberEdit',
 142: 'setupNozzle',
 143: 'setupNozzleEdit',
 144: 'setupLid',
 145: 'setupLidEdit',
 146: 'setupCup',
 147: 'setupCupEdit',
 148: 'setupIrCalibration',
 149: 'setupIrCalibrationExe',
 150: 'setupOpenPls',
 151: 'setupOpenPlsEdit',
 152: 'setupClosePls',
 153: 'setupClosePlsEdit',
 154: 'setupDescaling',
 155: 'setupDescalingEdit',
 156: 'setupFactoryReset',
 157: 'setupFactoryResetEdit',
 160: 'debugMenuEnter',
 161: 'manufTestsEnter',
 162: 'manufTests',
 163: 'manufTestsEdit',
 164: 'manualTestsEnter',
 165: 'durabilityTestsEnter',
 166: 'dryingMachine',
 227: 'infoPvClosing',
 228: 'infoPvOpening',
 229: 'waterFilter',
 230: 'waterFilterEdit',
 231: 'waterFilterReset',
 232: 'waterFilterResetExe',
 233: 'firmwareUpdate',
 234: 'functionInDevelopment'}

# Phasen-Code -> Text-Schlüssel der App (statuses.*)
PHASE_KEY = {2: 'homeScreen',
 4: 'homeScreen',
 25: 'fillingUp',
 26: 'steeping',
 27: 'rinseDelay',
 28: 'serving',
 29: 'rinsing',
 30: 'enjoy',
 31: 'loadingColdWater',
 32: 'loadingHotWater',
 33: 'dispensing',
 90: 'descalingIntro',
 91: 'descalingInProgress',
 93: 'descaleWithAdapter',
 94: 'adapterInstalled',
 95: 'descalerInCup',
 96: 'scanQrCode',
 97: 'installAdapter',
 98: 'addDescaler',
 99: 'descalingFinished',
 100: 'rinseSystem',
 101: 'freshWaterAttached',
 102: 'refillWaterTank',
 103: 'lidInstalled',
 104: 'pila',
 105: 'rinseFinished',
 108: 'rinseStopped',
 120: 'placeCup',
 121: 'removeCup',
 122: 'closeLid',
 123: 'openLid',
 124: 'addWater',
 125: 'insertChamber',
 126: 'nozzleNotDetected',
 127: 'errorOccurred',
 128: 'continue',
 129: 'processCancelled',
 130: 'nextCup',
 131: 'cupRemoved',
 132: 'placeDescalingAdapter',
 133: 'checkingSystem',
 227: 'valveClosing',
 228: 'valveOpening',
 233: 'firmwareUpdate'}

PHASE_TEXT = {'de': {'adapterInstalled': 'Adapter eingesetzt?',
        'addDescaler': 'Entkalker hinzufügen',
        'addWater': 'Bitte Wasser hinzufügen',
        'checkingSystem': 'System wird geprüft...',
        'closeLid': 'Bitte Deckel schließen',
        'continue': 'Weiter?',
        'cupRemoved': 'Tasse entfernt',
        'descaleWithAdapter': 'Mit Adapter entkalken?',
        'descalerInCup': 'Entkalker in der Tasse?',
        'descalingFinished': 'Entkalkung abgeschlossen',
        'descalingInProgress': 'Entkalkung läuft...',
        'descalingIntro': 'Entkalkung',
        'dispensing': 'Ausgabe',
        'enjoy': 'Guten Tee!',
        'errorOccurred': 'Ein Fehler ist aufgetreten',
        'fillingUp': 'Wasser wird gefüllt',
        'firmwareUpdate': 'Firmware-Update',
        'freshWaterAttached': 'Frischwassertank eingesetzt?',
        'homeScreen': 'Bereit',
        'insertChamber': 'Bitte Brühkammer einsetzen',
        'installAdapter': 'Bitte Adapter einsetzen',
        'lidInstalled': 'Deckel aufgesetzt?',
        'loadingColdWater': 'Kaltwasser laden',
        'loadingHotWater': 'Heißwasser laden',
        'nextCup': 'Nächste Tasse?',
        'nozzleNotDetected': 'Düse nicht erkannt',
        'openLid': 'Bitte Deckel öffnen',
        'pila': 'PILA',
        'placeCup': 'Bitte Tasse hinstellen',
        'placeDescalingAdapter': 'Entkalkungsadapter einsetzen',
        'processCancelled': 'Vorgang abgebrochen',
        'refillWaterTank': 'Bitte Wassertank auffüllen',
        'removeCup': 'Bitte Tasse entfernen',
        'rinseDelay': 'Spülpause',
        'rinseFinished': 'Spülvorgang abgeschlossen',
        'rinseStopped': 'Spülvorgang gestoppt',
        'rinseSystem': 'Bitte System spülen',
        'rinsing': 'Spülen...',
        'scanQrCode': 'Bitte QR-Code scannen',
        'serving': 'Servieren',
        'steeping': 'Ziehen lassen',
        'valveClosing': 'Ventil schließt',
        'valveOpening': 'Ventil öffnet'},
 'en': {'adapterInstalled': 'Adapter Installed?',
        'addDescaler': 'Add Descaler',
        'addWater': 'Please Add Water',
        'checkingSystem': 'Checking System...',
        'closeLid': 'Please Close Lid',
        'continue': 'Continue?',
        'cupRemoved': 'Cup Removed',
        'descaleWithAdapter': 'Descale With Adapter?',
        'descalerInCup': 'Descaler in Cup?',
        'descalingFinished': 'Descaling Finished',
        'descalingInProgress': 'Descaling in Progress',
        'descalingIntro': 'Descaling Intro',
        'dispensing': 'Dispensing',
        'enjoy': 'Enjoy Your Tea!',
        'errorOccurred': 'An Error Occurred',
        'fillingUp': 'Filling Up',
        'firmwareUpdate': 'Firmware Update',
        'freshWaterAttached': 'Fresh Water Tank Attached?',
        'homeScreen': 'Ready',
        'insertChamber': 'Please Insert Chamber',
        'installAdapter': 'Please Install Adapter',
        'lidInstalled': 'Is Lid Installed?',
        'loadingColdWater': 'Loading Cold Water',
        'loadingHotWater': 'Loading Hot Water',
        'nextCup': 'Next Cup?',
        'nozzleNotDetected': 'Nozzle Not Detected',
        'openLid': 'Please Open Lid',
        'pila': 'PILA',
        'placeCup': 'Please Place Cup',
        'placeDescalingAdapter': 'Place Descaling Adapter',
        'processCancelled': 'Process Cancelled',
        'refillWaterTank': 'Please Refill Water Tank',
        'removeCup': 'Please Remove Cup',
        'rinseDelay': 'Rinse Delay',
        'rinseFinished': 'Rinse Finished',
        'rinseStopped': 'Rinse Stopped',
        'rinseSystem': 'Please Rinse System',
        'rinsing': 'Rinsing',
        'scanQrCode': 'Please Scan QR Code',
        'serving': 'Serving',
        'steeping': 'Steeping',
        'valveClosing': 'Valve Closing',
        'valveOpening': 'Valve Opening'}}

STATUS_TEXT = {
    "de": {1: "Bereit", 2: "Menü", 3: "Einstellungen", 4: "Einstellungen", 5: "Brühen",
           6: "Ausgabe", 7: "Timer", 8: "Kalter Tee", 9: "Split Cup", 10: "Mehrfachaufguss",
           11: "Hinweis", 12: "Warnung", 13: "Fehler", 14: "Heißer Tee", 15: "Testmodus",
           16: "Testmodus", 17: "Testmodus", 18: "Testmodus", 19: "Testmodus",
           20: "Testmodus", 21: "Trocknen", 22: "Entkalken", 23: "Deckel-Erinnerung",
           24: "Bluetooth-Menü"},
    "en": {1: "Ready", 2: "Menu", 3: "Setup", 4: "Setup", 5: "Brewing", 6: "Dispensing",
           7: "Timer", 8: "Cold tea", 9: "Split cup", 10: "Multi steeping", 11: "Info",
           12: "Warning", 13: "Error", 14: "Hot tea", 15: "Test mode", 16: "Test mode",
           17: "Test mode", 18: "Test mode", 19: "Test mode", 20: "Test mode",
           21: "Drying", 22: "Descaling", 23: "Lid reminder", 24: "Bluetooth menu"},
}
# Eigene Texte für Bildschirme, für die die App keinen Text hat
EXTRA_PHASE_TEXT = {
    "de": {1: "Sprachauswahl", 3: "Start", 5: "Brühzeit einstellen", 6: "Temperatur einstellen",
           7: "Wassermenge einstellen", 10: "Preset", 11: "Mehrfachaufguss",
           12: "Mehrfachaufguss einstellen", 14: "Timer", 15: "Timer läuft",
           16: "Kalter Tee", 17: "Kalter Tee einstellen", 18: "Split Cup", 19: "Heißer Tee",
           20: "Heißer Tee einstellen", 40: "Einstellungen", 110: "Bluetooth",
           112: "Bluetooth-Kopplung", 166: "Trocknen"},
    "en": {1: "Language selection", 3: "Intro", 5: "Set brew time", 6: "Set temperature",
           7: "Set water amount", 10: "Preset", 11: "Multi steeping",
           12: "Edit multi steeping", 14: "Timer", 15: "Timer running", 16: "Cold tea",
           17: "Edit cold tea", 18: "Split cup", 19: "Hot tea", 20: "Edit hot tea",
           40: "Setup", 110: "Bluetooth", 112: "Bluetooth pairing", 166: "Drying"},
}

MESSAGE_STATUSES = (11, 12, 13)   # Hinweis / Warnung / Fehler -> Meldungstext anzeigen

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


def cancel_command() -> bytes:
    return build_frame(CMD_CANCEL, b"", 4)


def button_command(button: int) -> bytes:
    return build_frame(CMD_BUTTON_PRESS, bytes([button]), 5)
