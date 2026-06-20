"""Built-in reference data: military typecodes, rare types, squawks, categories.

These are sensible defaults baked into the app. Users can extend most of them via
config.yaml (military_typecodes, rare_typecodes, military_keywords) without editing code.
"""

# --- Emergency squawk codes -------------------------------------------------
EMERGENCY_SQUAWKS = {
    "7500": "Hijack",
    "7600": "Radio Failure",
    "7700": "General Emergency",
}

# --- Notable military typecodes ---------------------------------------------
# Not exhaustive – a curated list of frequently-interesting military types.
MILITARY_TYPECODES = {
    "C135", "K35R", "K35E", "R135", "RC135", "E3CF", "E3TF", "E3SE", "E3DF",
    "A400", "C17", "C130", "C30J", "F16", "F15", "F18", "F22", "F35",
    "EF2K", "EUFI", "E6", "E6B", "P8", "P8A", "P3", "B52", "B1", "B2",
    "H47", "H60", "H64", "AH64", "UH60", "CH47", "V22", "MV22", "CV22",
    "A10", "AV8B", "TOR", "TORN", "GLF5", "C5M", "C5", "C160", "A124",
    "E8", "U2", "RQ4", "MQ9", "MQ1", "GHWK", "NIMR", "VC10", "TRIS",
    "EUR", "RFAL", "MIG", "SU27", "SU30", "SU34", "SU35", "AN12", "AN26",
    "AN72", "IL76", "IL78", "TU95", "TU22", "TU16", "KC10", "KC46", "KC30",
    "C40", "C32", "C37", "C20", "VC25", "E2", "E2D", "EA18", "EA6",
}

# Operator/owner keyword fragments that indicate a military/government aircraft.
MILITARY_KEYWORDS = [
    "air force", "navy", "army", "marine", "luftwaffe", "bundesheer",
    "nato", "royal air force", "raf ", "usaf", "us air force", "military",
    "ministry of defence", "ministry of defense", "defence", "defense forces",
    "coast guard", "border guard", "gendarmerie", "national guard",
    "aeronautica militare", "armee de l", "fuerza aerea", "luftwaffe",
    "polizei", "police", "heeresflieger", "marineflieger",
]

# Callsign prefixes commonly used by military / government flights.
MILITARY_CALLSIGN_PREFIXES = [
    "RCH",   # Reach (USAF)
    "CNV",   # US Navy
    "AME",   # USAF Air Mobility
    "DOOM", "JAKE", "SLAM",  # tactical
    "GAF",   # German Air Force
    "IAM",   # Italian Air Force
    "FAF",   # French Air Force
    "NATO", "MAGMA", "BARON",
    "ASCOT", "RRR",  # RAF
    "PLF",   # Polish AF
    "HUNTER", "RAPTOR",
]

# --- Rare / interesting typecodes -------------------------------------------
# Aircraft that are uncommon enough to be worth an alert when seen.
RARE_TYPECODES = {
    "A124": "Antonov An-124 Ruslan",
    "A225": "Antonov An-225 Mriya",
    "A388": "Airbus A380-800",
    "A380": "Airbus A380",
    "B748": "Boeing 747-8",
    "B744": "Boeing 747-400",
    "B741": "Boeing 747-100",
    "B742": "Boeing 747-200",
    "B743": "Boeing 747-300",
    "B752": "Boeing 757-200",
    "B753": "Boeing 757-300",
    "CONC": "Concorde",
    "DC10": "McDonnell Douglas DC-10",
    "MD11": "McDonnell Douglas MD-11",
    "L101": "Lockheed L-1011 TriStar",
    "A342": "Airbus A340-200",
    "A343": "Airbus A340-300",
    "A345": "Airbus A340-500",
    "A346": "Airbus A340-600",
    "B703": "Boeing 707",
    "IL76": "Ilyushin Il-76",
    "AN12": "Antonov An-12",
    "AN22": "Antonov An-22",
    "BLCF": "Boeing 747 Dreamlifter",
    "A337": "Airbus BelugaXL",
    "BELU": "Airbus Beluga",
}

# --- OpenSky category codes -------------------------------------------------
# index → label, per the OpenSky state vector `category` field.
OPENSKY_CATEGORIES = {
    0: "No information",
    1: "No ADS-B category",
    2: "Light (<15500 lbs)",
    3: "Small (15500-75000 lbs)",
    4: "Large (75000-300000 lbs)",
    5: "High Vortex Large",
    6: "Heavy (>300000 lbs)",
    7: "High Performance",
    8: "Rotorcraft",
    9: "Glider / sailplane",
    10: "Lighter-than-air",
    11: "Parachutist / skydiver",
    12: "Ultralight / hang-glider",
    13: "Reserved",
    14: "UAV / drone",
    15: "Space / trans-atmospheric",
    16: "Surface – emergency vehicle",
    17: "Surface – service vehicle",
    18: "Point obstacle",
    19: "Cluster obstacle",
    20: "Line obstacle",
}

# Rotorcraft / helicopter detection
HELICOPTER_CATEGORY = 8
HELICOPTER_TYPECODES = {
    "H47", "H60", "H64", "AH64", "UH60", "CH47", "EC35", "EC45", "EC30",
    "EC20", "EC55", "EC75", "EC25", "AS50", "AS55", "AS65", "B06", "B407",
    "B412", "B429", "B505", "R22", "R44", "R66", "A109", "A119", "A139",
    "A169", "A189", "S76", "S92", "H125", "H130", "H135", "H145", "H155",
    "H160", "H175", "H215", "H225", "BK17", "EH10", "MI8", "MI17", "MI24",
}

# Surface vehicles & balloons (by OpenSky category)
GROUND_VEHICLE_CATEGORIES = {16, 17}
BALLOON_CATEGORY = 10
GLIDER_CATEGORY = 9

# --- Marker categories (used by frontend for coloring) ----------------------
CATEGORY_MILITARY = "military"
CATEGORY_EMERGENCY = "emergency"
CATEGORY_WATCHLIST = "watchlist"
CATEGORY_HELICOPTER = "helicopter"
CATEGORY_RARE = "rare"
CATEGORY_GROUND = "ground"
CATEGORY_BALLOON = "balloon"
CATEGORY_NORMAL = "normal"

# --- Discord embed colors (decimal) -----------------------------------------
COLOR_EMERGENCY = 0xE74C3C   # red
COLOR_MILITARY = 0xF1C40F    # yellow
COLOR_WATCHLIST = 0xF39C12   # orange
COLOR_RARE = 0x3498DB        # blue
COLOR_HOLDING = 0x9B59B6     # purple
COLOR_DEFAULT = 0x95A5A6     # grey

# --- OpenSky endpoints ------------------------------------------------------
OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
OPENSKY_METADATA_DB_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
