import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as path_effects
import geopandas as gpd
from github import Github, Auth
import json
import requests
import bz2
import tempfile
import os
import uuid
import pandas as pd
from PIL import Image
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import xarray as xr
import scipy.ndimage as ndimage
import io

# --- SEITEN-LAYOUT & CSS ---
st.set_page_config(page_title="Profi-Wetterterminal", page_icon="🌤️", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
        img { border-radius: 12px; box-shadow: 0 8px 25px rgba(0, 0, 0, 0.5); transition: all 0.3s ease; }
        .glass-banner {
            background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 12px; padding: 18px 25px;
            text-align: center; font-size: 1.25em; font-weight: 600; margin-bottom: 25px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2); letter-spacing: 0.5px;
        }
        .stSlider > div > div > div { background: linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%); }
        [data-testid="stColorPicker"] input { display: none !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🗺️ Statische Modellkarte (Profi-Terminal)")

# --- GITHUB CLIENT ---
def get_github_client(): return Github(auth=Auth.Token(st.secrets["GITHUB_TOKEN"])) if "GITHUB_TOKEN" in st.secrets else None

# --- DESIGN DEFAULTS & SPEICHER-LOGIK ---
DEFAULT_DESIGN = {
    "bg_color": "#0E1117", "title_bg": "#0E1117", "text_color": "#FFFFFF", 
    "border_color": "#FFFFFF", "border_alpha": 0.4, "font_family": "sans-serif",
    "cbar_step": 1, "number_color": "#000000", "number_outline": "#FFFFFF",
    "title_size": 11, "cbar_size": 11, "line_width": 0.8, "watermark": "", "discrete_colors": False
}

def load_design_config():
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            data = json.loads(repo.get_contents("configs/design_config.json").decoded_content.decode())
            return {**DEFAULT_DESIGN, **data}
        except: pass
    return DEFAULT_DESIGN.copy()

def save_design_config(design_dict):
    g, repo_name = get_github_client(), st.secrets.get("GITHUB_REPO")
    if g and repo_name:
        try:
            repo = g.get_repo(repo_name)
            filepath = "configs/design_config.json"
            try: 
                file = repo.get_contents(filepath)
                repo.update_file(filepath, "Update Design-Config", json.dumps(design_dict, indent=4), file.sha)
            except: 
                repo.create_file(filepath, "Create Design-Config", json.dumps(design_dict, indent=4))
            st.success("Design & Wasserzeichen erfolgreich auf GitHub gespeichert!")
        except Exception as e: st.error(f"Fehler beim Speichern: {e}")

# --- SYSTEM STATES ---
if "map_cache" not in st.session_state: st.session_state.map_cache = {}
if "f_hour" not in st.session_state: st.session_state.f_hour = 0
if "config" not in st.session_state: st.session_state.config = {}
if "design" not in st.session_state: st.session_state.design = load_design_config()

if "model_choice" not in st.session_state: st.session_state.model_choice = "ICON-D2 (2.2km)"
if "param_choice" not in st.session_state: st.session_state.param_choice = "Temperatur (2m)"
if "region_choice" not in st.session_state: st.session_state.region_choice = "Deutschland"

SIG_WETTER_LABELS = {
    1: "Regen (leicht)", 2: "Regen (mäßig)", 3: "Regen (stark)",
    4: "Schneeregen (leicht)", 5: "Schneeregen (mäßig)", 6: "Schneeregen (stark)",
    7: "Schnee (leicht)", 8: "Schnee (mäßig)", 9: "Schnee (stark)",
    10: "Gewitter (leicht)", 11: "Gewitter (stark)"
}

DEFAULT_CONFIGS = {
    "Temperatur (2m)": [{"value": -10.0, "color": "#313695"}, {"value": 0.0, "color": "#74add1"}, {"value": 15.0, "color": "#fdae61"}, {"value": 30.0, "color": "#d73027"}],
    "Windböen 10m": [{"value": 0.0, "color": "#ffffff"}, {"value": 40.0, "color": "#ffffcc"}, {"value": 70.0, "color": "#fd8d3c"}, {"value": 100.0, "color": "#e31a1c"}, {"value": 130.0, "color": "#800026"}],
    "Akk. Niederschlag (mm)": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#a6cee3"}, {"value": 10.0, "color": "#1f78b4"}, {"value": 30.0, "color": "#33a02c"}],
    "Niederschlagsrate (mm/h)": [{"value": 0.0, "color": "#ffffff"}, {"value": 0.5, "color": "#a6cee3"}, {"value": 2.0, "color": "#1f78b4"}, {"value": 10.0, "color": "#33a02c"}],
    "500 hPa Geopot. Height": [{"value": 500.0, "color": "#313695"}, {"value": 540.0, "color": "#e0f3f8"}, {"value": 580.0, "color": "#d73027"}],
    "850 hPa Temp.": [{"value": -20.0, "color": "#313695"}, {"value": -10.0, "color": "#74add1"}, {"value": 0.0, "color": "#ffffff"}, {"value": 10.0, "color": "#fdae61"}, {"value": 20.0, "color": "#d73027"}],
    "MLCAPE": [{"value": 0.0, "color": "#ffffff"}, {"value": 250.0, "color": "#ffffcc"}, {"value": 1000.0, "color": "#fd8d3c"}, {"value": 2500.0, "color": "#e31a1c"}],
    "CIN": [{"value": 0.0, "color": "#ffffff"}, {"value": 50.0, "color": "#a6cee3"}, {"value": 200.0, "color": "#1f78b4"}, {"value": 500.0, "color": "#08306b"}],
    "CAPE & CIN (Deckel)": [{"value": 0.0, "color": "#ffffff"}, {"value": 250.0, "color": "#ffffcc"}, {"value": 1000.0, "color": "#fd8d3c"}, {"value": 2500.0, "color": "#e31a1c"}],
    "Signifikantes Wetter": [
        {"value": 1.0, "color": "#a1d99b"}, {"value": 2.0, "color": "#31a354"}, {"value": 3.0, "color": "#006d2c"},
        {"value": 4.0, "color": "#fcc5c0"}, {"value": 5.0, "color": "#f768a1"}, {"value": 6.0, "color": "#ae017e"},
        {"value": 7.0, "color": "#c6dbef"}, {"value": 8.0, "color": "#6baed6"}, {"value": 9.0, "color": "#2171b5"},
        {"value": 10.0, "color": "#fd8d3c"}, {"value": 11.0, "color": "#e31a1c"}
    ]
}

REGIONS = {
    "Europa": [-15.0, 30.0, 35.0, 65.0], "Deutschland": [5.5, 15.5, 47.0, 55.0],
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

def get_config_filepath(param_name):
    safe_name = param_name.replace(" ", "_").replace("/", "_").replace(".", "")
    return f"configs/config_{safe_name}.json"

@st.cache_data(ttl=60, show_spinner=False)
def get_saved_config_files():
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            contents = repo.get_contents("configs")
            return [c.name for c in contents if c.name.endswith(".json") and not c.name.endswith("design_config.json")]
        except: pass
    return []

def load_param_config(param_name):
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            data = json.loads(repo.get_contents(get_config_filepath(param_name)).decoded_content.decode())
            if isinstance(data, list): return data
        except: pass
    return DEFAULT_CONFIGS.get(param_name, DEFAULT_CONFIGS["Temperatur (2m)"])

def save_param_config(param_name, config_list):
    g, repo_name = get_github_client(), st.secrets.get("GITHUB_REPO")
    if g and repo_name:
        try:
            clean_list = [{"value": float(c["value"]), "color": c["color"]} for c in config_list]
            repo = g.get_repo(repo_name)
            filepath = get_config_filepath(param_name)
            try: 
                file = repo.get_contents(filepath)
                repo.update_file(filepath, f"Update config for {param_name}", json.dumps(clean_list, indent=4), file.sha)
            except: 
                repo.create_file(filepath, f"Create config for {param_name}", json.dumps(clean_list, indent=4))
            st.success(f"Farbskala erfolgreich in {filepath} gespeichert!")
        except Exception as e: st.error(f"Fehler beim Speichern: {e}")

@st.cache_data
def load_borders():
    w_r = requests.get("https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson").text
    bl_r = requests.get("https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json").text
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f1, tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f2:
        f1.write(w_r); f1_name = f1.name; f2.write(bl_r); f2_name = f2.name
    return gpd.read_file(f1_name), gpd.read_file(f2_name)

@st.cache_data(ttl=86400, show_spinner=False)
def get_satellite_bg(lon_min, lon_max, lat_min, lat_max):
    url = f"https://s2maps-tiles.eu/wms/?service=WMS&request=GetMap&version=1.1.1&layers=s2cloudless-2020_3857&styles=&format=image/jpeg&transparent=false&width=1000&height=1000&srs=EPSG:4326&bbox={lon_min},{lat_min},{lon_max},{lat_max}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            return np.array(Image.open(io.BytesIO(resp.content)))
    except: pass
    return None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ensemble_data(lat, lon, param, model):
    url = f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}&hourly={param}&models={model}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json()
    except: pass
    return None

def get_available_runs(model_name):
    now = datetime.now(timezone.utc)
    if "RUC" in model_name: step, delay = 1, 2.5
    elif "AIFS" in model_name: step, delay = 12, 9.5
    elif "GFS" in model_name: step, delay = 6, 5.5
    elif "EU" in model_name: step, delay = 6, 3.5
    else: step, delay = 3, 2.5
    
    eff_now = now - timedelta(hours=delay)
    latest = eff_now.replace(hour=(eff_now.hour // step) * step, minute=0, second=0, microsecond=0)
    return {f"Lauf: { (latest - timedelta(hours=i*step)).strftime('%d.%m.%Y | %H:02d') }Z": (latest - timedelta(hours=i*step)) for i in range(6)}

@st.cache_data(ttl=3600, show_spinner=False)
def download_and_extract(url, is_bz2=False):
    if not url: return None, None, None
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla"}, timeout=15)
        if resp.status_code != 200: return None, None, None
        with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f: f.write(bz2.decompress(resp.content) if is_bz2 else resp.content); t_path = f.name
        ds = xr.open_dataset(t_path, engine='cfgrib')
        if ds['longitude'].max() > 180: ds = ds.assign_coords(longitude=(((ds.longitude + 180) % 360) - 180)).sortby('longitude')
        act_var = list(ds.data_vars)[0]
        vals, lats, lons = np.squeeze(ds[act_var].values), ds['latitude'].values, ds['longitude'].values
        pmsl_vals = next((np.squeeze(ds[p].values) for p in ['prmsl', 'pmsl', 'msl'] if p in ds.variables), None)
        while vals.ndim > 2: vals = vals[0]
        if lons.ndim == 1: lons, lats = np.meshgrid(lons, lats)
        while lons.ndim > 2: lons, lats = lons[0], lats[0]
        ds.close(); os.remove(t_path)
        if pmsl_vals is not None:
            while pmsl_vals.ndim > 2: pmsl_vals = pmsl_vals[0]
            return lons, lats, (vals, pmsl_vals)
        return lons, lats, vals
    except: return None, None, None

@st.cache_data(ttl=86400, show_spinner=False)
def get_topography(model):
    if "D2" in model: u = "https://opendata.dwd.de/weather/nwp/icon-d2/grib/00/hsurf/icon-d2_germany_regular-lat-lon_time-invariant_single-level_hsurf.grib2.bz2"
    elif "EU" in model: u = "https://opendata.dwd.de/weather/nwp/icon-eu/grib/00/hsurf/icon-eu_europe_regular-lat-lon_time-invariant_single-level_hsurf.grib2.bz2"
    else: return None, None, None
    return download_and_extract(u, is_bz2=True)

def get_raw_grib(run_time, forecast_hour, model, param_name):
    run_str, date_str, hour_str = f"{run_time.hour:02d}", run_time.strftime("%Y%m%d"), f"{forecast_hour:03d}"
    if param_name == "CAPE & CIN (Deckel)": return None, None, None

    if "GFS" in model:
        vm = {
            "Temperatur (2m)": "var_TMP=on&lev_2_m_above_ground=on", "Akk. Niederschlag (mm)": "var_APCP=on&lev_surface=on", 
            "Windböen 10m": "var_GUST=on&lev_surface=on", "Niederschlagsrate (mm/h)": "var_PRATE=on&lev_surface=on",
            "MLCAPE": "var_CAPE=on&lev_surface=on", "CIN": "var_CIN=on&lev_surface=on", "PMSL": "var_PRMSL=on&lev_mean_sea_level=on"
        }
        fs = vm.get(param_name, "")
        if param_name == "850 hPa Temp.": fs = "var_TMP=on&lev_850_mb=on&var_PRMSL=on&lev_mean_sea_level=on"
        return download_and_extract(f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=%2Fgfs.{date_str}%2F{run_str}%2Fatmos&file=gfs.t{run_str}z.pgrb2.0p25.f{hour_str}&{fs}" if fs else None)
    
    dm = {
        "Temperatur (2m)": ("t_2m", "2d_t_2m", None), "Windböen 10m": ("vmax_10m", "2d_vmax_10m", None), 
        "Akk. Niederschlag (mm)": ("tot_prec", "2d_tot_prec", None), "Niederschlagsrate (mm/h)": ("tot_prec", "2d_tot_prec", None), 
        "500 hPa Geopot. Height": ("fi", "fi", "500"), "850 hPa Temp.": ("t", "t", "850"), 
        "MLCAPE": ("cape_ml", "cape_ml", None), "CIN": ("cin_ml", "cin_ml", None),
        "PMSL": ("pmsl", "pmsl", None), "Signifikantes Wetter": ("ww", "ww", None)
    }
        
    if param_name not in dm: return None, None, None
    fld, var, lvl = dm[param_name]
    
    if lvl: 
        if "D2" in model: u = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/{fld}/icon-d2_germany_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_{var.upper()}.grib2.bz2"
        else: u = f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{fld}/icon-eu_europe_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_{var.upper()}.grib2.bz2"
    else: 
        if "D2" in model: u = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/{fld}/icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_{var}.grib2.bz2"
        else: u = f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{fld}/icon-eu_europe_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_{var.replace('2d_', '').upper()}.grib2.bz2"
        
    return download_and_extract(u, is_bz2=True)

def load_parameter_data(run_time, forecast_hour, param_name, model_type, overlays):
    pmsl_data, extra_overlay = None, None
    
    if param_name == "CAPE & CIN (Deckel)":
        lons, lats, cape_vals = get_raw_grib(run_time, forecast_hour, model_type, "MLCAPE")
        _, _, cin_vals = get_raw_grib(run_time, forecast_hour, model_type, "CIN")
        
        if isinstance(cape_vals, tuple): cape_vals, p_raw = cape_vals; pmsl_data = (p_raw / 100.0) if overlays.get('pmsl') else None
        if cape_vals is None or cin_vals is None: return None, None, None, "", None, None
        return lons, lats, np.squeeze(cape_vals), "CAPE (J/kg) & CIN-Deckel (Schraffur)", pmsl_data, np.squeeze(cin_vals)

    lons, lats, vals = get_raw_grib(run_time, forecast_hour, model_type, param_name)
    if isinstance(vals, tuple): vals, p_raw = vals; pmsl_data = (p_raw / 100.0) if overlays.get('pmsl') else None
    if vals is None: return None, None, None, "", None, None
    vals = np.squeeze(vals)
    
    title = ""
    if "Temp" in param_name: vals -= 273.15; title = "Temperatur in °C"
    elif "Windböen" in param_name: vals *= 3.6; title = "Windböen in km/h"
    elif param_name == "Akk. Niederschlag (mm)": title = "Niederschlag in mm"
    elif param_name == "Niederschlagsrate (mm/h)":
        if forecast_hour > 0:
            _, _, v1 = get_raw_grib(run_time, forecast_hour - 1, model_type, "Akk. Niederschlag (mm)")
            if isinstance(v1, tuple): v1 = v1[0]
            vals = np.clip(vals - v1, 0, None) if v1 is not None else vals
        else: vals = np.zeros_like(vals)
        title = "Regenrate in mm/h"
    elif "Geopot" in param_name: vals = vals / 9.80665 / 10.0; title = "Geopotential (gpdm)"
    elif param_name == "MLCAPE": title = "CAPE (J/kg)"
    elif param_name == "CIN": title = "CIN (J/kg)"
    elif param_name == "Signifikantes Wetter":
        title = "Signifikantes Wetter"
        ww = np.zeros_like(vals)
        ww[np.isin(vals, [50, 51, 58, 61, 80])] = 1
        ww[np.isin(vals, [52, 53, 59, 62, 81])] = 2
        ww[np.isin(vals, [54, 55, 63, 64, 65, 82])] = 3
        ww[np.isin(vals, [68, 83])] = 4
        ww[np.isin(vals, [69, 84])] = 5
        ww[np.isin(vals, [84])] = 6
        ww[np.isin(vals, [70, 71, 85])] = 7
        ww[np.isin(vals, [72, 73, 86])] = 8
        ww[np.isin(vals, [74, 75])] = 9
        ww[np.isin(vals, [91, 92, 93, 94, 95])] = 10
        ww[np.isin(vals, [96, 97, 98, 99])] = 11
        ww[ww == 0] = np.nan
        vals = ww

    return lons, lats, vals, title, pmsl_data, extra_overlay

# --- MAP RENDERER ---
def create_map(config_list, lons, lats, data, map_title_time, legend_title, model_type, region, overlays, design):
    world, bundeslaender = load_borders()
    
    levels = [c['value'] for c in sorted(config_list, key=lambda x: x['value'])]
    colors = [c['color'] for c in sorted(config_list, key=lambda x: x['value'])]
    min_v, max_v = min(levels), max(levels)
    if max_v == min_v: max_v += 1 
    
    is_categorical = (legend_title == "Signifikantes Wetter")
    is_discrete = design.get('discrete_colors', False)
    
    # NEU: SATELLITEN-FIX - Mache Daten <0.1 komplett transparent und verstecke die Achsen-Hintergrundfarbe
    is_satellite_active = overlays.get('satellite') and region == "Deutschland" and ("Niederschlag" in legend_title or "Regen" in legend_title)
    if is_satellite_active:
        data = np.where(data < 0.1, np.nan, data)
    
    if is_categorical:
        cmap = mcolors.ListedColormap(colors)
        bounds = [v - 0.5 for v in levels] + [levels[-1] + 0.5]
        norm = mcolors.BoundaryNorm(bounds, cmap.N)
    elif is_discrete:
        cmap = mcolors.ListedColormap(colors)
        bounds = levels + [max_v + 1.0]
        norm = mcolors.BoundaryNorm(bounds, cmap.N)
    else:
        cmap = mcolors.LinearSegmentedColormap.from_list("custom", list(zip([(v - min_v) / (max_v - min_v) for v in levels], colors)))
        if is_satellite_active:
            cmap.set_bad('none') # Zwingt Matplotlib dazu, NaNs wirklich transparent zu lassen
        contour_levels = np.linspace(min_v, max_v, 150)

    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(design['bg_color'])
    
    # FIX: Wenn Satellit an ist, darf die Achse keinen Hintergrund haben, sonst blockiert sie das Sat-Bild!
    if is_satellite_active:
        ax.set_facecolor('none')
    else:
        ax.set_facecolor(design['bg_color'])
    
    if region in REGIONS: 
        ax.set_xlim(REGIONS[region][0], REGIONS[region][1])
        ax.set_ylim(REGIONS[region][2], REGIONS[region][3])
        
    if is_satellite_active:
        sat_img = get_satellite_bg(REGIONS[region][0], REGIONS[region][1], REGIONS[region][2], REGIONS[region][3])
        if sat_img is not None:
            ax.imshow(sat_img, extent=[REGIONS[region][0], REGIONS[region][1], REGIONS[region][2], REGIONS[region][3]], aspect='auto', zorder=0)
        
    if is_categorical or is_discrete:
        karte = ax.contourf(lons, lats, data, levels=bounds, cmap=cmap, norm=norm, extend='max' if not is_categorical else 'neither', alpha=0.9 if is_satellite_active else 0.95, zorder=1)
        cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
        if is_categorical:
            cbar.ax.set_xticklabels([SIG_WETTER_LABELS.get(int(v), str(v)) for v in levels], rotation=45, ha='right', fontsize=8)
    else:
        karte = ax.contourf(lons, lats, data, levels=contour_levels, cmap=cmap, extend='max' if is_satellite_active else 'both', alpha=0.9 if is_satellite_active else 0.95, zorder=1)
        tick_step = int(design.get('cbar_step', 1))
        visible_ticks = levels[::tick_step]
        cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=visible_ticks, aspect=40)
    
    cbar.set_label(legend_title, color=design['text_color'], size=int(design.get('cbar_size', 11)), fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'))
    cbar.ax.xaxis.set_tick_params(color=design['text_color'], labelcolor=design['text_color'], labelsize=9)
    for label in cbar.ax.get_xticklabels(): label.set_fontfamily(design.get('font_family', 'sans-serif'))
    
    line_w = float(design.get('line_width', 0.8))
    world.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=line_w, alpha=float(design.get('border_alpha', 0.4)), zorder=2)
    bundeslaender.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=line_w + 0.4, alpha=float(design.get('border_alpha', 0.4)), zorder=2)

    if overlays.get('extra_data') is not None and "CIN" in legend_title:
        ax.contourf(lons, lats, overlays['extra_data'], levels=[50, 100000], hatches=['//'], colors='none', edgecolors='#00BFFF', alpha=0.6, zorder=3)

    if overlays.get('pmsl_data') is not None:
        iso = ax.contour(lons, lats, overlays['pmsl_data'], levels=np.arange(900, 1100, 5), colors=design['text_color'], linewidths=1.0, alpha=0.6, zorder=3)
        ax.clabel(iso, inline=True, fontsize=9, fmt='%d', colors=design['text_color'])

    if overlays.get('topo'):
        t_lons, t_lats, t_data = get_topography(model_type)
        if t_data is not None:
            topo = ax.contour(t_lons, t_lats, t_data, levels=np.arange(250, 4000, 250), colors=design['text_color'], alpha=0.25, linewidths=0.6, zorder=1)

    if overlays.get('cities') and region == "Deutschland":
        c_lons = [coords[0] for coords in GERMAN_CITIES.values()]
        c_lats = [coords[1] for coords in GERMAN_CITIES.values()]
        c_names = list(GERMAN_CITIES.keys())
        ax.plot(c_lons, c_lats, 'o', color=design['text_color'], markersize=3, alpha=0.8, zorder=4)
        for lon_c, lat_c, name in zip(c_lons, c_lats, c_names):
            ax.text(lon_c + 0.08, lat_c + 0.08, name, color=design['text_color'], fontsize=8, fontweight='bold',
                    fontfamily=design.get('font_family', 'sans-serif'),
                    path_effects=[path_effects.withStroke(linewidth=1.5, foreground=design['bg_color'])], zorder=4)

    if overlays.get('numbers') and not is_categorical:
        xmin, xmax, ymin, ymax = ax.get_xlim()[0], ax.get_xlim()[1], ax.get_ylim()[0], ax.get_ylim()[1]
        try: dy_km = abs(lats[0, 0] - lats[-1, 0]) / max(1, lats.shape[0]) * 111.0
        except: dy_km = 2.2
        if dy_km < 0.1: dy_km = 2.2
        mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
        
        if legend_title == "Regenrate in mm/h" or legend_title == "Niederschlag in mm":
            size_px = max(3, int(40.0 / dy_km))
            local_max = ndimage.maximum_filter(data, size=size_px) == data
            valid_mask = mask & local_max & (data >= 0.1)
        else:
            target_km = 60.0 
            step = max(1, int(target_km / dy_km)) 
            grid_mask = np.zeros_like(mask, dtype=bool)
            grid_mask[::step, ::step] = True
            valid_mask = mask & grid_mask
        
        for lon_val, lat_val, val in zip(lons[valid_mask], lats[valid_mask], data[valid_mask]):
            if ("Niederschlag" in legend_title or "Regen" in legend_title) and val < 0.1: continue
            if "CAPE" in legend_title and val < 50: continue
            txt = f"{val:.1f}" if ("Niederschlag" in legend_title or "Regen" in legend_title) else f"{val:.0f}"
            ax.text(lon_val, lat_val, txt, fontsize=5, fontfamily=design.get('font_family', 'sans-serif'), fontweight='bold', 
                    color=design.get('number_color', '#000000'), ha='center', va='center', 
                    path_effects=[path_effects.withStroke(linewidth=1.5, foreground=design.get('number_outline', '#FFFFFF'))], zorder=5)

    if design.get('watermark'):
        ax.text(0.5, 0.02, design['watermark'], transform=ax.transAxes, color=design['text_color'], 
                fontsize=10, fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'),
                ha='center', va='bottom', alpha=0.5, zorder=10)

    ax.axis('off')
    
    bg_rgba = mcolors.to_rgba(design.get('title_bg', '#0E1117'), alpha=0.4)
    ec_rgba = mcolors.to_rgba(design['border_color'], alpha=0.6)
    bbox_props = dict(boxstyle="round,pad=0.5", fc=bg_rgba, ec=ec_rgba, lw=1.2)
    
    ax.text(0.015, 0.985, f"{model_type} | {map_title_time}", transform=ax.transAxes, 
            color=design['text_color'], fontsize=int(design.get('title_size', 11)), fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'), 
            ha='left', va='top', bbox=bbox_props, zorder=10)
    
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight', pad_inches=0.1, facecolor=design['bg_color'])
    plt.close(fig)
    return buf.getvalue()

# --- BENUTZEROBERFLÄCHE (SEITENLEISTE MIT TABS) ---
st.sidebar.header("⚙️ Terminal-Steuerung")
tab_main, tab_overlays, tab_design = st.sidebar.tabs(["⚙️ Basis", "🔣 Overlays", "🎨 Design"])

with tab_main:
    with st.popover(f"🌍 Modell: {st.session_state.model_choice}"):
        idx_m = ["ICON-D2 (2.2km)", "ICON-D2-RUC (+27h)", "ICON-EU (+120h)", "GFS (+384h)"].index(st.session_state.model_choice)
        st.radio("Modell", ["ICON-D2 (2.2km)", "ICON-D2-RUC (+27h)", "ICON-EU (+120h)", "GFS (+384h)"], index=idx_m, key="m_radio", label_visibility="collapsed")
    if st.session_state.m_radio != st.session_state.model_choice:
        st.session_state.model_choice = st.session_state.m_radio
        st.rerun()

    model_choice = st.session_state.model_choice

    available_runs = get_available_runs(model_choice)
    run_label = st.selectbox("Modelllauf:", list(available_runs.keys()))
    run_time = available_runs[run_label]
    
    param_list = ["Temperatur (2m)", "Windböen 10m", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "500 hPa Geopot. Height", "850 hPa Temp.", "MLCAPE", "CIN", "CAPE & CIN (Deckel)", "Signifikantes Wetter"]
    with st.popover(f"🌡️ Parameter: {st.session_state.param_choice}"):
        idx_p = param_list.index(st.session_state.param_choice) if st.session_state.param_choice in param_list else 0
        st.radio("Parameter", param_list, index=idx_p, key="p_radio", label_visibility="collapsed")
    if st.session_state.p_radio != st.session_state.param_choice:
        st.session_state.param_choice = st.session_state.p_radio
        st.rerun()
        
    param_choice = st.session_state.param_choice
    
    if param_choice not in st.session_state.config: 
        st.session_state.config[param_choice] = load_param_config(param_choice)
        
    region_options = list(REGIONS.keys())
    if "D2" in model_choice: region_options.remove("Europa") 
    if st.session_state.region_choice not in region_options: st.session_state.region_choice = "Deutschland"
    
    with st.popover(f"📍 Region: {st.session_state.region_choice}"):
        idx_r = region_options.index(st.session_state.region_choice)
        st.radio("Region", region_options, index=idx_r, key="r_radio", label_visibility="collapsed")
    if st.session_state.r_radio != st.session_state.region_choice:
        st.session_state.region_choice = st.session_state.r_radio
        st.rerun()
        
    region_choice = st.session_state.region_choice

with tab_overlays:
    st.info("Kombiniere mehrere Karten-Layer:")
    show_topo = st.toggle("⛰️ Höhenlinien (250m Raster)", value=False)
    show_cities = st.toggle("🏙️ Wichtige Städte anzeigen", value=True) if region_choice == "Deutschland" else False
    show_pmsl = st.toggle("💨 Isobaren (Luftdruck)", value=True) if param_choice == "850 hPa Temp." else False
    
    show_numbers = False
    if param_choice in ["Temperatur (2m)", "Windböen 10m", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)"]:
        show_numbers = st.toggle("🔢 Zahlenwerte auf Karte", value=False)
        
    show_satellite = False
    if region_choice == "Deutschland" and param_choice in ["Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)"]:
        show_satellite = st.toggle("🛰️ Satellitenbild-Hintergrund", value=False)

with tab_design:
    st.subheader("🖥️ Basis-Themes")
    theme_choice = st.selectbox("Farbschema wählen:", ["Benutzerdefiniert / Gespeichert", "OLED Dark", "Light / Papier", "Satellite / Retro"])
    if theme_choice != st.session_state.get('last_theme', 'Benutzerdefiniert / Gespeichert'):
        if theme_choice == "OLED Dark": st.session_state.design.update({"bg_color": "#000000", "title_bg": "#000000", "text_color": "#FFFFFF", "border_color": "#FFFFFF", "border_alpha": 0.2})
        elif theme_choice == "Light / Papier": st.session_state.design.update({"bg_color": "#FFFFFF", "title_bg": "#FFFFFF", "text_color": "#000000", "border_color": "#000000", "border_alpha": 0.3, "number_color": "#000000", "number_outline": "#FFFFFF"})
        elif theme_choice == "Satellite / Retro": st.session_state.design.update({"bg_color": "#1A2421", "title_bg": "#1A2421", "text_color": "#00FFCC", "border_color": "#00FFCC", "border_alpha": 0.5})
        elif theme_choice == "Benutzerdefiniert / Gespeichert": st.session_state.design = load_design_config()
        st.session_state['last_theme'] = theme_choice
        st.rerun()

    st.divider()
    st.subheader("🎨 Karte & Text")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.session_state.design['bg_color'] = st.color_picker("Hintergrund", value=st.session_state.design['bg_color'])
        st.session_state.design['title_bg'] = st.color_picker("Header-Box", value=st.session_state.design.get('title_bg', '#0E1117'))
        st.session_state.design['text_color'] = st.color_picker("Text & Linien", value=st.session_state.design['text_color'])
        st.session_state.design['border_color'] = st.color_picker("Grenzen-Farbe", value=st.session_state.design['border_color'])
    with col_d2:
        st.session_state.design['border_alpha'] = st.slider("Grenzen-Deckkraft", 0.0, 1.0, float(st.session_state.design.get('border_alpha', 0.4)), 0.1)
        st.session_state.design['line_width'] = st.slider("Linien-Dicke", 0.1, 3.0, float(st.session_state.design.get('line_width', 0.8)), 0.1)
        st.session_state.design['title_size'] = st.number_input("Header Schriftgröße", 5, 20, int(st.session_state.design.get('title_size', 11)))
        st.session_state.design['font_family'] = st.selectbox("Schriftart", ["sans-serif", "serif", "monospace"], index=["sans-serif", "serif", "monospace"].index(st.session_state.design.get('font_family', 'sans-serif')))
    
    st.session_state.design['watermark'] = st.text_input("©️ Wasserzeichen (Text)", value=st.session_state.design.get('watermark', ''))
    if st.button("💾 Design & Wasserzeichen Speichern"): save_design_config(st.session_state.design)

    st.divider()
    st.subheader("🔢 Zahlen-Design")
    c_z1, c_z2 = st.columns(2)
    with c_z1: st.session_state.design['number_color'] = st.color_picker("Zahlfarbe", value=st.session_state.design.get('number_color', '#000000'))
    with c_z2: st.session_state.design['number_outline'] = st.color_picker("Umrandung", value=st.session_state.design.get('number_outline', '#FFFFFF'))

    st.divider()
    st.subheader(f"📊 Skala: {param_choice}")
    c_sk1, c_sk2 = st.columns(2)
    with c_sk1: st.session_state.design['discrete_colors'] = st.toggle("Harte Farbkanten (Diskret)", value=st.session_state.design.get('discrete_colors', False))
    with c_sk2: st.session_state.design['cbar_step'] = st.number_input("Zeige jeden X-ten Wert:", 1, 20, int(st.session_state.design.get('cbar_step', 1)))
    st.session_state.design['cbar_size'] = st.number_input("Skala Schriftgröße", 5, 20, int(st.session_state.design.get('cbar_size', 11)))
    
    for item in st.session_state.config[param_choice]:
        if "_id" not in item: item["_id"] = str(uuid.uuid4())
    
    new_config = []
    for i, item in enumerate(st.session_state.config[param_choice]):
        item_id = item["_id"]
        c1, c2, c3 = st.columns([2, 2, 1])
        if param_choice == "Signifikantes Wetter":
            with c1: val = st.selectbox("W", options=list(SIG_WETTER_LABELS.keys()), index=list(SIG_WETTER_LABELS.keys()).index(int(item['value'])) if int(item['value']) in SIG_WETTER_LABELS else 0, format_func=lambda x: SIG_WETTER_LABELS.get(x, str(x)), key=f"v_{item_id}", label_visibility="collapsed")
        else:
            with c1: val = st.number_input("W", value=float(item['value']), step=1.0, key=f"v_{item_id}", label_visibility="collapsed")
        with c2: col = st.color_picker("F", value=item['color'], key=f"c_{item_id}", label_visibility="collapsed")
        with c3:
            if st.button("🗑️", key=f"d_{item_id}"): st.session_state.config[param_choice].pop(i); st.rerun()
        new_config.append({"value": val, "color": col, "_id": item_id})
    
    st.session_state.config[param_choice] = new_config
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("➕ Neu"): st.session_state.config[param_choice].append({"value": max([c['value'] for c in new_config]) + 1 if new_config else 0.0, "color": "#ffffff", "_id": str(uuid.uuid4())}); st.rerun()
    with col_btn2:
        if st.button("💾 Skala Speichern"): save_param_config(param_choice, st.session_state.config[param_choice])
        
    st.divider()
    st.subheader("📥 Gespeicherte Skala laden")
    cloud_files = get_saved_config_files()
    if cloud_files:
        selected_file = st.selectbox("Cloud-Dateien:", ["-- Wählen --"] + cloud_files, label_visibility="collapsed")
        if selected_file != "-- Wählen --":
            if st.button("Laden & Anwenden"):
                try:
                    g = get_github_client()
                    repo = g.get_repo(st.secrets["GITHUB_REPO"])
                    st.session_state.config[param_choice] = json.loads(repo.get_contents(f"configs/{selected_file}").decoded_content.decode())
                    st.success(f"{selected_file} geladen!"); st.rerun()
                except Exception as e: st.error(f"Fehler: {e}")

# --- HAUPTBEREICH TABS ---
tab_map, tab_ens = st.tabs(["🗺️ Karten-Terminal", "📈 Ensemble (Spaghetti)"])

with tab_map:
    max_h = 384 if "GFS" in model_choice else (120 if "EU" in model_choice else (27 if "RUC" in model_choice else 48))
    step_h = 3 if "GFS" in model_choice else 1
    tz_berlin = ZoneInfo("Europe/Berlin")
    start_time_local = run_time.astimezone(tz_berlin)

    st.markdown(f"""
        <div class="glass-banner" style="color: {st.session_state.design['text_color']}; border-color: {st.session_state.design['border_color']};">
            🌤️ {model_choice} | 🌡️ {param_choice}
        </div>
    """, unsafe_allow_html=True)

    selected_datetime = st.slider("Zeitpunkt", min_value=start_time_local, max_value=start_time_local + timedelta(hours=max_h), 
                                  value=start_time_local + timedelta(hours=min(st.session_state.f_hour, max_h)), step=timedelta(hours=step_h), format="ddd, DD.MM. - HH:mm")

    chosen_f_hour = int((selected_datetime - start_time_local).total_seconds() / 3600)
    st.session_state.f_hour = chosen_f_hour

    config_hash = hash(str(st.session_state.config[param_choice]) + str(st.session_state.design) + str(show_cities) + str(show_topo) + str(show_numbers) + str(show_satellite))
    cache_key = f"{model_choice}_{run_label}_{param_choice}_{region_choice}_{chosen_f_hour}_{show_pmsl}_{config_hash}"

    if cache_key in st.session_state.map_cache:
        st.image(st.session_state.map_cache[cache_key]["image"], use_container_width=True)
        if st.session_state.map_cache[cache_key].get("extremes"):
            st.info(f"**Extremwerte (Deutschland):** {st.session_state.map_cache[cache_key]['extremes']}")
    else:
        if st.button(f"🗺️ Karte für +{chosen_f_hour}h berechnen & anzeigen", type="primary"):
            with st.spinner("Lade GRIB-Daten und rendere Karte..."):
                overlays_dict = {"pmsl": show_pmsl, "numbers": show_numbers, "cities": show_cities, "topo": show_topo, "satellite": show_satellite}
                lons, lats, data, title, pmsl, extra_overlay = load_parameter_data(run_time, chosen_f_hour, param_choice, model_choice, overlays_dict)
                
                if lons is not None:
                    # Extremwerte für Deutschland berechnen (Nur wenn Region DE gewählt)
                    extremes_txt = None
                    if region_choice == "Deutschland":
                        xmin, xmax, ymin, ymax = REGIONS["Deutschland"]
                        mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
                        if np.any(mask):
                            extremes_txt = f"Min: {np.nanmin(data[mask]):.1f} | Max: {np.nanmax(data[mask]):.1f}"

                    overlays_dict['pmsl_data'], overlays_dict['extra_data'] = pmsl, extra_overlay
                    t_str = selected_datetime.strftime('%d.%m. %H:00')
                    img_bytes = create_map(st.session_state.config[param_choice], lons, lats, data, f"+{chosen_f_hour}h | {t_str} Uhr", title, model_choice, region_choice, overlays_dict, st.session_state.design)
                    
                    st.session_state.map_cache[cache_key] = {"image": img_bytes, "extremes": extremes_txt}
                    st.rerun() 
                else:
                    st.error(f"Ein Datensatz für diesen Parameter (+{chosen_f_hour}h) ist auf den Servern für diesen Modelllauf noch nicht verfügbar[span_1](start_span)[span_1](end_span).")

with tab_ens:
    st.markdown("### 📈 Profi-Ensemble Prognose")
    col_e1, col_e2, col_e3 = st.columns(3)
    
    with col_e1: ens_city = st.selectbox("Ort:", list(GERMAN_CITIES.keys()))
    with col_e2: ens_model = st.selectbox("Modell-Ensemble:", ["ICON-EPS (DWD)", "GFS-Seamless (NOAA)", "ECMWF-EPS"])
    with col_e3: ens_param = st.selectbox("Wetter-Parameter:", ["Temperatur (2m)", "Niederschlag (mm/h)", "Windböen (km/h)", "CAPE (J/kg)"])
    
    om_model_map = {"ICON-EPS (DWD)": "icon_ensemble", "GFS-Seamless (NOAA)": "gfs_seamless", "ECMWF-EPS": "ecmwf_ensemble"}
    om_param_map = {"Temperatur (2m)": "temperature_2m", "Niederschlag (mm/h)": "precipitation", "Windböen (km/h)": "wind_gusts_10m", "CAPE (J/kg)": "cape"}
    
    if st.button("🚀 Ensemble-Diagramm berechnen", type="primary"):
        with st.spinner(f"Lade alle Modell-Mitglieder für {ens_city}..."):
            lon_c, lat_c = GERMAN_CITIES[ens_city]
            ens_data = fetch_ensemble_data(lat_c, lon_c, om_param_map[ens_param], om_model_map[ens_model])
            
            if ens_data and 'hourly' in ens_data:
                hourly = ens_data['hourly']
                times = pd.to_datetime(hourly['time'])
                member_keys = [k for k in hourly.keys() if k.startswith(om_param_map[ens_param])]
                
                fig, ax = plt.subplots(figsize=(12, 5))
                fig.patch.set_facecolor(st.session_state.design['bg_color'])
                ax.set_facecolor(st.session_state.design['bg_color'])
                
                all_series = []
                for mk in member_keys:
                    vals = np.array(hourly[mk])
                    if ens_param == "Windböen (km/h)" and "icon" not in ens_model.lower(): vals = vals * 3.6
                    all_series.append(vals)
                    ax.plot(times, vals, color=st.session_state.design['text_color'], alpha=0.15, linewidth=1)
                
                mean_vals = np.nanmean(all_series, axis=0)
                ax.plot(times, mean_vals, color='#e31a1c' if "Temp" in ens_param else '#1f78b4', linewidth=2.5, label="Ensemble-Mittel")
                
                ax.set_title(f"{ens_model} | {ens_param} | {ens_city}", color=st.session_state.design['text_color'], fontweight='bold', pad=15)
                ax.tick_params(colors=st.session_state.design['text_color'])
                for spine in ax.spines.values(): spine.set_color(st.session_state.design['border_color'])
                
                ax.legend(facecolor=st.session_state.design['bg_color'], labelcolor=st.session_state.design['text_color'], edgecolor=st.session_state.design['border_color'])
                ax.grid(color=st.session_state.design['text_color'], alpha=0.1, linestyle='--')
                st.pyplot(fig)
            else:
                st.error("Fehler beim Abruf der Ensemble-Daten von der Open-Meteo API.")
