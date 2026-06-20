import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import scipy.interpolate
import pandas as pd
import json
import os
import requests
from github import Github
from datetime import datetime, timedelta
import pytz
import geopandas as gpd

# --- KONFIGURATION ---
st.set_page_config(page_title="Hybrid-Wettermodell V2", layout="wide")

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
        repo.update_file(contents.path, "Update diskrete Farbskala", json.dumps(new_settings, indent=4), contents.sha)
        st.sidebar.success("✅ Skala in GitHub gespeichert!")
    except Exception as e:
        st.sidebar.error(f"Fehler beim Speichern: {e}")

@st.cache_data(ttl=86400)
def load_map_boundaries():
    """Lädt die Kartengrenzen (Behebt den Lade-Fehler aus V1)"""
    headers = {"User-Agent": "Mozilla/5.0"} # Verhindert, dass der Server uns blockiert
    url_states = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    url_districts = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/4_kreisgrenzen/4_niedrig.geo.json"
    
    # Daten via requests laden und an GeoPandas übergeben
    r_states = requests.get(url_states, headers=headers).json()
    r_districts = requests.get(url_districts, headers=headers).json()
    
    states = gpd.GeoDataFrame.from_features(r_states["features"])
    districts = gpd.GeoDataFrame.from_features(r_districts["features"])
    
    states.set_crs(epsg=4326, inplace=True)
    districts.set_crs(epsg=4326, inplace=True)
    
    return states, districts

@st.cache_data(ttl=1800) # Aktualisiert die Modelldaten alle 30 Minuten
def fetch_real_hybrid_data():
    """Holt ECHTE ICON-D2 und AROME Daten via Open-Meteo für ein Gitternetz um Mühlberg."""
    # Wir erstellen ein 4x4 Gitter (16 Messpunkte) rund um Mühlberg
    lats = np.linspace(50.98, 51.88, 4)
    lons = np.linspace(12.50, 13.90, 4)
    grid_lats, grid_lons = np.meshgrid(lats, lons)
    
    flat_lats = grid_lats.flatten()
    flat_lons = grid_lons.flatten()
    
    # Für die API in einen String formatieren
    lat_str = ",".join(map(lambda x: str(round(x, 3)), flat_lats))
    lon_str = ",".join(map(lambda x: str(round(x, 3)), flat_lons))
    
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat_str}&longitude={lon_str}&hourly=precipitation,wind_gusts_10m&models=icon_d2,arome_seamless&timezone=Europe/Berlin"
    
    response = requests.get(url)
    return response.json(), flat_lats, flat_lons

def process_hybrid_data(api_data, flat_lats, flat_lons, parameter, lead_time, correction_factor):
    """Verrechnet die API-Punkte zum Hybrid-Modell und interpoliert sie flächig."""
    points = []
    values = []
    
    api_param = "precipitation" if parameter == "Niederschlagsrate" else "wind_gusts_10m"
    
    # 1. Hybrid-Wert für jeden der 16 Gitterpunkte berechnen
    for i, loc_data in enumerate(api_data):
        # Open-Meteo liefert die Modellnamen als Suffix
        key_icon = f"{api_param}_icon_d2"
        key_arome = f"{api_param}_arome_seamless"
        
        # Daten abgreifen (Falls ein Modell fehlt, nehmen wir 0)
        val_icon = loc_data["hourly"].get(key_icon, [0]*48)[lead_time]
        val_arome = loc_data["hourly"].get(key_arome, [0]*48)[lead_time]
        
        val_icon = val_icon if val_icon is not None else 0
        val_arome = val_arome if val_arome is not None else 0
        
        # Hybrid bilden und Synoptiker-Korrektur anwenden
        hybrid_val = ((val_icon + val_arome) / 2.0) * correction_factor
        
        points.append([flat_lons[i], flat_lats[i]])
        values.append(hybrid_val)
        
    # 2. Die 16 Punkte auf eine 100x100 Pixel Karte weich interpolieren (für die Optik)
    grid_lon, grid_lat = np.meshgrid(np.linspace(12.50, 13.90, 100), np.linspace(50.98, 51.88, 100))
    grid_z = scipy.interpolate.griddata(points, values, (grid_lon, grid_lat), method='cubic')
    
    # Negative Werte durch Interpolation verhindern
    return np.clip(grid_z, 0, None), grid_lon, grid_lat

