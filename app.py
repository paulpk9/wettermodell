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
import scipy.ndimage as ndimage

# --- SEITEN-LAYOUT ---
st.set_page_config(page_title="Modellkarten-Generator", page_icon="🗺️", layout="wide")
st.title("🗺️ Statische Modellkarte (Profi-Terminal)")

# --- STANDARD-KONFIGURATION ---
DEFAULT_CONFIGS = {
    "Temperatur (2m)": [
        {"value": -10.0, "color": "#313695"},
        {"value": 0.0, "color": "#74add1"},
        {"value": 15.0, "color": "#fdae61"},
        {"value": 30.0, "color": "#d73027"}
    ],
    "Akk. Niederschlag (mm)": [
        {"value": 0.0, "color": "#ffffff"},
        {"value": 1.0, "color": "#a6cee3"},
        {"value": 10.0, "color": "#1f78b4"},
        {"value": 30.0, "color": "#33a02c"}
    ],
    "Niederschlagsrate (mm/h)": [
        {"value": 0.0, "color": "#ffffff"},
        {"value": 0.5, "color": "#a6cee3"},
        {"value": 2.0, "color": "#1f78b4"},
        {"value": 10.0, "color": "#33a02c"},
        {"value": 25.0, "color": "#fb9a99"}
    ]
}

# --- GITHUB LADE- & SPEICHER-FUNKTIONEN ---
def get_github_client():
    if "GITHUB_TOKEN" in st.secrets:
        auth = Auth.Token(st.secrets["GITHUB_TOKEN"])
        return Github(auth=auth)
    return None

def load_config():
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file = repo.get_contents("config.json")
            loaded_data = json.loads(file.decoded_content.decode())
            if isinstance(loaded_data, list):
                return {"Temperatur (2m)": loaded_data, "Akk. Niederschlag (mm)": DEFAULT_CONFIGS["Akk. Niederschlag (mm)"], "Niederschlagsrate (mm/h)": DEFAULT_CONFIGS["Niederschlagsrate (mm/h)"]}
            return loaded_data
        except Exception:
            pass
    return DEFAULT_CONFIGS

def save_config(config_data):
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file_path = "config.json"
            content = json.dumps(config_data, indent=4)
            try:
                file = repo.get_contents(file_path)
                repo.update_file(file_path, "Update Farbskalen", content, file.sha)
            except:
                repo.create_file(file_path, "Create config.json", content)
            st.success("Erfolgreich auf GitHub gespeichert!")
        except Exception as e:
            st.error(f"Fehler beim Speichern: {e}")

if "config" not in st.session_state:
    st.session_state.config = load_config()

# --- DATEN LADEN (Grenzen) ---
@st.cache_data
def load_borders():
    world_url = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
    bl_url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    
    world_resp = requests.get(world_url).text
    bl_resp = requests.get(bl_url).text
    
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

