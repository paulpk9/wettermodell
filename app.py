import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import geopandas as gpd
from github import Github, Auth
import json
import requests
import bz2
import tempfile
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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
def get_github_client():
    if "GITHUB_TOKEN" in st.secrets:
        # Korrigierte Authentifizierungsmethode laut neuer PyGithub Version
        auth = Auth.Token(st.secrets["GITHUB_TOKEN"])
        return Github(auth=auth)
    return None

def load_config():
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file = repo.get_contents("config.json")
            return json.loads(file.decoded_content.decode())
        except Exception:
            pass
    return DEFAULT_CONFIG

def save_config(config_data):
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
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

# --- DATEN LADEN (Grenzen) mit Anti-Absturz-Fix ---
@st.cache_data
def load_borders():
    # Wir nutzen requests, um den GDAL/curl Segmentation Fault zu umgehen
    world_url = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
    bl_url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    
    world_resp = requests.get(world_url).text
    bl_resp = requests.get(bl_url).text
    
    # Kurzzeitig als lokale Dateien speichern für geopandas
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f1:
        f1.write(world_resp)
        f1_name = f1.name
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f2:
        f2.write(bl_resp)
        f2_name = f2.name
        
    world = gpd.read_file(f1_name)
    bundeslaender = gpd.read_file(f2_name)
    
    os.remove(f1_name)
    os.remove(f2_name)
    
    return world, bundeslaender

# --- DWD ZEITEN FINDEN & LADE-FUNKTION ---
@st.cache_data(ttl=3600) # Cacht den neuesten Lauf für eine Stunde
def get_latest_run_time():
    now = datetime.now(timezone.utc)
    for offset in range(4):
        run_time = now - timedelta(hours=(now.hour % 3) + offset * 3)
        run_str = f"{run_time.hour:02d}"
        date_str = run_time.strftime("%Y%m%d")
        # Wir testen nur, ob Stunde 000 existiert
        url = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/t_2m/icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_000_2d_t_2m.grib2.bz2"
        try:
            resp = requests.head(url, timeout=5)
            if resp.status_code == 200:
                return run_time
        except Exception:
            continue
    return None

def get_icon_data(run_time, forecast_hour):
    run_str = f"{run_time.hour:02d}"
    date_str = run_time.strftime("%Y%m%d")
    hour_str = f"{forecast_hour:03d}"
    
    file_name = f"icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_2d_t_2m.grib2.bz2"
    url = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/t_2m/{file_name}"
    
    try:
        dl_resp = requests.get(url)
        if dl_resp.status_code != 200:
            st.error("Diese Vorhersagestunde ist auf dem Server (noch) nicht verfügbar.")
            return None, None, None
            
        grib_data = bz2.decompress(dl_resp.content)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f:
            f.write(grib_data)
            temp_path = f.name
        
        ds = xr.open_dataset(temp_path, engine='cfgrib')
        temp_c = ds['t2m'].values - 273.15
        lats = ds['latitude'].values
        lons = ds['longitude'].values
        
        ds.close()
        os.remove(temp_path)
        return lons, lats, temp_c
    except Exception as e:
        st.error(f"Fehler beim Laden der GRIB2-Daten: {e}")
        return None, None, None

# --- KARTE ZEICHNEN ---
def create_map(config_data, lons, lats, temp_data, map_title_time):
    world, bundeslaender = load_borders()
    
    sorted_conf = sorted(config_data, key=lambda x: x['value'])
    levels = [c['value'] for c in sorted_conf]
    colors = [c['color'] for c in sorted_conf]
    
    min_val, max_val = min(levels), max(levels)
    norm_levels = [(v - min_val) / (max_val - min_val) for v in levels]
    smooth_cmap = mcolors.LinearSegmentedColormap.from_list("custom_smooth", list(zip(norm_levels, colors)))
    
    bg_color = '#0E1117'
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    if len(levels) > 1:
        smooth_levels = np.linspace(min_val, max_val, 100)
        karte = ax.contourf(lons, lats, temp_data, levels=smooth_levels, cmap=smooth_cmap, extend='both', alpha=0.95)
        
        cbar = fig.colorbar(karte, ax=ax, fraction=0.046, pad=0.04, ticks=levels)
        cbar.set_label('Temperatur in °C', color='white', size=12)
        cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')

    world.boundary.plot(ax=ax, edgecolor='#555555', linewidth=0.8, alpha=0.8)
    bundeslaender.boundary.plot(ax=ax, edgecolor='#ffffff', linewidth=1.2, alpha=1.0)
    
    ax.set_xlim(5.5, 15.5)
    ax.set_ylim(47.0, 55.0)
    ax.axis('off')
    
    # Optional: Ein kleiner Text direkt in der Karte
    ax.text(5.7, 54.7, f"ICON-D2 | {map_title_time}", color='white', fontsize=10, 
            bbox=dict(facecolor='#0E1117', alpha=0.7, edgecolor='none'))
    
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

# --- HAUPTBEREICH (Karten-Steuerung & Zeit) ---
run_time = get_latest_run_time()

if run_time:
    # Laufzeit in UTC anzeigen
    st.info(f"Basis-Modelllauf: {run_time.strftime('%d.%m.%Y | %H:00')} UTC")
    
    # Der neue Schieberegler
    st.markdown("### ⏱️ Zeitschritt auswählen")
    forecast_hour = st.slider("Vorhersagestunde", min_value=0, max_value=48, value=0, step=1, format="+%dh")
    
    # Zeit umrechnen in MESZ/MEZ (Europe/Berlin)
    forecast_time_utc = run_time + timedelta(hours=forecast_hour)
    local_tz = ZoneInfo("Europe/Berlin")
    forecast_time_local = forecast_time_utc.astimezone(local_tz)
    
    # Zeit formatiert anzeigen
    time_string = f"{forecast_time_local.strftime('%d.%m.%Y')} um {forecast_time_local.strftime('%H:00')} Uhr"
    st.success(f"**Gültig für:** +{forecast_hour}h ➔ {time_string} (MEZ/MESZ)")
    
    # Der Render-Button unterhalb des Sliders
    if st.button("🚀 Karte für diese Stunde rendern", type="primary"):
        with st.spinner(f"Lade ICON-D2 Daten für +{forecast_hour}h vom DWD Server..."):
            lons, lats, temp_data = get_icon_data(run_time, forecast_hour)
            
            if lons is not None:
                with st.spinner("Rendere Karte..."):
                    fertige_grafik = create_map(st.session_state.config, lons, lats, temp_data, f"+{forecast_hour}h | {time_string}")
                    st.pyplot(fertige_grafik)
                    st.toast("Modellkarte erfolgreich generiert!", icon="✅")
else:
    st.error("Konnte aktuell keine Verbindung zum DWD-Server aufbauen oder keinen Lauf finden.")
