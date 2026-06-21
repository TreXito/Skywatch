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
# Genuinely uncommon "stop and look" aircraft worldwide. Deliberately tight:
# everyday widebodies (747-400, 757, 767, A330/A340-300) are NOT rare. Extend via
# config `rare_typecodes` if you want more.
RARE_TYPECODES = {
    # Outsized / special cargo
    "A124": "Antonov An-124 Ruslan",
    "A225": "Antonov An-225 Mriya",
    "AN22": "Antonov An-22",
    "AN12": "Antonov An-12",
    "AN26": "Antonov An-26",
    "A30B": "Airbus A300 (classic)",
    "BLCF": "Boeing 747 Dreamlifter",
    "A3ST": "Airbus A300-600ST Beluga",
    "A337": "Airbus BelugaXL",
    "SGUP": "Aero Spacelines Super Guppy",
    # Iconic / retired-era
    "A388": "Airbus A380-800",
    "B748": "Boeing 747-8",
    "B741": "Boeing 747-100",
    "B742": "Boeing 747-200",
    "B743": "Boeing 747-300",
    "B74S": "Boeing 747SP",
    "CONC": "Concorde",
    "DC10": "McDonnell Douglas DC-10",
    "MD11": "McDonnell Douglas MD-11",
    "L101": "Lockheed L-1011 TriStar",
    "A345": "Airbus A340-500",
    "A346": "Airbus A340-600",
    "B703": "Boeing 707",
    "VC10": "Vickers VC10",
    # Russian / rare types in the West
    "IL76": "Ilyushin Il-76",
    "IL62": "Ilyushin Il-62",
    "IL96": "Ilyushin Il-96",
    "IL18": "Ilyushin Il-18",
    "T154": "Tupolev Tu-154",
    "T204": "Tupolev Tu-204",
    "AN72": "Antonov An-72",
    "A40": "Beriev A-40/Be-200",
}

# --- Special "stop everything" aircraft -------------------------------------
# Curated icons of aviation – warbirds, outsize cargo, spyplanes, command posts.
# Detected by typecode; the description is shown as the alert reason. These rank
# above generic rare/military finds.
SPECIAL_TYPECODES = {
    # Outsize / special cargo
    "A37X": "Airbus BelugaXL — 1 of only 6, flies between Airbus plants",
    "A337": "Airbus BelugaXL — outsize cargo whale",
    "A3ST": "Airbus Beluga (original) — being retired",
    "B74R": "Boeing 747 Dreamlifter — 1 of only 4 outsize freighters",
    "BLCF": "Boeing 747 Dreamlifter — outsize freighter",
    "A124": "Antonov An-124 Ruslan — one of the largest aircraft on Earth",
    "A225": "Antonov An-225 Mriya — the largest aircraft ever built",
    # WWII / warbirds
    "LANC": "Avro Lancaster — WWII heavy bomber, ~2 airworthy worldwide",
    "SPIT": "Supermarine Spitfire — Battle of Britain fighter (1940)",
    "P51": "P-51 Mustang — WWII long-range escort fighter",
    "B17": "B-17 Flying Fortress — WWII bomber, ~1 airworthy left",
    "B29": "B-29 Superfortress — 'FIFI', the only airworthy one",
    "DC3": "Douglas DC-3 — the airliner that started it all (1940s)",
    "C47": "Douglas C-47 Skytrain — WWII/D-Day transport (DC-3 military)",
    # Jet trainers with history
    "L39": "Aero L-39 Albatros — the Eastern Bloc's standard jet trainer",
    "TS11": "PZL TS-11 Iskra — Poland's home-grown jet trainer",
    "MB33": "Aermacchi MB-339 — jet of the Frecce Tricolori display team",
    "M339": "Aermacchi MB-339 — Frecce Tricolori display jet",
    # Reconnaissance / spy
    "U2": "Lockheed U-2 — Cold War spyplane, flies at ~21 km",
    "RC35": "Boeing RC-135 Rivet Joint — the West's top SIGINT platform",
    "RC135": "Boeing RC-135 Rivet Joint — signals-intelligence recon",
    "RQ4": "RQ-4 Global Hawk — high-altitude recon drone over E. Europe",
    "GHWK": "RQ-4 Global Hawk — high-altitude recon drone",
    # VIP / command
    "E4": "Boeing E-4B Nightwatch — airborne nuclear command post (Doomsday)",
    "E6": "Boeing E-6B Mercury — nuclear command relay (TACAMO)",
    "E6B": "Boeing E-6B Mercury — nuclear command relay (TACAMO)",
}

