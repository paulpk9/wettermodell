import streamlit as st
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import scipy.ndimage as ndimage
import json
import os
from github import Github
from datetime import datetime, timedelta
import pytz
import geopandas as gpd

# --- KONFIGURATION ---
st.set_page_config(page_title="Hybrid-Wettermodell", layout="wide")

# --- FUNKTIONEN ---

@st.cache_data(ttl=300)
def load_settings():
    if os.path.exists("settings.json"):
        with open("settings.json", "r") as f:
            return json.load(f)
    return {}

def save_settings_to_github(new_settings):
    try:
        token = st.secrets["GITHUB_TOKEN"]
        repo_name = st.secrets["REPO_NAME"]
        g = Github(token)
        repo = g.get_repo(repo_name)
        contents = repo.get_contents("settings.json")
        repo.update_file(contents.path, "Farbupdate via Streamlit", json.dumps(new_settings, indent=4), contents.sha)
        st.sidebar.success("✅ Design gespeichert!")
    except Exception as e:
        st.sidebar.error(f"Fehler: {e}")

@st.cache_data(ttl=3600*24) # Speichert die Kartengrenzen für 24h im Zwischenspeicher
def load_map_boundaries():
    """Lädt echte Bundesland- und Landkreisgrenzen aus Open-Source GeoJSON."""
    url_states = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    url_districts = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/4_kreisgrenzen/4_niedrig.geo.json"
    states = gpd.read_file(url_states)
    districts = gpd.read_file(url_districts)
    return states, districts

def get_hybrid_data(parameter, lead_time, correction_factor):
    """Generiert simulierte Daten, die wie echte Wetterkarten aussehen."""
    np.random.seed(lead_time + len(parameter))
    # Erzeugt Rauschen und macht es "wolkig/flächig" wie im Radar
    noise = np.random.rand(100, 100)
    smoothed_data = ndimage.gaussian_filter(noise, sigma=5) * 100
    
    if parameter == "Niederschlagsrate":
        smoothed_data = smoothed_data * 0.4
    else:
        smoothed_data = smoothed_data * 1.5
        
    return smoothed_data * correction_factor

def plot_static_map(data, settings, parameter, lead_time_hours):
    """Erstellt die detaillierte, statische Modellkarte für Mühlberg."""
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # Farben aus den Einstellungen holen (Standard: Weiß zu Blau/Rot)
    cmin = settings.get(parameter, {}).get("color_min", "#ffffff")
    cmax = settings.get(parameter, {}).get("color_max", "#0000ff")
    cmap = LinearSegmentedColormap.from_list("custom", [cmin, cmax])
    vmin = settings.get(parameter, {}).get("vmin", 0.0)
    vmax = settings.get(parameter, {}).get("vmax", 50.0)
    
    # 1. Begrenzung: Mühlberg/Elbe + ca. 50 km Radius
    # Mühlberg Koordinaten: 51.43° Nord, 13.21° Ost
    min_lon, max_lon = 12.50, 13.90
    min_lat, max_lat = 50.98, 51.88
    
    # 2. Kartengrenzen zeichnen (Landkreise & Bundesländer)
    try:
        states, districts = load_map_boundaries()
        districts.boundary.plot(ax=ax, linewidth=0.5, color='gray', zorder=1)
        states.boundary.plot(ax=ax, linewidth=1.5, color='black', zorder=2)
    except Exception:
        st.warning("Kartengrenzen konnten kurzzeitig nicht geladen werden.")
        
    ax.set_xlim(min_lon, max_lon)
    ax.set_ylim(min_lat, max_lat)
    
    # 3. Wetterdaten als Flächen über die Karte legen
    # Wir erzeugen ein geografisches Gitter für die Dummy-Daten
    X, Y = np.meshgrid(np.linspace(min_lon, max_lon, 100), np.linspace(min_lat, max_lat, 100))
    c = ax.contourf(X, Y, data, levels=20, cmap=cmap, vmin=vmin, vmax=vmax, alpha=0.75, zorder=0)
    fig.colorbar(c, ax=ax, label=parameter, pad=0.02)
    
    # 4. Mühlberg/Elbe auf der Karte markieren
    ax.plot(13.2167, 51.4333, marker='*', color='red', markersize=12, zorder=3)
    ax.text(13.23, 51.44, "Mühlberg/Elbe", color='black', fontweight='bold', zorder=3, 
            bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1))
    
    # 5. Beschriftung (oben auf der Karte)
    berlin_tz = pytz.timezone('Europe/Berlin')
    current_time = datetime.now(berlin_tz)
    forecast_time = current_time + timedelta(hours=lead_time_hours)
    
    title_str = (f"Modell: Hybrid-Modell\n"
                 f"Gültig für: {forecast_time.strftime('%d.%m.%Y, %H:%M Uhr')}\n"
                 f"Parameter: {parameter}")
    ax.set_title(title_str, loc='left', fontsize=12, fontweight='bold')
    
    # Optik aufräumen
    ax.grid(True, linestyle=':', alpha=0.5)
    ax.set_xlabel("Längengrad")
    ax.set_ylabel("Breitengrad")
    
    return fig