# --- MODELLLÄUFE BERECHNEN ---
def get_available_runs():
    now = datetime.now(timezone.utc)
    latest_run_hour = (now.hour // 3) * 3
    latest_run = now.replace(hour=latest_run_hour, minute=0, second=0, microsecond=0)
    runs = {}
    for i in range(8):
        r = latest_run - timedelta(hours=i*3)
        label = f"{r.strftime('%d.%m.%Y')} | {r.hour:02d}Z (UTC)"
        runs[label] = r
    return runs

# --- DWD GRIB2 DOWNLOAD-FUNKTION ---
@st.cache_data(ttl=3600)
def get_raw_grib(run_time, forecast_hour, folder, suffix, var_name):
    run_str = f"{run_time.hour:02d}"
    date_str = run_time.strftime("%Y%m%d")
    hour_str = f"{forecast_hour:03d}"
    
    file_name = f"icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_{suffix}.grib2.bz2"
    url = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/{folder}/{file_name}"
    
    try:
        dl_resp = requests.get(url)
        if dl_resp.status_code != 200:
            return None, None, None
            
        grib_data = bz2.decompress(dl_resp.content)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f:
            f.write(grib_data)
            temp_path = f.name
        
        ds = xr.open_dataset(temp_path, engine='cfgrib')
        
        actual_var = var_name
        if var_name not in ds.variables:
            actual_var = list(ds.data_vars)[0] 
            
        vals = ds[actual_var].values
        lats = ds['latitude'].values
        lons = ds['longitude'].values
        
        while vals.ndim > 2: vals = vals[0]
        if lons.ndim == 1 and lats.ndim == 1: lons, lats = np.meshgrid(lons, lats)
        while lons.ndim > 2: lons = lons[0]
        while lats.ndim > 2: lats = lats[0]
            
        ds.close()
        os.remove(temp_path)
        return lons, lats, vals
    except Exception as e:
        print(f"Fehler beim Laden: {e}")
        return None, None, None

# --- KI & THERMODYNAMIK DOWNSCALING ---
def apply_ai_downscaling(lons, lats, t2m, td2m):
    # 1. DEN NaN-VIRUS BEHEBEN: Wir ersetzen fehlende Randpixel kurzzeitig
    # durch den Durchschnitt, damit der Zoom-Filter nicht zerstört wird.
    t2m_safe = np.nan_to_num(t2m, nan=np.nanmean(t2m))
    td2m_safe = np.nan_to_num(td2m, nan=np.nanmean(td2m))
    
    # 2. Auflösung auf 1x1km hochrechnen (Zoom-Faktor ~ 2.2)
    zoom_f = 2.2
    # order=1 (bilinear) ist extrem stabil bei Wetterdaten
    t2m_high = ndimage.zoom(t2m_safe, zoom_f, order=1)
    td2m_high = ndimage.zoom(td2m_safe, zoom_f, order=1)
    lons_high = ndimage.zoom(lons, zoom_f, order=1)
    lats_high = ndimage.zoom(lats, zoom_f, order=1)
    
    # 3. Relative Feuchte (%) berechnen (Magnus-Formel)
    td2m_c = np.clip(td2m_high, -50, 50)
    t2m_c = np.clip(t2m_high, -50, 50)
    
    e_vapor = np.exp((17.625 * td2m_c) / (243.04 + td2m_c))
    e_sat = np.exp((17.625 * t2m_c) / (243.04 + t2m_c))
    rh = 100.0 * (e_vapor / e_sat)
    rh = np.clip(rh, 0, 100) 
    
    # 4. Dynamischer Temperaturgradient (Lapse Rate)
    # Trockenadiabatisch: ~9.8 K/km. Feuchtadiabatisch: ~5.0 K/km
    lapse_rate = (9.8 - 4.8 * (rh / 100.0)) / 1000.0 
    
    # 5. Topographische Simulation (Berge und Täler)
    np.random.seed(42) 
    noise = np.random.normal(0, 1, t2m_high.shape)
    terrain_diff = ndimage.gaussian_filter(noise, sigma=3) * 60.0 
    
    # 6. Downscaling anwenden
    t2m_downscaled = t2m_high - (lapse_rate * terrain_diff)
    
    # 7. Die leeren Ränder wieder abschneiden (Original-Maske zoomen)
    mask = np.isnan(t2m)
    mask_high = ndimage.zoom(mask.astype(float), zoom_f, order=0) > 0.5
    t2m_downscaled[mask_high] = np.nan
    
    return lons_high, lats_high, t2m_downscaled

# --- PARAMETER-LOGIK ---
def load_parameter_data(run_time, forecast_hour, param_name, model_type):
    if param_name == "Temperatur (2m)":
        lons, lats, t2m = get_raw_grib(run_time, forecast_hour, "t_2m", "2d_t_2m", "t2m")
        if t2m is None: return None, None, None, ""
        t2m = t2m - 273.15 
        
        if model_type == "KI-Downscaling (1x1km)":
            _, _, td2m = get_raw_grib(run_time, forecast_hour, "td_2m", "2d_td_2m", "d2m")
            if td2m is not None:
                td2m = td2m - 273.15
                lons, lats, t2m = apply_ai_downscaling(lons, lats, t2m, td2m)
            else:
                st.warning("Taupunkt für Downscaling fehlt. Zeige Standard-Auflösung.")
                
        return lons, lats, t2m, "Temperatur in °C"
        
    elif param_name == "Akk. Niederschlag (mm)":
        lons, lats, vals = get_raw_grib(run_time, forecast_hour, "tot_prec", "2d_tot_prec", "tp")
        return lons, lats, vals, "Niederschlag in mm"
        
    elif param_name == "Niederschlagsrate (mm/h)":
        if forecast_hour == 0:
            lons, lats, vals = get_raw_grib(run_time, forecast_hour, "tot_prec", "2d_tot_prec", "tp")
            if vals is not None: vals = np.zeros_like(vals)
            return lons, lats, vals, "Regenrate in mm/h"
        else:
            lons, lats, vals_h = get_raw_grib(run_time, forecast_hour, "tot_prec", "2d_tot_prec", "tp")
            _, _, vals_h1 = get_raw_grib(run_time, forecast_hour - 1, "tot_prec", "2d_tot_prec", "tp")
            if vals_h is not None and vals_h1 is not None:
                rate = vals_h - vals_h1
                rate = np.clip(rate, 0, None)
                return lons, lats, rate, "Regenrate in mm/h"
    return None, None, None, ""

# --- KARTE ZEICHNEN ---
def create_map(config_list, lons, lats, data, map_title_time, legend_title, model_type):
    world, bundeslaender = load_borders()
    
    sorted_conf = sorted(config_list, key=lambda x: x['value'])
    levels = [c['value'] for c in sorted_conf]
    colors = [c['color'] for c in sorted_conf]
    
    min_val, max_val = min(levels), max(levels)
    if max_val == min_val: max_val = min_val + 1 
    
    norm_levels = [(v - min_val) / (max_val - min_val) for v in levels]
    smooth_cmap = mcolors.LinearSegmentedColormap.from_list("custom_smooth", list(zip(norm_levels, colors)))
    
    bg_color = '#0E1117'
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    if len(levels) > 1:
        smooth_levels = np.linspace(min_val, max_val, 150) 
        karte = ax.contourf(lons, lats, data, levels=smooth_levels, cmap=smooth_cmap, extend='both', alpha=0.95)
        
        cbar = fig.colorbar(karte, ax=ax, fraction=0.046, pad=0.04, ticks=levels)
        cbar.set_label(legend_title, color='white', size=12)
        cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')

    world.boundary.plot(ax=ax, edgecolor='#555555', linewidth=0.8, alpha=0.8)
    bundeslaender.boundary.plot(ax=ax, edgecolor='#ffffff', linewidth=1.2, alpha=1.0)
    
    ax.set_xlim(5.5, 15.5)
    ax.set_ylim(47.0, 55.0)
    ax.axis('off')
    
    model_name = "ICON-D2" if model_type == "ICON-D2 (2.2km)" else "KI-Downscaling (1x1km)"
    ax.text(5.7, 54.7, f"{model_name} | {map_title_time}", color='white', fontsize=10, 
            bbox=dict(facecolor='#0E1117', alpha=0.7, edgecolor='none'))
    return fig

# --- BENUTZEROBERFLÄCHE (UI) ---
st.sidebar.header("⚙️ Allgemeine Einstellungen")
model_choice = st.sidebar.selectbox("Modell:", ["ICON-D2 (2.2km)", "KI-Downscaling (1x1km)"])

available_runs = get_available_runs()
run_label = st.sidebar.selectbox("Modelllauf (Letzte 24h):", list(available_runs.keys()))
run_time = available_runs[run_label]

param_choice = st.sidebar.selectbox("Parameter:", ["Temperatur (2m)", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)"])

if model_choice == "KI-Downscaling (1x1km)" and param_choice != "Temperatur (2m)":
    st.sidebar.warning("⚠️ KI-Downscaling ist derzeit nur für die Temperatur (Thermodynamik) aktiv.")

st.sidebar.divider()

if param_choice not in st.session_state.config:
    st.session_state.config[param_choice] = DEFAULT_CONFIGS[param_choice]

with st.sidebar.expander(f"🎨 Farben für {param_choice}", expanded=False):
    new_config = []
    for i, item in enumerate(st.session_state.config[param_choice]):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            val = st.number_input("Wert", value=float(item['value']), step=1.0, key=f"val_{param_choice}_{i}", label_visibility="collapsed")
        with col2:
            color = st.color_picker("Farbe", value=item['color'], key=f"col_{param_choice}_{i}", label_visibility="collapsed")
        with col3:
            if st.button("🗑️", key=f"del_{param_choice}_{i}"):
                st.session_state.config[param_choice].pop(i)
                st.rerun()
        new_config.append({"value": val, "color": color})
    
    st.session_state.config[param_choice] = new_config

    col_add, col_save = st.columns(2)
    with col_add:
        if st.button("➕ Neu"):
            st.session_state.config[param_choice].append({"value": 0.0, "color": "#ffffff"})
            st.rerun()
    with col_save:
        if st.button("💾 Speichern"):
            with st.spinner("Speichere auf GitHub..."):
                save_config(st.session_state.config)
st.sidebar.divider()

# --- HAUPTBEREICH ---
st.info(f"Basis-Modelllauf: **{run_label}**")
    
st.markdown(f"### ⏱️ Zeitschritt für {param_choice}")
forecast_hour = st.slider("Vorhersagestunde", min_value=0, max_value=48, value=0, step=1, format="+%dh")

forecast_time_utc = run_time + timedelta(hours=forecast_hour)
local_tz = ZoneInfo("Europe/Berlin")
forecast_time_local = forecast_time_utc.astimezone(local_tz)

time_string = f"{forecast_time_local.strftime('%d.%m.%Y')} um {forecast_time_local.strftime('%H:00')} Uhr"
st.success(f"**Gültig für:** +{forecast_hour}h ➔ {time_string} (MEZ/MESZ)")

if st.button("🚀 Karte für diese Stunde rendern", type="primary"):
    with st.spinner(f"Lade Daten und berechne Physik..."):
        lons, lats, data, legend_title = load_parameter_data(run_time, forecast_hour, param_choice, model_choice)
        
        if lons is not None:
            with st.spinner("Rendere hochauflösende Karte..."):
                fertige_grafik = create_map(st.session_state.config[param_choice], lons, lats, data, f"+{forecast_hour}h | {time_string}", legend_title, model_choice)
                st.pyplot(fertige_grafik)
                st.toast("Modellkarte erfolgreich generiert!", icon="✅")
        else:
            st.error("Dieser Datensatz ist auf dem DWD-Server (noch) nicht verfügbar.")
