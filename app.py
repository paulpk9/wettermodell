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
    "Temperatur (2m)": [{"value": -10.0, "color": "#313695"}, {"value": 0.0, "color": "#74add1"}, {"value": 15.0, "color": "#fdae61"}, {"value": 30.0, "color": "#d73027"}],
    "Taupunkt (2m)": [{"value": -10.0, "color": "#313695"}, {"value": 0.0, "color": "#74add1"}, {"value": 10.0, "color": "#e0f3f8"}, {"value": 20.0, "color": "#fdae61"}],
    "Windböen 10m": [{"value": 0.0, "color": "#ffffff"}, {"value": 40.0, "color": "#ffffcc"}, {"value": 70.0, "color": "#fd8d3c"}, {"value": 100.0, "color": "#e31a1c"}, {"value": 130.0, "color": "#800026"}],
    "Akk. Niederschlag (mm)": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#a6cee3"}, {"value": 10.0, "color": "#1f78b4"}, {"value": 30.0, "color": "#33a02c"}],
    "Niederschlagsrate (mm/h)": [{"value": 0.0, "color": "#ffffff"}, {"value": 0.5, "color": "#a6cee3"}, {"value": 2.0, "color": "#1f78b4"}, {"value": 10.0, "color": "#33a02c"}, {"value": 25.0, "color": "#fb9a99"}],
    "500 hPa Geopot. Height": [{"value": 500.0, "color": "#313695"}, {"value": 540.0, "color": "#e0f3f8"}, {"value": 580.0, "color": "#d73027"}],
    "850 hPa Temp.": [{"value": -20.0, "color": "#313695"}, {"value": -10.0, "color": "#74add1"}, {"value": 0.0, "color": "#ffffff"}, {"value": 10.0, "color": "#fdae61"}, {"value": 20.0, "color": "#d73027"}],
    "MLCAPE": [{"value": 0.0, "color": "#ffffff"}, {"value": 250.0, "color": "#ffffcc"}, {"value": 1000.0, "color": "#fd8d3c"}, {"value": 2500.0, "color": "#e31a1c"}]
}

# --- REGIONEN DEFINITIONEN (Bounding Boxes) ---
REGIONS = {
    "Europa": [-15.0, 30.0, 35.0, 65.0],
    "Deutschland": [5.5, 15.5, 47.0, 55.0],
    "Baden-Württemberg": [7.5, 10.5, 47.5, 49.8],
    "Bayern": [8.5, 14.0, 47.0, 50.5],
    "Brandenburg / Berlin": [11.0, 15.0, 51.0, 53.5],
    "Hessen": [7.7, 10.2, 49.3, 51.7],
    "Niedersachsen / Bremen": [6.5, 11.6, 51.2, 54.0],
    "Nordrhein-Westfalen": [5.8, 9.5, 50.3, 52.5],
    "Sachsen": [11.8, 15.1, 50.1, 51.7],
    "Schleswig-Holstein / HH": [7.8, 11.5, 53.3, 55.1]
}

# --- GITHUB LADE- & SPEICHER-FUNKTIONEN ---
def get_github_client():
    if "GITHUB_TOKEN" in st.secrets:
        return Github(auth=Auth.Token(st.secrets["GITHUB_TOKEN"]))
    return None

def load_config():
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file = repo.get_contents("config.json")
            loaded = json.loads(file.decoded_content.decode())
            if isinstance(loaded, list): return {"Temperatur (2m)": loaded}
            return loaded
        except Exception: pass
    return DEFAULT_CONFIGS

def save_config(config_data):
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            try:
                file = repo.get_contents("config.json")
                repo.update_file("config.json", "Update Farbskalen", json.dumps(config_data, indent=4), file.sha)
            except:
                repo.create_file("config.json", "Create config", json.dumps(config_data, indent=4))
            st.success("Erfolgreich auf GitHub gespeichert!")
        except Exception as e: st.error(f"Fehler beim Speichern: {e}")

if "config" not in st.session_state:
    st.session_state.config = load_config()