# --- APP LAYOUT ---
st.title("🌦️ Mein Hybrid-Modell (Mühlberg Fokus)")

if "lead_time" not in st.session_state:
    st.session_state.lead_time = 1 # Start bei Stunde 1

# --- SIDEBAR ---
st.sidebar.header("⚙️ Steuerung")

# 1. Parameter Auswahl
parameter = st.sidebar.selectbox("Parameter wählen", ["Niederschlagsrate", "Windböen"])

# 2. Synoptische Korrektur (Passt sich nun an den Parameter an)
st.sidebar.subheader("👨‍🔬 Synoptische Korrektur")
correction = st.sidebar.slider(f"Faktor für {parameter}", min_value=0.0, max_value=3.0, value=1.0, step=0.1)

# 3. Zeitregler (Geordnet von 1 bis 27)
st.sidebar.subheader("⏱️ Vorhersagezeit")
berlin_tz = pytz.timezone('Europe/Berlin')
current_time = datetime.now(berlin_tz)

# Grid für Buttons logisch aufbauen (4 Spalten, zeilenweise)
for row in range(7):
    cols = st.sidebar.columns(4)
    for i in range(4):
        h = row * 4 + i + 1 # Zählt von 1 bis 28
        if h <= 27:
            forecast_time = current_time + timedelta(hours=h)
            time_str = forecast_time.strftime("%H:%M")
            with cols[i]:
                if st.button(f"+{h}h\n{time_str}", key=f"btn_{h}"):
                    st.session_state.lead_time = h

# 4. JSON / Farb-Einstellungen (Mit Farbrad!)
st.sidebar.subheader("🎨 Karten-Einstellungen")
settings = load_settings()

# Standardwerte anlegen, falls noch nicht in der JSON
if parameter not in settings:
    settings[parameter] = {
        "color_min": "#ffffff",
        "color_max": "#0000ff" if parameter == "Niederschlagsrate" else "#ff0000",
        "vmin": 0.0,
        "vmax": 50.0 if parameter == "Niederschlagsrate" else 100.0
    }

# Farbräder (Color Picker)
color_min = st.sidebar.color_picker("Farbe Min-Wert (Start)", settings[parameter].get("color_min", "#ffffff"))
color_max = st.sidebar.color_picker("Farbe Max-Wert (Ende)", settings[parameter].get("color_max", "#0000ff"))
new_vmin = st.sidebar.number_input("Skala Minimum", value=float(settings[parameter].get("vmin", 0.0)))
new_vmax = st.sidebar.number_input("Skala Maximum", value=float(settings[parameter].get("vmax", 50.0)))

if st.sidebar.button("💾 Design in GitHub speichern"):
    settings[parameter]["color_min"] = color_min
    settings[parameter]["color_max"] = color_max
    settings[parameter]["vmin"] = new_vmin
    settings[parameter]["vmax"] = new_vmax
    save_settings_to_github(settings)

# --- HAUPTBEREICH ---
data = get_hybrid_data(parameter, st.session_state.lead_time, correction)

# Karte plotten und anzeigen
with st.spinner("Lade Karte und Grenzen..."):
    fig = plot_static_map(data, settings, parameter, st.session_state.lead_time)
    st.pyplot(fig)
