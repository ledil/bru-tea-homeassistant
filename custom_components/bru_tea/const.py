DOMAIN = "bru_tea"
PLATFORMS = ["sensor", "select", "switch", "button"]
CUSTOM_TEA = "Eigene Einstellung"
CONF_TEAS = "teas"

# Vorschläge beim ersten Start – unter "Konfigurieren" änderbar
DEFAULT_TEAS = [
    {"id": "gruentee", "name": "Grüntee", "temperature": "80 °C", "time": "2:00",
     "water": "200 ml", "rinse": False},
    {"id": "schwarztee", "name": "Schwarztee", "temperature": "95 °C", "time": "4:00",
     "water": "250 ml", "rinse": False},
    {"id": "weisser_tee", "name": "Weißer Tee", "temperature": "75 °C", "time": "3:00",
     "water": "200 ml", "rinse": False},
    {"id": "kraeutertee", "name": "Kräutertee", "temperature": "Max", "time": "6:00",
     "water": "250 ml", "rinse": False},
]