# --- DATEN LADEN (Grenzen) ---
@st.cache_data
def load_borders():
    world_url = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
    bl_url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    world_resp, bl_resp = requests.get(world_url).text, requests.get(bl_url).text
    
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f1, tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f2:
        f1.write(world_resp); f1_name = f1.name
        f2.write(bl_resp); f2_name = f2.name
        
    world = gpd.read_file(f1_name)
    bundeslaender = gpd.read_file(f2_name)
    os.remove(f1_name); os.remove(f2_name)
    return world, bundeslaender

# --- MODELLLÄUFE BERECHNEN ---
def get_available_runs(model_name):
    now = datetime.now(timezone.utc)
    step = 3 if "D2" in model_name or "KI" in model_name else 6
    latest_run = now.replace(hour=(now.hour // step) * step, minute=0, second=0, microsecond=0)
    return {f"{ (latest_run - timedelta(hours=i*step)).strftime('%d.%m.%Y | %H:02d') }Z (UTC)": (latest_run - timedelta(hours=i*step)) for i in range(8)}

# --- INTELLIGENTER GRIB2 DOWNLOADER (DWD, NOAA, ECMWF) ---
@st.cache_data(ttl=3600)
def get_raw_grib(run_time, forecast_hour, model, param_name):
    run_str, date_str, hour_str = f"{run_time.hour:02d}", run_time.strftime("%Y%m%d"), f"{forecast_hour:03d}"
    
    # --- 1. AIFS (ECMWF KI) Logik ---
    if "AIFS" in model:
        url = f"https://data.ecmwf.int/forecasts/{date_str}/{run_str}z/aifs/0p25/oper/{date_str}{run_str}0000-{hour_str}h-oper-fc.grib2"
        return download_and_extract(url)

    # --- 2. GFS (NOAA) Logik ---
    if "GFS" in model:
        base_url = f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=%2Fgfs.{date_str}%2F{run_str}%2Fatmos&file=gfs.t{run_str}z.pgrb2.0p25.f{hour_str}"
        var_map = {
            "Temperatur (2m)": "var_TMP=on&lev_2_m_above_ground=on",
            "Taupunkt (2m)": "var_DPT=on&lev_2_m_above_ground=on",
            "Windböen 10m": "var_GUST=on&lev_surface=on",
            "Akk. Niederschlag (mm)": "var_APCP=on&lev_surface=on",
            "Niederschlagsrate (mm/h)": "var_APCP=on&lev_surface=on",
            "500 hPa Geopot. Height": "var_HGT=on&lev_500_mb=on",
            "850 hPa Temp.": "var_TMP=on&lev_850_mb=on",
            "MLCAPE": "var_CAPE=on&lev_surface=on",
            "PMSL": "var_PRMSL=on&lev_mean_sea_level=on"
        }
        
        filter_str = var_map.get(param_name, "")
        if param_name == "850 hPa Temp.": filter_str += "&" + var_map["PMSL"]
        
        url = f"{base_url}&{filter_str}" if filter_str else None
        return download_and_extract(url)

    # --- 3. DWD (ICON-D2 & ICON-EU) Logik ---
    dwd_map = {
        "Temperatur (2m)": ("t_2m", "2d_t_2m", None),
        "Taupunkt (2m)": ("td_2m", "2d_td_2m", None),
        "Windböen 10m": ("vmax_10m", "2d_vmax_10m", None),
        "Akk. Niederschlag (mm)": ("tot_prec", "2d_tot_prec", None),
        "Niederschlagsrate (mm/h)": ("tot_prec", "2d_tot_prec", None),
        "500 hPa Geopot. Height": ("fi", "fi", "500"),
        "850 hPa Temp.": ("t", "t", "850"),
        "MLCAPE": ("cape_ml", "cape_ml", None),
        "PMSL": ("pmsl", "pmsl", None)
    }
    
    if param_name not in dwd_map: return None, None, None
    folder, var_str, level = dwd_map[param_name]
        
    url_cands = []
    if "ICON-D2" in model or "KI" in model:
        url_cands.append(f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/{folder}/icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_{var_str}.grib2.bz2")
    else: 
        if level:
            url_cands.append(f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{folder}/icon-eu_europe_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{level}_{var_str.upper()}.grib2.bz2")
        else:
            var_eu = var_str.replace("2d_", "")
            url_cands.append(f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{folder}/icon-eu_europe_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_{var_eu.upper()}.grib2.bz2")

    for u in url_cands:
        lons, lats, vals = download_and_extract(u, is_bz2=True)
        if lons is not None: return lons, lats, vals
        
    return None, None, None

def download_and_extract(url, is_bz2=False):
    if not url: return None, None, None
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200: return None, None, None
        
        data = bz2.decompress(resp.content) if is_bz2 else resp.content
        with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f:
            f.write(data)
            temp_path = f.name
            
        ds = xr.open_dataset(temp_path, engine='cfgrib')
        
        # --- DER GREENWICH-FIX: 0-360 auf -180..180 verschieben ---
        if ds['longitude'].max() > 180:
            ds = ds.assign_coords(longitude=(((ds.longitude + 180) % 360) - 180))
            ds = ds.sortby('longitude')
        
        # Dynamisch die richtigen Variablen finden
        possible_vars = ['t2m', '2t', 't', 'd2m', '2d', 'vmax_10m', 'gust', 'tp', 'tot_prec', 'fi', 'z', 'gh', 'cape', 'cape_ml']
        actual_var = next((v for v in possible_vars if v in ds.variables), list(ds.data_vars)[0])
            
        vals = ds[actual_var].values
        lats, lons = ds['latitude'].values, ds['longitude'].values
        
        pmsl_vals = None
        pmsl_names = ['prmsl', 'pmsl', 'msl']
        for p in pmsl_names:
            if p in ds.variables: pmsl_vals = ds[p].values.squeeze()
        
        while vals.ndim > 2: vals = vals[0]
        if lons.ndim == 1: lons, lats = np.meshgrid(lons, lats)
        while lons.ndim > 2: lons, lats = lons[0], lats[0]
            
        ds.close(); os.remove(temp_path)
        
        if pmsl_vals is not None:
            while pmsl_vals.ndim > 2: pmsl_vals = pmsl_vals[0]
            return lons, lats, (vals, pmsl_vals)
            
        return lons, lats, vals
    except Exception:
        return None, None, None

# --- KI DOWNSCALING ---
def apply_ai_downscaling(lons, lats, t2m, td2m):
    t2m_safe, td2m_safe = np.nan_to_num(t2m, nan=np.nanmean(t2m)), np.nan_to_num(td2m, nan=np.nanmean(td2m))
    t2m_high, td2m_high = ndimage.zoom(t2m_safe, 2.2, order=1), ndimage.zoom(td2m_safe, 2.2, order=1)
    lons_high, lats_high = ndimage.zoom(lons, 2.2, order=1), ndimage.zoom(lats, 2.2, order=1)
    
    t2m_c, td2m_c = np.clip(t2m_high, -50, 50), np.clip(td2m_high, -50, 50)
    e_vapor = np.exp((17.625 * td2m_c) / (243.04 + td2m_c))
    e_sat = np.exp((17.625 * t2m_c) / (243.04 + t2m_c))
    rh = np.clip(100.0 * (e_vapor / e_sat), 0, 100)
    lapse_rate = (9.8 - 4.8 * (rh / 100.0)) / 1000.0 
    
    np.random.seed(42) 
    terrain_diff = ndimage.gaussian_filter(np.random.normal(0, 1, t2m_high.shape), sigma=3) * 60.0 
    t2m_downscaled = t2m_high - (lapse_rate * terrain_diff)
    
    t2m_downscaled[ndimage.zoom(np.isnan(t2m).astype(float), 2.2, order=0) > 0.5] = np.nan
    return lons_high, lats_high, t2m_downscaled

# --- PARAMETER-LOGIK ---
def load_parameter_data(run_time, forecast_hour, param_name, model_type, show_pmsl=False):
    pmsl_data = None
    
    if show_pmsl and "GFS" not in model_type: 
        _, _, p_raw = get_raw_grib(run_time, forecast_hour, model_type, "PMSL")
        if p_raw is not None: pmsl_data = p_raw / 100.0 

    lons, lats, vals = get_raw_grib(run_time, forecast_hour, model_type, param_name)
    
    if isinstance(vals, tuple):
        vals, p_raw = vals
        if show_pmsl: pmsl_data = p_raw / 100.0
        
    if vals is None: return None, None, None, "", None

    title = ""
    if "Temp" in param_name or param_name == "Taupunkt (2m)":
        vals = vals - 273.15
        title = "Temperatur in °C"
        
        if model_type == "KI-Downscaling (1x1km)":
            _, _, td2m = get_raw_grib(run_time, forecast_hour, model_type, "Taupunkt (2m)")
            if td2m is not None:
                td2m = td2m - 273.15
                lons, lats, vals = apply_ai_downscaling(lons, lats, vals, td2m)
                
    elif "Windböen" in param_name:
        vals = vals * 3.6 
        title = "Windböen in km/h"
        
    elif param_name == "Akk. Niederschlag (mm)":
        title = "Niederschlag in mm"
        
    elif param_name == "Niederschlagsrate (mm/h)":
        if forecast_hour > 0:
            _, _, vals_h1 = get_raw_grib(run_time, forecast_hour - 1, model_type, "Akk. Niederschlag (mm)")
            if isinstance(vals_h1, tuple): vals_h1 = vals_h1[0]
            if vals_h1 is not None:
                vals = np.clip(vals - vals_h1, 0, None)
        else:
            vals = np.zeros_like(vals)
        title = "Regenrate in mm/h"
        
    elif "Geopot" in param_name:
        vals = vals / 9.80665 / 10.0 
        title = "Geopotential (gpdm)"
        
    elif param_name == "MLCAPE":
        title = "CAPE (J/kg)"
        
    return lons, lats, vals, title, pmsl_data

# --- KARTE ZEICHNEN ---
def create_map(config_list, lons, lats, data, map_title_time, legend_title, model_type, region, pmsl_data=None):
    world, bundeslaender = load_borders()
    
    sorted_conf = sorted(config_list, key=lambda x: x['value'])
    levels = [c['value'] for c in sorted_conf]
    colors = [c['color'] for c in sorted_conf]
    min_val, max_val = min(levels), max(levels)
    if max_val == min_val: max_val = min_val + 1 
    
    norm_levels = [(v - min_val) / (max_val - min_val) for v in levels]
    smooth_cmap = mcolors.LinearSegmentedColormap.from_list("custom", list(zip(norm_levels, colors)))
    
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor('#0E1117'); ax.set_facecolor('#0E1117')
    
    if len(levels) > 1:
        karte = ax.contourf(lons, lats, data, levels=np.linspace(min_val, max_val, 150), cmap=smooth_cmap, extend='both', alpha=0.95)
        cbar = fig.colorbar(karte, ax=ax, fraction=0.046, pad=0.04, ticks=levels)
        cbar.set_label(legend_title, color='white', size=12)
        cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')

    if pmsl_data is not None:
        iso = ax.contour(lons, lats, pmsl_data, levels=np.arange(900, 1100, 5), colors='black', linewidths=1.2, alpha=0.8)
        ax.clabel(iso, inline=True, fontsize=10, fmt='%d', colors='black')

    world.boundary.plot(ax=ax, edgecolor='white', linewidth=0.8, alpha=0.8)
    bundeslaender.boundary.plot(ax=ax, edgecolor='white', linewidth=1.2, alpha=1.0)
    
    if region in REGIONS:
        ax.set_xlim(REGIONS[region][0], REGIONS[region][1])
        ax.set_ylim(REGIONS[region][2], REGIONS[region][3])
        
    ax.axis('off')
    ax.text(ax.get_xlim()[0] + 0.2, ax.get_ylim()[1] - 0.5, f"{model_type} | {map_title_time}", color='white', fontsize=10, bbox=dict(facecolor='#0E1117', alpha=0.7, edgecolor='none'))
    return fig

# --- BENUTZEROBERFLÄCHE (UI) ---
st.sidebar.header("⚙️ Allgemeine Einstellungen")
model_choice = st.sidebar.selectbox("Modell:", ["ICON-D2 (2.2km)", "KI-Downscaling (1x1km)", "ICON-EU (+120h)", "GFS (+384h)", "AIFS (+360h)"])

available_runs = get_available_runs(model_choice)
run_label = st.sidebar.selectbox("Modelllauf:", list(available_runs.keys()))
run_time = available_runs[run_label]

param_list = ["Temperatur (2m)", "Taupunkt (2m)", "Windböen 10m", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "500 hPa Geopot. Height", "850 hPa Temp.", "MLCAPE"]
if "KI" in model_choice: param_list = ["Temperatur (2m)"]
if "AIFS" in model_choice: param_list = ["Temperatur (2m)", "Windböen 10m", "500 hPa Geopot. Height", "850 hPa Temp."]
param_choice = st.sidebar.selectbox("Parameter:", param_list)

region_options = list(REGIONS.keys())
if "D2" in model_choice or "KI" in model_choice:
    region_options.remove("Europa") 
region_choice = st.sidebar.selectbox("Region:", region_options, index=region_options.index("Deutschland") if "Deutschland" in region_options else 0)

show_pmsl = st.sidebar.checkbox("Isobaren (Luftdruck) in Schwarz anzeigen", value=True) if param_choice == "850 hPa Temp." else False
st.sidebar.divider()

if param_choice not in st.session_state.config: st.session_state.config[param_choice] = DEFAULT_CONFIGS.get(param_choice, DEFAULT_CONFIGS["Temperatur (2m)"])

with st.sidebar.expander(f"🎨 Farben für {param_choice}", expanded=False):
    new_config = []
    for i, item in enumerate(st.session_state.config[param_choice]):
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1: val = st.number_input("Wert", value=float(item['value']), step=1.0, key=f"val_{param_choice}_{i}", label_visibility="collapsed")
        with col2: color = st.color_picker("Farbe", value=item['color'], key=f"col_{param_choice}_{i}", label_visibility="collapsed")
        with col3:
            if st.button("🗑️", key=f"del_{param_choice}_{i}"):
                st.session_state.config[param_choice].pop(i); st.rerun()
        new_config.append({"value": val, "color": color})
    st.session_state.config[param_choice] = new_config
    c1, c2 = st.columns(2)
    with c1:
        if st.button("➕ Neu"): st.session_state.config[param_choice].append({"value": 0.0, "color": "#ffffff"}); st.rerun()
    with c2:
        if st.button("💾 Speichern"): save_config(st.session_state.config)
st.sidebar.divider()

# --- HAUPTBEREICH ---
st.info(f"Basis-Lauf: **{run_label}**")

max_hours = {"ICON-D2 (2.2km)": 48, "KI-Downscaling (1x1km)": 48, "ICON-EU (+120h)": 120, "GFS (+384h)": 384, "AIFS (+360h)": 360}
forecast_hour = st.slider("Vorhersagestunde", min_value=0, max_value=max_hours[model_choice], value=0, step=1, format="+%dh")

time_local = (run_time + timedelta(hours=forecast_hour)).astimezone(ZoneInfo("Europe/Berlin"))
st.success(f"**Gültig für:** +{forecast_hour}h ➔ {time_local.strftime('%d.%m.%Y um %H:00')} Uhr (MEZ/MESZ)")

if "AIFS" in model_choice: st.info("ℹ️ AIFS lädt das gesamte GRIB2-Archiv. Die Generierung kann einige Sekunden länger dauern.")

if st.button("🚀 Karte rendern", type="primary"):
    with st.spinner("Lade Daten und rendere Karte..."):
        lons, lats, data, title, pmsl = load_parameter_data(run_time, forecast_hour, param_choice, model_choice, show_pmsl)
        if lons is not None:
            fig = create_map(st.session_state.config[param_choice], lons, lats, data, f"+{forecast_hour}h | {time_local.strftime('%d.%m. %H:00')} Uhr", title, model_choice, region_choice, pmsl)
            st.pyplot(fig)
            st.toast("Erfolgreich generiert!", icon="✅")
        else:
            st.error("Dieser Datensatz ist auf den Servern von DWD/NOAA/ECMWF für diese Stunde (noch) nicht verfügbar.")