def plot_static_map(data_z, grid_lon, grid_lat, settings, parameter, lead_time_hours):
    """Erstellt die Karte mit echten Daten und diskreter Farbskala."""
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # 1. Diskrete Farbskala aufbauen
    levels = settings.get(parameter, {}).get("levels", [0.0, 1.0, 5.0, 10.0])
    colors = settings.get(parameter, {}).get("colors", ["#ffffff", "#aaccff", "#0000ff"])
    max_val = settings.get(parameter, {}).get("max_val", 50.0)
    
    # Erzeuge Boundaries (Grenzen): levels + Maximalwert
    boundaries = levels + [max_val]
    
    try:
        cmap = mcolors.ListedColormap(colors)
        norm = mcolors.BoundaryNorm(boundaries, cmap.N)
    except Exception:
        # Fallback, falls der Nutzer in der Tabelle weniger Farben als Level definiert hat
        cmap = "viridis"
        norm = None
        st.warning("Achtung: Die Anzahl der Farben muss genau eins weniger sein als die Anzahl der Level + Maximalwert. Nutze Standardfarben.")

    # 2. Kartengrenzen zeichnen
    try:
        states, districts = load_map_boundaries()
        districts.boundary.plot(ax=ax, linewidth=0.5, color='gray', zorder=1)
        states.boundary.plot(ax=ax, linewidth=1.5, color='black', zorder=2)
    except Exception as e:
        st.error(f"Grenzen konnten nicht geladen werden: {e}")
        
    ax.set_xlim(12.50, 13.90)
    ax.set_ylim(50.98, 51.88)
    
    # 3. Wetterdaten plotten
    if norm:
        c = ax.contourf(grid_lon, grid_lat, data_z, levels=boundaries, cmap=cmap, norm=norm, alpha=0.75, zorder=0, extend='max')
    else:
        c = ax.contourf(grid_lon, grid_lat, data_z, levels=20, cmap=cmap, alpha=0.75, zorder=0)
        
    fig.colorbar(c, ax=ax, label=f"{parameter} {'(mm/h)' if parameter == 'Niederschlagsrate' else '(km/h)'}", pad=0.02)
    
    # 4. Mühlberg/Elbe markieren
    ax.plot(13.2167, 51.4333, marker='*', color='red', markersize=12, zorder=3)
    ax.text(13.23, 51.44, "Mühlberg/Elbe", color='black', fontweight='bold', zorder=3, bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1))
    
    # 5. Beschriftung
    berlin_tz = pytz.timezone('Europe/Berlin')
    forecast_time = datetime.now(berlin_tz) + timedelta(hours=lead_time_hours)
    
    title_str = (f"Modell: Hybrid-Modell (ICON-D2 + AROME)\n"
                 f"Gültig für: {forecast_time.strftime('%d.%m.%Y, %H:%M Uhr')}\n"
                 f"Parameter: {parameter}")
    ax.set_title(title_str, loc='left', fontsize=12, fontweight='bold')
    
    ax.grid(True, linestyle=':', alpha=0.5)
    ax.set_xlabel("Längengrad")
    ax.set_ylabel("Breitengrad")
    
    return fig

# --- APP LAYOUT ---
st.title("🌦️ Hybrid-Modell BETA.V2 (Echte Daten!)")

if "lead_time" not in st.session_state:
    st.session_state.lead_time = 1

# --- SIDEBAR ---
st.sidebar.header("⚙️ Steuerung")

parameter = st.sidebar.selectbox("Parameter wählen", ["Niederschlagsrate", "Windböen"])

st.sidebar.subheader("👨‍🔬 Synoptische Korrektur")
correction = st.sidebar.slider(f"Faktor für {parameter}", min_value=0.0, max_value=3.0, value=1.0, step=0.1)

st.sidebar.subheader("⏱️ Vorhersagezeit")
berlin_tz = pytz.timezone('Europe/Berlin')
current_time = datetime.now(berlin_tz)

for row in range(7):
    cols = st.sidebar.columns(4)
    for i in range(4):
        h = row * 4 + i + 1
        if h <= 27:
            forecast_time = current_time + timedelta(hours=h)
            with cols[i]:
                if st.button(f"+{h}h\n{forecast_time.strftime('%H:%M')}", key=f"btn_{h}"):
                    st.session_state.lead_time = h

# --- FARBEN & SKALEN EDITOR ---
st.sidebar.subheader("🎨 Individuelle Skala")
settings = load_settings()

# Standardwerte falls komplett neu
if parameter not in settings:
    settings[parameter] = {
        "levels": [0.0, 1.0, 5.0, 10.0],
        "colors": ["#ffffff", "#aaccff", "#0000ff", "#ff00ff"],
        "max_val": 50.0
    }

st.sidebar.write("Definiere deine eigenen Schwellenwerte (z.B. ab 1.0mm) und die dazugehörige Farbe als Hex-Code:")

# Tabelle für den Nutzer aufbereiten
df_colors = pd.DataFrame({
    "Ab Wert": settings[parameter]["levels"],
    "Farbe (Hex)": settings[parameter]["colors"]
})

# Streamlit Data Editor nutzen
edited_df = st.sidebar.data_editor(df_colors, num_rows="dynamic", use_container_width=True)
max_val = st.sidebar.number_input("Absoluter Maximalwert der Skala", value=float(settings[parameter].get("max_val", 50.0)))

if st.sidebar.button("💾 Skala in GitHub speichern"):
    # Bereinigen und in JSON Format überführen
    settings[parameter]["levels"] = edited_df["Ab Wert"].tolist()
    settings[parameter]["colors"] = edited_df["Farbe (Hex)"].tolist()
    settings[parameter]["max_val"] = max_val
    save_settings_to_github(settings)

# --- HAUPTBEREICH ---
with st.spinner("Lade echte Modelldaten von Open-Meteo und berechne Hybrid-Raster..."):
    try:
        api_data, flat_lats, flat_lons = fetch_real_hybrid_data()
        data_z, grid_lon, grid_lat = process_hybrid_data(api_data, flat_lats, flat_lons, parameter, st.session_state.lead_time, correction)
        
        fig = plot_static_map(data_z, grid_lon, grid_lat, settings, parameter, st.session_state.lead_time)
        st.pyplot(fig)
        
    except Exception as e:
        st.error(f"Fehler bei der Datenverarbeitung: {e}")
        st.info("Tipp: Manchmal braucht die API einen Moment. Lade die Seite einfach neu.")
