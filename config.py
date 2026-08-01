# config.py

DEFAULT_DESIGN = {
    "bg_color": "#0E1117", "title_bg": "#0E1117", "text_color": "#FFFFFF", 
    "border_color": "#FFFFFF", "border_alpha": 0.4, "font_family": "sans-serif",
    "cbar_step": 1, "number_color": "#000000", "number_outline": "#FFFFFF",
    "title_size": 11, "cbar_size": 11, "line_width": 0.8, "watermark": "", 
    "discrete_colors": False, "scientific_cmap": False
}

SIG_WETTER_LABELS = {
    1: "Nebel", 2: "Regen (leicht)", 3: "Regen (mäßig)", 4: "Regen (stark)",
    5: "Schneeregen (leicht)", 6: "Schneeregen (mäßig)", 7: "Schneeregen (stark)",
    8: "Schnee (leicht)", 9: "Schnee (mäßig)", 10: "Schnee (stark)",
    11: "Gewitter (leicht)", 12: "Gewitter (stark)"
}

DEFAULT_CONFIGS = {
    "Temperatur (2m)": [{"value": -10.0, "color": "#313695"}, {"value": 0.0, "color": "#74add1"}, {"value": 15.0, "color": "#fdae61"}, {"value": 30.0, "color": "#d73027"}],
    "Taupunkt (2m)": [{"value": -10.0, "color": "#313695"}, {"value": 0.0, "color": "#74add1"}, {"value": 10.0, "color": "#e0f3f8"}, {"value": 15.0, "color": "#fdae61"}, {"value": 22.0, "color": "#d73027"}],
    "Windböen 10m": [{"value": 0.0, "color": "#ffffff"}, {"value": 40.0, "color": "#ffffcc"}, {"value": 70.0, "color": "#fd8d3c"}, {"value": 100.0, "color": "#e31a1c"}, {"value": 130.0, "color": "#800026"}],
    "Windgeschw. Mittel 10m": [{"value": 0.0, "color": "#ffffff"}, {"value": 20.0, "color": "#ffffcc"}, {"value": 50.0, "color": "#fd8d3c"}, {"value": 80.0, "color": "#e31a1c"}, {"value": 110.0, "color": "#800026"}],
    "Akk. Niederschlag (mm)": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#a6cee3"}, {"value": 10.0, "color": "#1f78b4"}, {"value": 30.0, "color": "#33a02c"}],
    "Niederschlagsrate (mm/h)": [{"value": 0.0, "color": "#ffffff"}, {"value": 0.5, "color": "#a6cee3"}, {"value": 2.0, "color": "#1f78b4"}, {"value": 10.0, "color": "#33a02c"}],
    "Relative Luftfeuchte 2m (%)": [{"value": 0.0, "color": "#ffffcc"}, {"value": 40.0, "color": "#a1d99b"}, {"value": 70.0, "color": "#41b6c4"}, {"value": 90.0, "color": "#225ea8"}, {"value": 100.0, "color": "#081d58"}],
    "Schneehöhe (cm)": [{"value": 0.0, "color": "#ffffff"}, {"value": 5.0, "color": "#c6dbef"}, {"value": 15.0, "color": "#6baed6"}, {"value": 30.0, "color": "#2171b5"}, {"value": 100.0, "color": "#08306b"}],
    "Luftdruck (hPa)": [{"value": 950.0, "color": "#8c510a"}, {"value": 990.0, "color": "#d8b365"}, {"value": 1013.0, "color": "#f6e8c3"}, {"value": 1030.0, "color": "#c7eae5"}, {"value": 1050.0, "color": "#5ab4ac"}],
    "Sichtweite (m)": [{"value": 0.0, "color": "#800026"}, {"value": 200.0, "color": "#e31a1c"}, {"value": 1000.0, "color": "#fd8d3c"}, {"value": 5000.0, "color": "#ffffcc"}, {"value": 20000.0, "color": "#ffffff"}],
    "Nullgradgrenze (m)": [{"value": 0.0, "color": "#313695"}, {"value": 1000.0, "color": "#74add1"}, {"value": 2000.0, "color": "#e0f3f8"}, {"value": 3000.0, "color": "#fdae61"}, {"value": 4000.0, "color": "#d73027"}],
    "Sonneneinstrahlung (W/m²)": [{"value": 0.0, "color": "#ffffff"}, {"value": 200.0, "color": "#ffffcc"}, {"value": 500.0, "color": "#fdae61"}, {"value": 800.0, "color": "#f46d43"}, {"value": 1000.0, "color": "#d73027"}],
    "500 hPa Geopot. Height": [{"value": 500.0, "color": "#313695"}, {"value": 540.0, "color": "#e0f3f8"}, {"value": 580.0, "color": "#d73027"}],
    "850 hPa Temp.": [{"value": -20.0, "color": "#313695"}, {"value": -10.0, "color": "#74add1"}, {"value": 0.0, "color": "#ffffff"}, {"value": 10.0, "color": "#fdae61"}, {"value": 20.0, "color": "#d73027"}],
    "MLCAPE": [{"value": 0.0, "color": "#ffffff"}, {"value": 250.0, "color": "#ffffcc"}, {"value": 1000.0, "color": "#fd8d3c"}, {"value": 2500.0, "color": "#e31a1c"}],
    "CIN": [{"value": 0.0, "color": "#ffffff"}, {"value": 50.0, "color": "#a6cee3"}, {"value": 200.0, "color": "#1f78b4"}, {"value": 500.0, "color": "#08306b"}],
    "CAPE & CIN (Deckel)": [{"value": 0.0, "color": "#ffffff"}, {"value": 250.0, "color": "#ffffcc"}, {"value": 1000.0, "color": "#fd8d3c"}, {"value": 2500.0, "color": "#e31a1c"}],
    "Scherung 0-1 km": [{"value": 0.0, "color": "#ffffff"}, {"value": 15.0, "color": "#ffffcc"}, {"value": 30.0, "color": "#fd8d3c"}, {"value": 45.0, "color": "#e31a1c"}, {"value": 60.0, "color": "#800026"}],
    "Scherung 0-6 km": [{"value": 0.0, "color": "#ffffff"}, {"value": 20.0, "color": "#ffffcc"}, {"value": 40.0, "color": "#fd8d3c"}, {"value": 60.0, "color": "#e31a1c"}, {"value": 80.0, "color": "#800026"}],
    "Radarreflektivität (dBZ)": [{"value": 0.0, "color": "#ffffff"}, {"value": 15.0, "color": "#a6cee3"}, {"value": 30.0, "color": "#1f78b4"}, {"value": 45.0, "color": "#fd8d3c"}, {"value": 55.0, "color": "#e31a1c"}, {"value": 65.0, "color": "#800026"}],
    "Blitzrate (LPI)": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#ffffcc"}, {"value": 5.0, "color": "#fd8d3c"}, {"value": 10.0, "color": "#e31a1c"}, {"value": 20.0, "color": "#800026"}],
    "Chaser Target-Index": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#ffffcc"}, {"value": 3.0, "color": "#fd8d3c"}, {"value": 6.0, "color": "#e31a1c"}, {"value": 10.0, "color": "#800026"}],
    "SCP-Index": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#a6cee3"}, {"value": 5.0, "color": "#1f78b4"}, {"value": 10.0, "color": "#fd8d3c"}, {"value": 20.0, "color": "#e31a1c"}],
    "PWAT (mm)": [{"value": 10.0, "color": "#ffffff"}, {"value": 20.0, "color": "#a6cee3"}, {"value": 30.0, "color": "#1f78b4"}, {"value": 40.0, "color": "#33a02c"}, {"value": 50.0, "color": "#e31a1c"}],
    "Gesamtbewölkung (%)": [{"value": 0.0, "color": "#f0f0f0"}, {"value": 25.0, "color": "#c6dbef"}, {"value": 50.0, "color": "#9ecae1"}, {"value": 75.0, "color": "#6baed6"}, {"value": 100.0, "color": "#3182bd"}],
    "Tiefe Wolken (%)": [{"value": 0.0, "color": "#f0f0f0"}, {"value": 25.0, "color": "#c6dbef"}, {"value": 50.0, "color": "#9ecae1"}, {"value": 75.0, "color": "#6baed6"}, {"value": 100.0, "color": "#3182bd"}],
    "Blanko / Nur Basiskarte": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#000000"}],
}

