import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import geopandas as gpd
from github import Github
import json
import requests
import bz2
import tempfile
import os
from datetime import datetime, timedelta, timezone
import xarray as xr

# --- SEITEN-LAYOUT ---
st.set_page_config(page_title="Modellkarten-Generator", page_icon="🗺️", layout="wide")
st.title("🗺️ Statische Modellkarte (Echte DWD-Daten)")

# --- STANDARD-KONFIGURATION ---
DEFAULT_CONFIG = [
    {"value": -10.0, "color": "#313695"},
    {"value": 0.0, "color": "#74add1"},
    {"value": 10.0, "color": "#e0f3f8"},
    {"value": 20.0, "color": "#fdae61"},
    {"value": 30.0, "color": "#d73027"},
    {"value": 40.0, "color": "#a50026"}
]

# --- GITHUB LADE- & SPEICHER-FUNKTIONEN ---
def load_config():
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            g = Github(st.secrets["GITHUB_TOKEN"])
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file = repo.get_contents("config.json")
            return json.loads(file.decoded_content.decode())
        except Exception:
            pass # Nutzt Standardwerte, wenn keine config gefunden wird
    return DEFAULT_CONFIG

def save_config(config_data):
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            g = Github(st.secrets["GITHUB_TOKEN"])
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file_path = "config.json"
            content = json.dumps(config_data, indent=4)
            try:
                file = repo.get_contents(file_path)
                repo.update_file(file_path, "Update Farbskala", content, file.sha)
            except:
                repo.create_file(file_path, "Create config.json", content)
            st.success("Erfolgreich auf GitHub gespeichert!")
        except Exception as e:
            st.error(f"Fehler beim Speichern: {e}")
    else:
        st.error("GitHub Secrets fehlen zum Speichern.")

if "config" not in st.session_state:
    st.session_state.config = load_config()

# --- DATEN LADEN (Grenzen) ---
@st.cache_data
def load_borders():
    world_url = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
    world = gpd.read_file(world_url)
    bl_url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    bundeslaender = gpd.read_file(bl_url)
    return world, bundeslaender

# --- DWD ICON-D2 LADE-FUNKTION ---
def get_latest_icon_data():
    now = datetime.now(timezone.utc)
    # Sucht die letzten 12 Stunden ab, um den neuesten hochgeladenen Lauf zu finden
    for offset in range(4):
        run_time = now - timedelta(hours=(now.hour % 3) + offset * 3)
        run_str = f"{run_time.hour:02d}"
        date_str = run_time.strftime("%Y%m%d")
        
        # DWD Open Data URL für ICON-D2, Reguläres Lat-Lon Gitter, 2m Temperatur, Analyse-Schritt (000)
        file_name = f"icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_000_2d_t_2m.grib2.bz2"
        url = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/t_2m/{file_name}"
        
        try:
            # Prüfen, ob die Datei existiert
            resp = requests.head(url, timeout=5)
            if resp.status_code == 200:
                st.info(f"Lade echten Modell-Lauf vom {run_time.strftime('%d.%m.%Y')} um {run_str}:00 UTC...")
                
                # Datei herunterladen
                dl_resp = requests.get(url)
                grib_data = bz2.decompress(dl_resp.content)
                
                # Temporär speichern für xarray
                with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f:
                    f.write(grib_data)
                    temp_path = f.name
                
                # GRIB2 öffnen und Temperatur auslesen
                ds = xr.open_dataset(temp_path, engine='cfgrib')
                temp_c = ds['t2m'].values - 273.15 # Umrechnung Kelvin in Celsius
                lats = ds['latitude'].values
                lons = ds['longitude'].values
                
                ds.close()
                os.remove(temp_path)
                return lons, lats, temp_c
        except Exception as e:
            continue
            
    st.error("Konnte keine aktuellen DWD-Daten finden.")
    return None, None, None

