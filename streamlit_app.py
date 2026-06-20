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
st.set_page_config(page_title="Hybrid-Wettermodell PRO", layout="wide")

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
        repo.update_file(contents.path, "Farbrad Update", json.dumps(new_settings, indent=4), contents.sha)
        st.sidebar.success("✅ Design sicher in GitHub gespeichert!")
    except Exception as e:
        st.sidebar.error(f"Fehler beim Speichern: {e}")

@st.cache_data(ttl=86400)
def load_map_boundaries():
    headers = {"User-Agent": "Mozilla/5.0"}
    url_states = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    url_districts = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/4_kreisgrenzen/4_niedrig.geo.json"
    
    r_states = requests.get(url_states, headers=headers).json()
    r_districts = requests.get(url_districts, headers=headers).json()
    
    states = gpd.GeoDataFrame.from_features(r_states["features"])
    districts = gpd.GeoDataFrame.from_features(r_districts["features"])
    
    states.set_crs(epsg=4326, inplace=True)
    districts.set_crs(epsg=4326, inplace=True)
    
    return states, districts

@st.cache_data(ttl=1800)
def fetch_real_hybrid_data():
    """Holt ECHTE ICON-D2 und AROME Daten. Massiv verdichtetes 8x8 Gitter (64 Punkte) für höchste Genauigkeit."""
    lats = np.linspace(50.98, 51.88, 8)
    lons = np.linspace(12.50, 13.90, 8)
    grid_lats, grid_lons = np.meshgrid(lats, lons)
    
    flat_lats = grid_lats.flatten()
    flat_lons = grid_lons.flatten()
    
    lat_str = ",".join([f"{x:.3f}" for x in flat_lats])
    lon_str = ",".join([f"{x:.3f}" for x in flat_lons])
    
    # Echte Vorhersagedaten der offiziellen Modelle abrufen
    url = f"https://api.open-meteo.com/v1/forecast?latitude={lat_str}&longitude={lon_str}&hourly=precipitation,wind_gusts_10m&models=icon_d2,arome_seamless&timezone=Europe/Berlin"
    
    response = requests.get(url)
    return response.json(), flat_lats, flat_lons

def process_hybrid_data(api_data, flat_lats, flat_lons, parameter, lead_time, correction_factor, weight_icon, weight_arome):
    """Gewichtet die Modelle individuell und interpoliert sie flächig."""
    points = []
    values = []
    api_param = "precipitation" if parameter == "Niederschlagsrate" else "wind_gusts_10m"
    
    total_weight = weight_icon + weight_arome
    if total_weight == 0:
        total_weight = 1.0 # Verhindert Division durch 0
        
    for i, loc_data in enumerate(api_data):
        key_icon = f"{api_param}_icon_d2"
        key_arome = f"{api_param}_arome_seamless"
        
        # Falls ein Punkt beim Anbieter mal fehlt, nehmen wir sicherheitshalber 0
        val_icon = loc_data.get("hourly", {}).get(key_icon, [0]*48)[lead_time]
        val_arome = loc_data.get("hourly", {}).get(key_arome, [0]*48)[lead_time]
        
        val_icon = val_icon if val_icon is not None else 0.0
        val_arome = val_arome if val_arome is not None else 0.0
        
        # Hybrid-Verrechnung mit deinen eingestellten Gewichten
        hybrid_val = ((val_icon * weight_icon) + (val_arome * weight_arome)) / total_weight
        hybrid_val *= correction_factor
        
        points.append([flat_lons[i], flat_lats[i]])
        values.append(hybrid_val)
        
    # Die 64 echten Messpunkte werden auf ein dichtes 150x150 Pixel Bild gelegt (Interpolation)
    grid_lon, grid_lat = np.meshgrid(np.linspace(12.50, 13.90, 150), np.linspace(50.98, 51.88, 150))
    grid_z = scipy.interpolate.griddata(points, values, (grid_lon, grid_lat), method='linear')
    
    return np.clip(grid_z, 0, None), grid_lon, grid_lat

def plot_static_map(data_z, grid_lon, grid_lat, settings, parameter, lead_time_hours):
    """Erstellt die Karte mit Grenzen, Mühlberg-Fokus und Beschriftungen."""
    fig, ax = plt.subplots(figsize=(10, 8))
    
    levels = settings[parameter]["levels"]
    colors = settings[parameter]["colors"]
    max_val = settings[parameter]["max_val"]
    
    boundaries = levels + [max_val]
    
    try:
        cmap = mcolors.ListedColormap(colors)
        norm = mcolors.BoundaryNorm(boundaries, cmap.N)
    except Exception:
        cmap = "viridis"
        norm = None

    try:
        states, districts = load_map_boundaries()
        districts.boundary.plot(ax=ax, linewidth=0.5, color='gray', zorder=1)
        states.boundary.plot(ax=ax, linewidth=1.5, color='black', zorder=2)
    except Exception:
        pass
        
    ax.set_xlim(12.50, 13.90)
    ax.set_ylim(50.98, 51.88)
    
    if norm:
        c = ax.contourf(grid_lon, grid_lat, data_z, levels=boundaries, cmap=cmap, norm=norm, alpha=0.75, zorder=0, extend='max')
    else:
        c = ax.contourf(grid_lon, grid_lat, data_z, levels=20, cmap=cmap, alpha=0.75, zorder=0)
        
    fig.colorbar(c, ax=ax, label=f"{parameter} {'(mm/h)' if parameter == 'Niederschlagsrate' else '(km/h)'}", pad=0.02)
    
    ax.plot(13.2167, 51.4333, marker='*', color='red', markersize=12, zorder=3)
    ax.text(13.23, 51.44, "Mühlberg/Elbe", color='black', fontweight='bold', zorder=3, bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1))
    
    berlin_tz = pytz.timezone('Europe/Berlin')
    forecast_time = datetime.now(berlin_tz) + timedelta(hours=lead_time_hours)
    
    title_str = (f"Modell: Hybrid (ICON-D2 + AROME)\n"
                 f"Gültig für: {forecast_time.strftime('%d.%m.%Y, %H:%M Uhr')}\n"
                 f"Parameter: {parameter}")
    ax.set_title(title_str, loc='left', fontsize=12, fontweight='bold')
    
    ax.grid(True, linestyle=':', alpha=0.5)
    ax.set_xlabel("Längengrad")
    ax.set_ylabel("Breitengrad")
    
    return fig

