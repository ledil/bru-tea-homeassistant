"""Verbindung und Logik für eine BRU-Maschine."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from . import protocol as p
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = 5          # Sekunden zwischen Statusabfragen während des Brühens
IDLE_DISCONNECT = 20       # Sekunden Standby, bevor getrennt wird


class BruDevice:
    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        self.hass = hass
        self.address = address
        self.name = name
        self.firmware: str | None = None
        self.status: int | None = None
        self.substatus: int | None = None
        self.last_result: str | None = None
        self.connected = False
        self.settings = {"temperature": "80 °C", "time": "3:00", "water": "200 ml",
                         "rinse": False}
        self._client = None
        self._lock = asyncio.Lock()
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._monitor: asyncio.Task | None = None
        self._listeners: list[Callable[[], None]] = []
        self.available = False          # Maschine sendet Bluetooth-Signale
        self.status_source: str | None = None   # "advertising" | "connected"
        self.rssi: int | None = None
        self._unsubs: list[Callable[[], None]] = []

    # ---- Passiver Status aus Bluetooth-Advertisements -----------------------
    @callback
    def async_start(self) -> None:
        """Advertisements abonnieren (keine Verbindung nötig)."""
        self._unsubs.append(bluetooth.async_register_callback(
            self.hass, self._on_advertisement,
            bluetooth.BluetoothCallbackMatcher(address=self.address, connectable=False),
            bluetooth.BluetoothScanningMode.ACTIVE))
        self._unsubs.append(bluetooth.async_track_unavailable(
            self.hass, self._on_unavailable, self.address, connectable=False))
        last = bluetooth.async_last_service_info(self.hass, self.address,
                                                 connectable=False)
        if last is not None:
            self._on_advertisement(last, None)

    @callback
    def async_stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    @staticmethod
    def parse_advertisement(info) -> tuple[int, int] | None:
        """Wie parseAdvertisingData der App: Puffer = Firmen-ID (2 Byte LE) +
        Herstellerdaten, Status = Byte 3, Phase = Byte 4. Fallback: Service-Daten."""
        candidates = [cid.to_bytes(2, "little") + bytes(data)
                      for cid, data in (info.manufacturer_data or {}).items()]
        candidates += [bytes(data) for uuid_, data in (info.service_data or {}).items()
                       if uuid_.lower() == p.SERVICE_UUID]
        fallback = None
        for raw in candidates:
            if len(raw) < 5:
                continue
            if raw[3] in p.STATUS:
                return raw[3], raw[4]
            fallback = fallback or (raw[3], raw[4])
        return fallback

    @callback
    def _on_advertisement(self, info, _change) -> None:
        self.rssi = info.rssi
        changed = not self.available
        self.available = True
        if not self.connected:          # verbundener Status hat Vorrang (wie in der App)
            parsed = self.parse_advertisement(info)
            if parsed is not None and (parsed != (self.status, self.substatus)
                                       or self.status_source != "advertising"):
                self.status, self.substatus = parsed
                self.status_source = "advertising"
                changed = True
        if changed:
            self._notify_listeners()

    @callback
    def _on_unavailable(self, _info) -> None:
        self.available = False
        if not self.connected:
            self.status = self.substatus = None
            self.status_source = None
        self._notify_listeners()

    # ---- Listener für Entitäten -------------------------------------------
    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.address)},
            connections={(CONNECTION_BLUETOOTH, self.address)},
            name=self.name, manufacturer="BRU", model="Maker One",
            sw_version=self.firmware)

    @callback
    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)
        return lambda: self._listeners.remove(cb)

    @callback
    def _notify_listeners(self) -> None:
        for cb in list(self._listeners):
            cb()

    @property
    def status_name(self) -> str | None:
        return None if self.status is None else p.STATUS.get(self.status, str(self.status))

    @property
    def substatus_name(self) -> str | None:
        return None if self.substatus is None else p.SUBSTATUS.get(self.substatus,
                                                                   str(self.substatus))

    # ---- BLE ----------------------------------------------------------------
    def _on_notify(self, _sender, data: bytearray) -> None:
        data = bytes(data)
        _LOGGER.debug("BRU <- %s", data.hex(" "))
        if len(data) > 4 and data[2] == p.RSP_STATUS:
            self.status, self.substatus = data[3], data[4]
            self.status_source = "connected"
            self._notify_listeners()
        elif len(data) > 3 and data[2] == p.RSP_BREW_RESULT:
            self.last_result = p.BREW_RESULT.get(data[3], f"Unbekannt ({data[3]})")
            self._notify_listeners()
        self._queue.put_nowait(data)

    def _on_disconnect(self, _client) -> None:
        self._client = None
        self.connected = False
        self.hass.loop.call_soon_threadsafe(self._notify_listeners)

    async def _ensure_connected(self):
        if self._client is not None and self._client.is_connected:
            return self._client
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True)
        if ble_device is None:
            raise HomeAssistantError(f"{self.name} ist nicht in Bluetooth-Reichweite")
        try:
            client = await establish_connection(
                BleakClientWithServiceCache, ble_device, self.name,
                disconnected_callback=self._on_disconnect, max_attempts=3)
        except (BleakError, TimeoutError) as err:
            raise HomeAssistantError(f"Verbindung fehlgeschlagen: {err}") from err
        try:
            raw = await client.read_gatt_char(p.FW_REV_UUID)
            self.firmware = raw.decode("utf-8", "ignore").replace("\x00", "").strip()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Firmware nicht lesbar: %s", err)
        self._queue = asyncio.Queue()
        await client.start_notify(p.NOTIFY_UUID, self._on_notify)
        self._client = client
        self.connected = True
        try:
            await self._write(p.set_time_command())
        except BleakError as err:
            await self._disconnect()
            raise HomeAssistantError(
                "Maschine lehnt Befehle ab – nicht gekoppelt. Integration entfernen und neu hinzufügen, um mit Code zu koppeln.") from err
        self._notify_listeners()
        return client

    async def _write(self, frame: bytes) -> None:
        _LOGGER.debug("BRU -> %s", frame.hex(" "))
        await self._client.write_gatt_char(p.WRITE_UUID, frame, response=False)

    async def _wait_for(self, cmd_id: int, timeout: float) -> bytes | None:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while (left := end - loop.time()) > 0:
            try:
                data = await asyncio.wait_for(self._queue.get(), left)
            except TimeoutError:
                return None
            if len(data) > 3 and data[2] == cmd_id:
                return data
        return None

    async def _disconnect(self) -> None:
        client, self._client = self._client, None
        self.connected = False
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._notify_listeners()

    # ---- Öffentliche Aktionen ----------------------------------------------
    async def async_refresh(self) -> None:
        async with self._lock:
            keep = self._monitor is not None and not self._monitor.done()
            await self._ensure_connected()
            await self._write(p.status_command())
            await self._wait_for(p.RSP_STATUS, 5)
            if not keep:
                await self._disconnect()

    async def async_brew(self, temperature=None, brew_time=None, water=None,
                         rinse=None, buzzer=True) -> None:
        s = self.settings
        temperature = temperature if temperature is not None else s["temperature"]
        brew_time = brew_time if brew_time is not None else s["time"]
        water = water if water is not None else s["water"]
        rinse = s["rinse"] if rinse is None else rinse

        if self._monitor is not None and not self._monitor.done():
            raise HomeAssistantError("Es läuft bereits ein Brühvorgang")

        async with self._lock:
            await self._ensure_connected()
            try:
                frame = p.brew_command(p.temp_code(temperature), p.time_code(brew_time),
                                       p.water_code(water, self.firmware), rinse=rinse,
                                       buzzer=buzzer, fw=self.firmware)
            except ValueError as err:
                await self._disconnect()
                raise HomeAssistantError(str(err)) from err
            await self._write(frame)
            res = await self._wait_for(p.RSP_BREW_RESULT, 8)
            if res is not None and res[3] != 0:
                await self._disconnect()
                raise HomeAssistantError(f"Maschine meldet: {self.last_result}")
            if res is None:
                _LOGGER.warning("Keine Brüh-Bestätigung erhalten, verfolge Status trotzdem")

        self._monitor = self.hass.async_create_background_task(
            self._monitor_brew(), f"{DOMAIN}_monitor_{self.address}")

    async def _monitor_brew(self) -> None:
        """Status abfragen, bis die Maschine wieder im Standby ist."""
        standby_since = None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 75 * 60
        try:
            while loop.time() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                async with self._lock:
                    if self._client is None or not self._client.is_connected:
                        await self._ensure_connected()
                    await self._write(p.status_command())
                    await self._wait_for(p.RSP_STATUS, 4)
                if self.status == p.STATUS_STANDBY:
                    standby_since = standby_since or loop.time()
                    if loop.time() - standby_since > IDLE_DISCONNECT:
                        break
                else:
                    standby_since = None
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Statusverfolgung abgebrochen: %s", err)
        finally:
            async with self._lock:
                await self._disconnect()

    async def async_cancel(self) -> None:
        """Laufenden Vorgang abbrechen (Befehl 0x42, wie die App)."""
        async with self._lock:
            temp = self._client is None
            await self._ensure_connected()
            await self._write(p.cancel_command())
            await asyncio.sleep(0.3)
            await self._write(p.status_command())
            await self._wait_for(p.RSP_STATUS, 3)
            if temp and (self._monitor is None or self._monitor.done()):
                await self._disconnect()

    async def async_shutdown(self) -> None:
        self.async_stop()
        if self._monitor is not None:
            self._monitor.cancel()
        await self._disconnect()