# Only these truly extreme aircraft earn an @mention ping (a DC-3 or a common
# warbird does NOT). The broader SPECIAL_* lists still flag/alert; this is tighter.
PING_TYPECODES = {
    "E4", "E6", "E6B",                      # airborne nuclear command posts
    "U2", "RC35", "RC135", "RQ4", "GHWK",   # strategic recon / spyplanes
    "A124", "A225",                          # Antonov outsize
    "A37X", "A337", "A3ST", "B74R", "BLCF",  # Beluga / Dreamlifter
    "CONC",                                  # Concorde
    "B29", "B17", "LANC",                    # 1-of-a-kind WWII heavies
}
PING_CALLSIGNS = {"NIGHTWATCH", "IRON99", "ORDER"}  # Doomsday / nuclear C3

# Callsign prefixes that mark a notable flight, with context shown as the reason.
SPECIAL_CALLSIGNS = {
    "NIGHTWATCH": "E-4B 'Nightwatch' — airborne nuclear command post",
    "IRON99": "E-4B 'Nightwatch' — airborne nuclear command post",
    "ORDER": "E-6B Mercury — nuclear command relay",
    "SPAR": "US Air Force VIP / government flight",
    "SAM": "US Air Force Special Air Mission (VIP)",
    "NATO": "NATO flight",
    "MAGMA": "NATO AWACS / support",
    "FORTE": "RQ-4 Global Hawk — recon drone",
    "HOMER": "RC-135 — signals-intelligence recon",
    "JAKE": "Reconnaissance flight",
    "IRAN": "Iranian state flight",
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

# --- HTTP ------------------------------------------------------------------
USER_AGENT = "SkyWatch/1.1 (+https://github.com/skywatch/skywatch)"

# --- External data sources --------------------------------------------------
RAINVIEWER_MAPS_URL = "https://api.rainviewer.com/public/weather-maps.json"
METAR_API_URL = "https://aviationweather.gov/api/data/metar"
PLANESPOTTERS_HEX_URL = "https://api.planespotters.net/pub/photos/hex/{hex}"
OURAIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# Default news feeds scanned for the conflict/hazard-zone overlay. Users can
# override or extend via `news_feeds` in config.yaml.
DEFAULT_NEWS_FEEDS = [
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "http://rss.cnn.com/rss/edition_world.rss",
    "https://www.reutersagency.com/feed/?best-topics=political-general&post_type=best",
]

# Words in a headline that flag it as conflict/hazard related.
CONFLICT_KEYWORDS = [
    "airstrike", "air strike", "missile", "drone strike", "shelling", "rocket",
    "war", "warzone", "conflict", "invasion", "offensive", "ceasefire", "clashes",
    "militant", "insurgent", "airspace", "no-fly", "shot down", "downed",
    "explosion", "bombing", "bombardment", "fighter jet", "artillery", "troops",
    "border clash", "incursion", "evacuat", "siege", "frontline", "front line",
]

# Region gazetteer: name -> (lat, lon, radius_km, [aliases]). Used to geocode
# news headlines into map regions for the conflict/hazard overlay. Curated toward
# conflict-prone regions plus major countries; users can add static zones too.
GAZETTEER = {
    "Ukraine": (49.0, 32.0, 350, ["ukraine", "ukrainian", "kyiv", "kharkiv", "donetsk", "luhansk", "zaporizhzhia", "crimea", "mariupol", "odesa", "bakhmut"]),
    "Russia": (55.75, 37.62, 300, ["russia", "russian", "moscow", "belgorod", "kursk"]),
    "Israel": (31.5, 34.9, 90, ["israel", "israeli", "tel aviv", "jerusalem"]),
    "Gaza": (31.45, 34.39, 30, ["gaza", "rafah", "khan younis"]),
    "West Bank": (32.0, 35.3, 40, ["west bank", "ramallah", "jenin", "nablus"]),
    "Lebanon": (33.85, 35.5, 70, ["lebanon", "lebanese", "beirut", "hezbollah"]),
    "Syria": (34.8, 38.0, 250, ["syria", "syrian", "damascus", "aleppo", "idlib"]),
    "Iraq": (33.3, 44.4, 250, ["iraq", "iraqi", "baghdad", "mosul", "erbil"]),
    "Iran": (35.7, 51.4, 350, ["iran", "iranian", "tehran", "isfahan"]),
    "Yemen": (15.4, 44.2, 250, ["yemen", "yemeni", "houthi", "sanaa", "red sea"]),
    "Sudan": (15.5, 32.5, 350, ["sudan", "sudanese", "khartoum", "darfur", "rsf"]),
    "Somalia": (2.05, 45.34, 250, ["somalia", "somali", "mogadishu", "al-shabaab", "al shabaab"]),
    "Libya": (32.9, 13.2, 300, ["libya", "libyan", "tripoli", "benghazi"]),
    "Mali": (17.6, -3.0, 400, ["mali", "malian", "bamako", "sahel"]),
    "Niger": (17.6, 8.0, 400, ["niger", "niamey"]),
    "Burkina Faso": (12.4, -1.5, 300, ["burkina faso", "ouagadougou"]),
    "Nigeria": (9.08, 8.68, 350, ["nigeria", "nigerian", "abuja", "boko haram"]),
    "Ethiopia": (9.0, 39.0, 350, ["ethiopia", "ethiopian", "addis ababa", "tigray", "amhara"]),
    "DR Congo": (-2.5, 27.0, 300, ["congo", "drc", "goma", "kinshasa", "m23"]),
    "Afghanistan": (34.5, 69.2, 350, ["afghanistan", "afghan", "kabul", "kandahar", "taliban"]),
    "Pakistan": (33.7, 73.1, 300, ["pakistan", "pakistani", "islamabad", "waziristan"]),
    "Myanmar": (19.75, 96.1, 350, ["myanmar", "burma", "naypyidaw", "yangon", "rakhine"]),
    "North Korea": (39.0, 125.75, 150, ["north korea", "pyongyang", "dprk"]),
    "Taiwan": (23.7, 121.0, 150, ["taiwan", "taiwanese", "taipei", "taiwan strait"]),
    "South China Sea": (13.0, 114.0, 500, ["south china sea", "spratly", "paracel"]),
    "Venezuela": (10.5, -66.9, 250, ["venezuela", "venezuelan", "caracas"]),
    "Haiti": (18.6, -72.3, 80, ["haiti", "haitian", "port-au-prince"]),
    "Colombia": (4.7, -74.1, 350, ["colombia", "colombian", "bogota"]),
    "Mexico": (19.43, -99.13, 400, ["mexico", "mexican", "sinaloa", "cartel"]),
    "Armenia": (40.18, 44.51, 120, ["armenia", "armenian", "yerevan", "nagorno", "karabakh"]),
    "Azerbaijan": (40.41, 49.87, 150, ["azerbaijan", "azerbaijani", "baku"]),
    "Georgia (country)": (41.7, 44.8, 120, ["tbilisi", "abkhazia", "south ossetia"]),
    "United States": (38.9, -77.04, 400, ["united states", "u.s.", "usa", "washington", "pentagon"]),
    "United Kingdom": (51.5, -0.13, 150, ["united kingdom", "britain", "british", "london"]),
    "France": (48.85, 2.35, 250, ["france", "french", "paris"]),
    "Germany": (52.52, 13.40, 250, ["germany", "german", "berlin"]),
    "China": (39.9, 116.4, 500, ["china", "chinese", "beijing"]),
    "India": (28.6, 77.2, 500, ["india", "indian", "new delhi", "kashmir"]),
    "Egypt": (30.04, 31.24, 300, ["egypt", "egyptian", "cairo", "sinai"]),
    "Turkey": (39.93, 32.86, 350, ["turkey", "turkish", "ankara", "istanbul"]),
    "Poland": (52.23, 21.01, 250, ["poland", "polish", "warsaw"]),
}

# --- OpenSky endpoints ------------------------------------------------------
OPENSKY_STATES_URL = "https://opensky-network.org/api/states/all"
OPENSKY_TOKEN_URL = (
    "https://auth.opensky-network.org/auth/realms/opensky-network/"
    "protocol/openid-connect/token"
)
OPENSKY_METADATA_DB_URL = "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv"