# --- APP LAYOUT ---
st.title("🌦️ Hybrid-Modell PRO (Echte DWD & AROME Daten)")

if "lead_time" not in st.session_state:
    st.session_state.lead_time = 1
if "show_map" not in st.session_state:
    st.session_state.show_map = False

# --- SIDEBAR ---
st.sidebar.header("⚙️ Modell-Steuerung")

parameter = st.sidebar.selectbox("Parameter wählen", ["Niederschlagsrate", "Windböen"])

st.sidebar.subheader("⚖️ Hybrid-Gewichtung")
weight_icon = st.sidebar.slider("Einfluss ICON-D2", 0.0, 1.0, 0.5, 0.1)
weight_arome = st.sidebar.slider("Einfluss AROME", 0.0, 1.0, 0.5, 0.1)

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
                # Ein Klick aktualisiert die Zeit und behält die Karte, falls sie offen ist
                if st.button(f"+{h}h\n{forecast_time.strftime('%H:%M')}", key=f"btn_{h}"):
                    st.session_state.lead_time = h

# --- FARBEN & SKALEN EDITOR (MIT FARBRAD) ---
st.sidebar.subheader(f"🎨 Skala: {parameter}")
settings = load_settings()

if parameter not in settings:
    settings[parameter] = {}

# Absturzsicherung: Fehlende Keys werden sofort korrekt nachgebaut
if "levels" not in settings[parameter]:
    settings[parameter]["levels"] = [0.0, 1.0, 5.0, 10.0] if parameter == "Niederschlagsrate" else [0.0, 30.0, 60.0, 90.0]
if "colors" not in settings[parameter]:
    settings[parameter]["colors"] = ["#ffffff", "#add8e6", "#0000ff", "#ff00ff"]
if "max_val" not in settings[parameter]:
    settings[parameter]["max_val"] = 50.0 if parameter == "Niederschlagsrate" else 130.0

df_colors = pd.DataFrame({
    "Ab Wert": settings[parameter]["levels"],
    "Farbe": settings[parameter]["colors"]
})

st.sidebar.write("Klicke in der Spalte 'Farbe' auf das Farb-Kästchen, um das Farbrad zu öffnen!")
# Die Magie: Das Streamlit ColorColumn Widget!
edited_df = st.sidebar.data_editor(
    df_colors, 
    num_rows="dynamic", 
    use_container_width=True,
    column_config={
        "Farbe": st.column_config.ColorColumn("Farbe (Hier klicken)")
    }
)
max_val = st.sidebar.number_input(f"Maximalwert für {parameter}", value=float(settings[parameter]["max_val"]))

if st.sidebar.button("💾 Skala in GitHub speichern"):
    settings[parameter]["levels"] = edited_df["Ab Wert"].tolist()
    settings[parameter]["colors"] = edited_df["Farbe"].tolist()
    settings[parameter]["max_val"] = max_val
    save_settings_to_github(settings)

# --- HAUPTBEREICH ---
st.write("Stelle alle Parameter und Gewichte im linken Menü ein. Drücke danach auf den blauen Button, um die Rechenleistung abzurufen und die Karte zu erstellen.")

# Der Button, um die Karte zu generieren
if st.button("🗺️ Karte jetzt berechnen & generieren", type="primary"):
    st.session_state.show_map = True

# Zeigt die Karte an, sobald der Button einmal gedrückt wurde
if st.session_state.show_map:
    with st.spinner("Lade offizielle Modelldaten (64 Gitterpunkte) und berechne Interpolation..."):
        try:
            api_data, flat_lats, flat_lons = fetch_real_hybrid_data()
            data_z, grid_lon, grid_lat = process_hybrid_data(api_data, flat_lats, flat_lons, parameter, st.session_state.lead_time, correction, weight_icon, weight_arome)
            
            fig = plot_static_map(data_z, grid_lon, grid_lat, settings, parameter, st.session_state.lead_time)
            st.pyplot(fig)
            
        except Exception as e:
            st.error(f"Schwerer Rechenfehler bei den Wetterdaten: {e}")