# --- KARTE ZEICHNEN ---
def create_map(config_data, lons, lats, temp_data):
    world, bundeslaender = load_borders()
    
    # 1. Weiche Farbskala berechnen
    sorted_conf = sorted(config_data, key=lambda x: x['value'])
    levels = [c['value'] for c in sorted_conf]
    colors = [c['color'] for c in sorted_conf]
    
    # Farben anhand der Minimal- und Maximalwerte normalisieren
    min_val, max_val = min(levels), max(levels)
    norm_levels = [(v - min_val) / (max_val - min_val) for v in levels]
    
    # Generiert einen fließenden Gradienten
    smooth_cmap = mcolors.LinearSegmentedColormap.from_list("custom_smooth", list(zip(norm_levels, colors)))
    
    bg_color = '#0E1117'
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    # 2. Reale Daten plotten (mit 100 Stufen für weiche Übergänge)
    if len(levels) > 1:
        # contourf mit 100 levels sorgt für die völlig glatte "Airbrush"-Optik
        smooth_levels = np.linspace(min_val, max_val, 100)
        karte = ax.contourf(lons, lats, temp_data, levels=smooth_levels, cmap=smooth_cmap, extend='both', alpha=0.95)
        
        # Farbskala rechts anbringen (mit den vom User definierten Ticks)
        cbar = fig.colorbar(karte, ax=ax, fraction=0.046, pad=0.04, ticks=levels)
        cbar.set_label('Temperatur in °C', color='white', size=12)
        cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')

    # 3. Grenzen zeichnen
    world.boundary.plot(ax=ax, edgecolor='#555555', linewidth=0.8, alpha=0.8)
    bundeslaender.boundary.plot(ax=ax, edgecolor='#ffffff', linewidth=1.2, alpha=1.0)
    
    # 4. Fokus exakt auf das ICON-D2 Gitter zuschneiden
    ax.set_xlim(5.5, 15.5)
    ax.set_ylim(47.0, 55.0)
    ax.axis('off')
    
    return fig

# --- BENUTZEROBERFLÄCHE (UI) ---
st.sidebar.header("⚙️ Allgemeine Einstellungen")
model_choice = st.sidebar.selectbox("Modell auswählen:", ["ICON-D2 (2.2km)"])
param_choice = st.sidebar.selectbox("Parameter auswählen:", ["Temperatur (2m)"])

st.sidebar.divider()

# Ausklappbares Menü für die Farben
with st.sidebar.expander("🎨 Farb- & Werte-Einstellungen", expanded=False):
    st.write("Definiere deine eigenen Schwellenwerte:")
    new_config = []
    for i, item in enumerate(st.session_state.config):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            val = st.number_input("Wert", value=float(item['value']), step=1.0, key=f"val_{i}", label_visibility="collapsed")
        with col2:
            color = st.color_picker("Farbe", value=item['color'], key=f"col_{i}", label_visibility="collapsed")
        with col3:
            if st.button("🗑️", key=f"del_{i}"):
                st.session_state.config.pop(i)
                st.rerun()
        new_config.append({"value": val, "color": color})
    
    st.session_state.config = new_config

    col_add, col_save = st.columns(2)
    with col_add:
        if st.button("➕ Neuer Wert"):
            st.session_state.config.append({"value": 0.0, "color": "#ffffff"})
            st.rerun()
    with col_save:
        if st.button("💾 Speichern"):
            with st.spinner("Speichere auf GitHub..."):
                save_config(st.session_state.config)

st.sidebar.divider()

# Karten-Generierung
if st.button("🚀 Echte DWD-Karte rendern", type="primary"):
    with st.spinner("Lade 2.2km ICON-D2 GRIB2-Daten vom DWD Server (kann kurz dauern)..."):
        # Daten abrufen
        lons, lats, temp_data = get_latest_icon_data()
        
        if lons is not None:
            with st.spinner("Rendere Karte mit weichen Übergängen..."):
                fertige_grafik = create_map(st.session_state.config, lons, lats, temp_data)
                st.pyplot(fertige_grafik)
                st.success("Modellkarte aus echten ICON-D2 Rohdaten generiert!")