REGIONS = {
    "Europa": [-15.0, 30.0, 35.0, 65.0], "Deutschland": [2.5, 17.5, 47.0, 55.0],
    "Baden-Württemberg": [7.5, 10.5, 47.5, 49.8], "Bayern": [8.5, 14.0, 47.0, 50.5],
    "Brandenburg / Berlin": [11.0, 15.0, 51.0, 53.5], "Hessen": [7.7, 10.2, 49.3, 51.7],
    "Niedersachsen / Bremen": [6.5, 11.6, 51.2, 54.0], "Nordrhein-Westfalen": [5.8, 9.5, 50.3, 52.5],
    "Sachsen": [11.8, 15.1, 50.1, 51.7], "Schleswig-Holstein / HH": [7.8, 11.5, 53.3, 55.1]
}

GERMAN_CITIES = {
    "Berlin": (13.40, 52.52), "Hamburg": (9.99, 53.55), "München": (11.58, 48.14),
    "Köln": (6.96, 50.93), "Frankfurt": (8.68, 50.11), "Stuttgart": (9.18, 48.78),
    "Düsseldorf": (6.78, 51.22), "Leipzig": (12.37, 51.34), "Dortmund": (7.46, 51.51),
    "Essen": (7.01, 51.45), "Bremen": (8.80, 53.07), "Dresden": (13.73, 51.05),
    "Hannover": (9.73, 52.37), "Nürnberg": (11.07, 49.45)
}
