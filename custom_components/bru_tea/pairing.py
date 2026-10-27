"""BLE-Pairing mit Passkey direkt über BlueZ (D-Bus) – ohne SSH/bluetoothctl.

Funktioniert mit dem lokalen Bluetooth-Adapter von Home Assistant (HA OS,
Supervised, Container mit /run/dbus). Nicht über ESPHome-Proxys.
"""
# Hinweis: KEIN "from __future__ import annotations" – dbus-fast liest die
# D-Bus-Signaturen aus den Annotationen ('o', 'u', ...).
import asyncio
import logging

_LOGGER = logging.getLogger(__name__)

AGENT_PATH = "/org/homeassistant/bru_tea/agent"

try:
    from dbus_fast import BusType, Message, MessageType, Variant
    from dbus_fast.aio import MessageBus
    from dbus_fast.service import ServiceInterface, method

    HAVE_DBUS = True
except ImportError:  # pragma: no cover
    HAVE_DBUS = False


class PairingError(Exception):
    pass


if HAVE_DBUS:

    class _Agent(ServiceInterface):
        def __init__(self, session: "BruPairing"):
            super().__init__("org.bluez.Agent1")
            self._s = session

        @method()
        def Release(self):
            pass

        @method()
        async def RequestPasskey(self, device: "o") -> "u":
            return int(await self._s._wait_for_code())

        @method()
        async def RequestPinCode(self, device: "o") -> "s":
            return str(await self._s._wait_for_code())

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):
            self._s.displayed_code = f"{passkey:06d}"

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):
            self._s.displayed_code = pincode

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u"):
            self._s.displayed_code = f"{passkey:06d}"

        @method()
        def RequestAuthorization(self, device: "o"):
            pass

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):
            pass

        @method()
        def Cancel(self):
            self._s._cancelled()


class BruPairing:
    """Ablauf: start() -> (code_requested) -> submit_code() -> wait_done()."""

    def __init__(self, address: str) -> None:
        self.address = address.upper()
        self.displayed_code: str | None = None
        self.code_requested = asyncio.Event()
        self._code: asyncio.Future | None = None
        self._bus = None
        self._dev_path: str | None = None
        self._task: asyncio.Task | None = None

    # ---- D-Bus-Helfer -------------------------------------------------------
    async def _call(self, path, iface, member, signature="", body=None, timeout=None):
        msg = Message(destination="org.bluez", path=path, interface=iface,
                      member=member, signature=signature, body=body or [])
        coro = self._bus.call(msg)
        reply = await (asyncio.wait_for(coro, timeout) if timeout else coro)
        if reply.message_type == MessageType.ERROR:
            raise PairingError(f"{reply.error_name}: {reply.body[0] if reply.body else ''}")
        return reply.body

    async def _find_device(self) -> tuple[str, bool]:
        (objects,) = await self._call("/", "org.freedesktop.DBus.ObjectManager",
                                      "GetManagedObjects")
        for path, ifaces in objects.items():
            dev = ifaces.get("org.bluez.Device1")
            if dev and dev["Address"].value.upper() == self.address:
                return path, bool(dev.get("Paired", Variant("b", False)).value)
        raise PairingError("Maschine ist dem Bluetooth-Adapter nicht bekannt – "
                           "ist sie eingeschaltet und in Reichweite?")

    # ---- Ablauf ---------------------------------------------------------------
    async def start(self) -> bool:
        """Startet das Pairing. True = schon gekoppelt (nichts zu tun)."""
        if not HAVE_DBUS:
            raise PairingError("dbus-fast nicht verfügbar")
        try:
            self._bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        except Exception as err:  # noqa: BLE001
            raise PairingError(f"Kein Zugriff auf D-Bus/BlueZ: {err}") from err
        self._dev_path, paired = await self._find_device()
        if paired:
            await self.close()
            return True
        self._code = asyncio.get_running_loop().create_future()
        self._bus.export(AGENT_PATH, _Agent(self))
        await self._call("/org/bluez", "org.bluez.AgentManager1", "RegisterAgent",
                         "os", [AGENT_PATH, "KeyboardDisplay"])
        self._task = asyncio.create_task(self._pair())
        return False

    async def _pair(self) -> None:
        await self._call(self._dev_path, "org.bluez.Device1", "Pair", timeout=90)
        await self._call(self._dev_path, "org.freedesktop.DBus.Properties", "Set",
                         "ssv", ["org.bluez.Device1", "Trusted", Variant("b", True)])

    async def _wait_for_code(self):
        self.code_requested.set()
        return await self._code

    def _cancelled(self) -> None:
        if self._code and not self._code.done():
            self._code.set_exception(PairingError("Pairing von der Maschine abgebrochen"))

    async def wait_for_request(self, timeout: float = 30) -> str:
        """Wartet, bis ein Code gebraucht wird oder das Pairing fertig ist.
        Rückgabe: 'code' | 'done'."""
        waiter = asyncio.create_task(self.code_requested.wait())
        done, _ = await asyncio.wait({waiter, self._task}, timeout=timeout,
                                     return_when=asyncio.FIRST_COMPLETED)
        if self._task in done:
            waiter.cancel()
            self._task.result()          # wirft PairingError bei Fehler
            return "done"
        if waiter in done:
            return "code"
        waiter.cancel()
        raise PairingError("Zeitüberschreitung – ist der Pairing-Modus an der Maschine aktiv?")

    def submit_code(self, code: str) -> None:
        if self._code and not self._code.done():
            self._code.set_result(int(code))

    async def wait_done(self, timeout: float = 40) -> None:
        try:
            await asyncio.wait_for(asyncio.shield(self._task), timeout)
        except TimeoutError as err:
            raise PairingError("Pairing hat nicht geantwortet") from err

    async def close(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._call(self._dev_path, "org.bluez.Device1", "CancelPairing")
            except Exception:  # noqa: BLE001
                pass
        if self._bus:
            try:
                await self._call("/org/bluez", "org.bluez.AgentManager1",
                                 "UnregisterAgent", "o", [AGENT_PATH])
            except Exception:  # noqa: BLE001
                pass
            try:
                if self._dev_path:   # Verbindung freigeben, HA verbindet sich selbst
                    await self._call(self._dev_path, "org.bluez.Device1", "Disconnect")
            except Exception:  # noqa: BLE001
                pass
            self._bus.disconnect()
            self._bus = None
