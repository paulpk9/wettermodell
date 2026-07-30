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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import xarray as xr
import scipy.ndimage as ndimage
import io

# --- SEITEN-LAYOUT & CSS ---
st.set_page_config(page_title="Profi-Wetterterminal", page_icon="🌤️", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;800&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
        img { border-radius: 16px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4); transition: all 0.3s ease; }
        
        /* Modernes Glassmorphism Header-Design */
        .glass-banner {
            background: linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.02) 100%);
            backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 16px; padding: 20px 30px;
            text-align: center; font-size: 1.3em; font-weight: 600; margin-bottom: 25px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3); letter-spacing: 0.5px;
        }
        
        /* Stylische Slider und saubere Inputs */
        .stSlider > div > div > div { background: linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%); }
        [data-testid="stColorPicker"] input { display: none !important; }
        .stPopover { border-radius: 12px !important; }
    </style>
""", unsafe_allow_html=True)

st.title("🗺️ Statische Modellkarte (Profi-Terminal)")

# --- GITHUB CLIENT & DESIGN LOGIK ---
def get_github_client(): return Github(auth=Auth.Token(st.secrets["GITHUB_TOKEN"])) if "GITHUB_TOKEN" in st.secrets else None

DEFAULT_DESIGN = {
    "bg_color": "#0E1117", "title_bg": "#0E1117", "text_color": "#FFFFFF", 
    "border_color": "#FFFFFF", "border_alpha": 0.4, "font_family": "sans-serif",
    "cbar_step": 1, "number_color": "#000000", "number_outline": "#FFFFFF",
    "title_size": 11, "cbar_size": 11, "line_width": 0.8, "watermark": "", 
    "discrete_colors": False, "scientific_cmap": False
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
            st.success("Design erfolgreich in der Cloud gespeichert!")
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
    1: "Nebel", 2: "Regen (leicht)", 3: "Regen (mäßig)", 4: "Regen (stark)",
    5: "Schneeregen (leicht)", 6: "Schneeregen (mäßig)", 7: "Schneeregen (stark)",
    8: "Schnee (leicht)", 9: "Schnee (mäßig)", 10: "Schnee (stark)",
    11: "Gewitter (leicht)", 12: "Gewitter (stark)"
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
    "Scherung 0-1 km": [{"value": 0.0, "color": "#ffffff"}, {"value": 15.0, "color": "#ffffcc"}, {"value": 30.0, "color": "#fd8d3c"}, {"value": 45.0, "color": "#e31a1c"}, {"value": 60.0, "color": "#800026"}],
    "Scherung 0-6 km": [{"value": 0.0, "color": "#ffffff"}, {"value": 20.0, "color": "#ffffcc"}, {"value": 40.0, "color": "#fd8d3c"}, {"value": 60.0, "color": "#e31a1c"}, {"value": 80.0, "color": "#800026"}],
    "Simulierte Hagelgröße": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#a6cee3"}, {"value": 2.0, "color": "#1f78b4"}, {"value": 4.0, "color": "#33a02c"}, {"value": 6.0, "color": "#e31a1c"}],
    "Radarreflektivität (dBZ)": [{"value": 0.0, "color": "#ffffff"}, {"value": 15.0, "color": "#a6cee3"}, {"value": 30.0, "color": "#1f78b4"}, {"value": 45.0, "color": "#fd8d3c"}, {"value": 55.0, "color": "#e31a1c"}, {"value": 65.0, "color": "#800026"}],
    "Blitzrate (LPI)": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#ffffcc"}, {"value": 5.0, "color": "#fd8d3c"}, {"value": 10.0, "color": "#e31a1c"}, {"value": 20.0, "color": "#800026"}],
    "Chaser Target-Index": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#ffffcc"}, {"value": 3.0, "color": "#fd8d3c"}, {"value": 6.0, "color": "#e31a1c"}, {"value": 10.0, "color": "#800026"}],
    "SCP-Index": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#a6cee3"}, {"value": 5.0, "color": "#1f78b4"}, {"value": 10.0, "color": "#fd8d3c"}, {"value": 20.0, "color": "#e31a1c"}],
    "PWAT (mm)": [{"value": 10.0, "color": "#ffffff"}, {"value": 20.0, "color": "#a6cee3"}, {"value": 30.0, "color": "#1f78b4"}, {"value": 40.0, "color": "#33a02c"}, {"value": 50.0, "color": "#e31a1c"}],
    "Gesamtbewölkung (%)": [{"value": 0.0, "color": "#f0f0f0"}, {"value": 25.0, "color": "#c6dbef"}, {"value": 50.0, "color": "#9ecae1"}, {"value": 75.0, "color": "#6baed6"}, {"value": 100.0, "color": "#3182bd"}],
    "Signifikantes Wetter": [
        {"value": 1.0, "color": "#d9d9d9"}, {"value": 2.0, "color": "#a1d99b"}, {"value": 3.0, "color": "#31a354"},
        {"value": 4.0, "color": "#006d2c"}, {"value": 5.0, "color": "#fcc5c0"}, {"value": 6.0, "color": "#f768a1"},
        {"value": 7.0, "color": "#ae017e"}, {"value": 8.0, "color": "#c6dbef"}, {"value": 9.0, "color": "#6baed6"},
        {"value": 10.0, "color": "#2171b5"}, {"value": 11.0, "color": "#fd8d3c"}, {"value": 12.0, "color": "#e31a1c"}
    ]
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
    return DEFAULT_CONFIGS.get(param_name, DEFAULT_CONFIGS.get("Temperatur (2m)"))

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
            st.success(f"Farbskala erfolgreich gespeichert!")
        except Exception as e: st.error(f"Fehler beim Speichern: {e}")

@st.cache_data
def load_borders():
    w_r = requests.get("https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson").text
    bl_r = requests.get("https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json").text
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f1, tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f2:
        f1.write(w_r); f1_name = f1.name; f2.write(bl_r); f2_name = f2.name
    return gpd.read_file(f1_name), gpd.read_file(f2_name)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_ensemble_data(lat, lon, param, model):
    if "gfs" in model.lower(): days = 16
    elif "ecmwf" in model.lower(): days = 15
    else: days = 7
    url = f"https://ensemble-api.open-meteo.com/v1/ensemble?latitude={lat}&longitude={lon}&hourly={param}&models={model}&forecast_days={days}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200: return resp.json()
    except: pass
    return None

def get_available_runs(model_name):
    if "Live-Radar" in model_name: return {"Live": datetime.now(timezone.utc)}
    now = datetime.now(timezone.utc)
    if "RUC" in model_name: step, delay = 1, 2.0
    elif "EPS" in model_name: step, delay = 3, 3.5
    elif "GFS" in model_name: step, delay = 6, 5.5
    elif "EU" in model_name: step, delay = 6, 3.5
    else: step, delay = 3, 2.5
    eff_now = now - timedelta(hours=delay)
    latest = eff_now.replace(hour=(eff_now.hour // step) * step, minute=0, second=0, microsecond=0)
    return {f"Lauf: { (latest - timedelta(hours=i*step)).strftime('%d.%m.%Y | %H:02d') }Z": (latest - timedelta(hours=i*step)) for i in range(6)}

@st.cache_data(ttl=3600, show_spinner=False)
def download_and_extract(url, is_bz2=False, param_name=None, eps_member=None):
    if not url: return None, None, None
    try:
        # Stream=True verhindert Abbruch bei DWD-Sperren von Head-Requests
        resp = requests.get(url, headers={"User-Agent": "Mozilla"}, stream=True, timeout=10)
        if resp.status_code != 200: return None, None, None
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f: 
            f.write(bz2.decompress(resp.content) if is_bz2 else resp.content)
            t_path = f.name
            
        ds = xr.open_dataset(t_path, engine='cfgrib')
        if 'number' in ds.dims:
            if eps_member and "Member" in eps_member:
                member_idx = int(eps_member.replace("Member ", "")) - 1
                ds = ds.isel(number=member_idx)
            elif param_name == "Signifikantes Wetter": 
                ds = ds.isel(number=0) 
            else: 
                ds = ds.mean(dim='number') 

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

def get_raw_grib(run_time, forecast_hour, model, param_name, eps_choice=None):
    if "Live-Radar" in model: return None, None, None
    run_str, date_str, hour_str = f"{run_time.hour:02d}", run_time.strftime("%Y%m%d"), f"{forecast_hour:03d}"
    if param_name in ["CAPE & CIN (Deckel)", "Scherung 0-1 km", "Scherung 0-6 km", "SCP-Index", "Chaser Target-Index"]: return None, None, None

    if "GFS" in model:
        vm = {
            "Temperatur (2m)": "var_TMP=on&lev_2_m_above_ground=on", "Akk. Niederschlag (mm)": "var_APCP=on&lev_surface=on", 
            "Windböen 10m": "var_GUST=on&lev_surface=on", "Niederschlagsrate (mm/h)": "var_PRATE=on&lev_surface=on",
            "MLCAPE": "var_CAPE=on&lev_surface=on", "CIN": "var_CIN=on&lev_surface=on", "PMSL": "var_PRMSL=on&lev_mean_sea_level=on",
            "Gesamtbewölkung (%)": "var_TCDC=on&lev_entire_atmosphere=on", "PWAT (mm)": "var_PWAT=on&lev_entire_atmosphere=on"
        }
        fs = vm.get(param_name, "")
        if param_name == "850 hPa Temp.": fs = "var_TMP=on&lev_850_mb=on&var_PRMSL=on&lev_mean_sea_level=on"
        url = f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=%2Fgfs.{date_str}%2F{run_str}%2Fatmos&file=gfs.t{run_str}z.pgrb2.0p25.f{hour_str}&{fs}" if fs else None
        return download_and_extract(url, param_name=param_name, eps_member=eps_choice)
    
    dm = {
        "Temperatur (2m)": ("t_2m", "t_2m", None), "Windböen 10m": ("vmax_10m", "vmax_10m", None), 
        "Akk. Niederschlag (mm)": ("tot_prec", "tot_prec", None), "Niederschlagsrate (mm/h)": ("tot_prec", "tot_prec", None), 
        "500 hPa Geopot. Height": ("fi", "fi", "500"), "850 hPa Temp.": ("t", "t", "850"), 
        "MLCAPE": ("cape_ml", "cape_ml", None), "CIN": ("cin_ml", "cin_ml", None),
        "PMSL": ("pmsl", "pmsl", None), "Signifikantes Wetter": ("ww", "ww", None),
        "Gesamtbewölkung (%)": ("clct", "clct", None), "PWAT (mm)": ("tqv", "tqv", None),
        "Radarreflektivität (dBZ)": ("dbz_cmax", "dbz_cmax", None), "Blitzrate (LPI)": ("lpi_max", "lpi_max", None),
        "U-Wind 10m": ("u_10m", "u_10m", None), "V-Wind 10m": ("v_10m", "v_10m", None),
        "U-Wind 850hPa": ("u", "u", "850"), "V-Wind 850hPa": ("v", "v", "850"),
        "U-Wind 500hPa": ("u", "u", "500"), "V-Wind 500hPa": ("v", "v", "500"),
        "Simulierte Hagelgröße": ("mxhail", "mxhail", None)
    }
        
    if param_name not in dm: return None, None, None
    fld, var, lvl = dm[param_name]
    
    urls_to_try = []
    if "D2" in model:
        m_str = "icon-d2-eps" if "EPS" in model else ("icon-d2-ruc" if "RUC" in model else "icon-d2")
        base = f"https://opendata.dwd.de/weather/nwp/{m_str}/grib/{run_str}/{fld}/"
        if lvl:
            prefix = f"{m_str}_germany_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_"
            urls_to_try.extend([base + prefix + f"{var.upper()}.grib2.bz2", base + prefix + f"{var}.grib2.bz2"])
        else:
            prefix = f"{m_str}_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_"
            vars_try = [var, f"2d_{var}", var.replace("2d_", "")]
            if fld == "mxhail" or var == "mxhail":
                vars_try.extend(["mxhail", "2d_mxhail", "dzhail_mx", "2d_dzhail_mx"])
            for v in vars_try:
                urls_to_try.append(base + prefix + f"{v}.grib2.bz2")
    elif "EU" in model:
        base = f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{fld}/"
        if lvl:
            prefix = f"icon-eu_europe_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_"
            urls_to_try.append(base + prefix + f"{var.upper()}.grib2.bz2")
        else:
            prefix = f"icon-eu_europe_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_"
            urls_to_try.extend([base + prefix + f"{var.upper()}.grib2.bz2", base + prefix + f"{var.replace('2d_', '').upper()}.grib2.bz2"])
            
    for u in urls_to_try:
        res = download_and_extract(u, is_bz2=True, param_name=param_name, eps_member=eps_choice)
        if res[0] is not None:
            return res
        
    return None, None, None

def load_parameter_data(run_time, forecast_hour, param_name, model_type, overlays, eps_choice=None):
    if "Live-Radar" in model_type:
        return np.zeros((2,2)), np.zeros((2,2)), None, "Live Regenradar (DWD)", None, None

    pmsl_data, extra_overlay = None, None
    
    if param_name == "CAPE & CIN (Deckel)":
        lons, lats, cape_vals = get_raw_grib(run_time, forecast_hour, model_type, "MLCAPE", eps_choice)
        _, _, cin_vals = get_raw_grib(run_time, forecast_hour, model_type, "CIN", eps_choice)
        if cape_vals is None or cin_vals is None: return None, None, None, "", None, None
        if isinstance(cape_vals, tuple): cape_vals, p_raw = cape_vals; pmsl_data = (p_raw / 100.0) if overlays.get('pmsl') else None
        return lons, lats, np.squeeze(cape_vals), "CAPE (J/kg) & CIN-Deckel (Schraffur)", pmsl_data, np.squeeze(cin_vals)

    if param_name in ["Scherung 0-1 km", "Scherung 0-6 km"]:
        res_u10 = get_raw_grib(run_time, forecast_hour, model_type, "U-Wind 10m", eps_choice)
        res_v10 = get_raw_grib(run_time, forecast_hour, model_type, "V-Wind 10m", eps_choice)
        h_param = "U-Wind 850hPa" if "0-1" in param_name else "U-Wind 500hPa"
        v_param = "V-Wind 850hPa" if "0-1" in param_name else "V-Wind 500hPa"
        res_uh = get_raw_grib(run_time, forecast_hour, model_type, h_param, eps_choice)
        res_vh = get_raw_grib(run_time, forecast_hour, model_type, v_param, eps_choice)
        
        if res_u10[2] is None or res_uh[2] is None: return None, None, None, "", None, None
        u10 = res_u10[2][0] if isinstance(res_u10[2], tuple) else res_u10[2]
        v10 = res_v10[2][0] if isinstance(res_v10[2], tuple) else res_v10[2]
        uh = res_uh[2][0] if isinstance(res_uh[2], tuple) else res_uh[2]
        vh = res_vh[2][0] if isinstance(res_vh[2], tuple) else res_vh[2]
        
        shear = np.sqrt((np.squeeze(uh) - np.squeeze(u10))**2 + (np.squeeze(vh) - np.squeeze(v10))**2) * 1.94384
        return res_u10[0], res_u10[1], shear, f"{param_name} (kn)", None, None

    if param_name in ["SCP-Index", "Chaser Target-Index"]:
        res_cape = get_raw_grib(run_time, forecast_hour, model_type, "MLCAPE", eps_choice)
        res_u10 = get_raw_grib(run_time, forecast_hour, model_type, "U-Wind 10m", eps_choice)
        res_v10 = get_raw_grib(run_time, forecast_hour, model_type, "V-Wind 10m", eps_choice)
        res_u500 = get_raw_grib(run_time, forecast_hour, model_type, "U-Wind 500hPa", eps_choice)
        res_v500 = get_raw_grib(run_time, forecast_hour, model_type, "V-Wind 500hPa", eps_choice)
        
        if res_cape[2] is None or res_u10[2] is None or res_u500[2] is None: return None, None, None, "", None, None
        cape = np.squeeze(res_cape[2][0] if isinstance(res_cape[2], tuple) else res_cape[2])
        u10 = np.squeeze(res_u10[2][0] if isinstance(res_u10[2], tuple) else res_u10[2])
        v10 = np.squeeze(res_v10[2][0] if isinstance(res_v10[2], tuple) else res_v10[2])
        u500 = np.squeeze(res_u500[2][0] if isinstance(res_u500[2], tuple) else res_u500[2])
        v500 = np.squeeze(res_v500[2][0] if isinstance(res_v500[2], tuple) else res_v500[2])
        shear_ms = np.sqrt((u500 - u10)**2 + (v500 - v10)**2)
        
        if param_name == "SCP-Index":
            scp = (cape / 1000.0) * (shear_ms / 20.0)
            return res_cape[0], res_cape[1], np.clip(scp, 0, None), "SCP-Index", None, None
        else:
            res_cin = get_raw_grib(run_time, forecast_hour, model_type, "CIN", eps_choice)
            if res_cin[2] is None: return None, None, None, "", None, None
            cin = np.squeeze(res_cin[2][0] if isinstance(res_cin[2], tuple) else res_cin[2])
            cin_abs = np.abs(cin)
            cin_penalty = np.where(cin_abs > 50, 50 / cin_abs, 1.0)
            cti = (cape / 1000.0) * ((shear_ms * 1.94384) / 30.0) * cin_penalty
            return res_cape[0], res_cape[1], np.clip(cti, 0, None), "Chaser Target-Index (CTI)", None, None

    lons, lats, vals = get_raw_grib(run_time, forecast_hour, model_type, param_name, eps_choice)
    if vals is None: return None, None, None, "", None, None
    if isinstance(vals, tuple): vals, p_raw = vals; pmsl_data = (p_raw / 100.0) if overlays.get('pmsl') else None
    vals = np.squeeze(vals)
    
    if param_name == "Signifikantes Wetter" and overlays.get('clouds'):
        res_c = get_raw_grib(run_time, forecast_hour, model_type, "Gesamtbewölkung (%)", eps_choice)
        cloud_vals = res_c[2]
        if cloud_vals is not None:
            extra_overlay = np.squeeze(cloud_vals[0] if isinstance(cloud_vals, tuple) else cloud_vals)
    
    title = ""
    if "Temp" in param_name: vals -= 273.15; title = "Temperatur in °C"
    elif "Windböen" in param_name: vals *= 3.6; title = "Windböen in km/h"
    elif param_name == "Akk. Niederschlag (mm)": title = "Niederschlag in mm"
    elif param_name == "Gesamtbewölkung" in param_name: title = "Gesamtbewölkung in %"
    elif param_name == "PWAT" in param_name: title = "PWAT in mm"
    elif param_name == "Radarreflektivität" in param_name: title = "Reflektivität in dBZ"
    elif param_name == "Blitzrate" in param_name: title = "LPI (Blitzpotenzial)"
    elif param_name == "Niederschlagsrate (mm/h)":
        if forecast_hour > 0:
            res_v1 = get_raw_grib(run_time, forecast_hour - 1, model_type, "Akk. Niederschlag (mm)", eps_choice)
            v1 = res_v1[2]
            if isinstance(v1, tuple): v1 = v1[0]
            vals = np.clip(vals - v1, 0, None) if v1 is not None else vals
        else: vals = np.zeros_like(vals)
        title = "Regenrate in mm/h"
    elif "Geopot" in param_name: vals = vals / 9.80665 / 10.0; title = "Geopotential (gpdm)"
    elif param_name == "Simulierte Hagelgröße": 
        # Hagel roh ist meist Meter, Umrechnung in cm
        vals = vals * 100.0; title = "Hagelgröße (cm)"
    elif param_name == "MLCAPE": title = "CAPE (J/kg)"
    elif param_name == "CIN": title = "CIN (J/kg)"
    elif param_name == "Signifikantes Wetter":
        title = "Signifikantes Wetter"
        ww = np.zeros_like(vals)
        ww[np.isin(vals, [40, 41, 42, 43, 44, 45, 46, 47, 48, 49])] = 1
        ww[np.isin(vals, [50, 51, 58, 61, 80])] = 2
        ww[np.isin(vals, [52, 53, 59, 62, 81])] = 3
        ww[np.isin(vals, [54, 55, 63, 64, 65, 82])] = 4
        ww[np.isin(vals, [68, 83])] = 5
        ww[np.isin(vals, [69])] = 6
        ww[np.isin(vals, [84])] = 7
        ww[np.isin(vals, [70, 71, 85])] = 8
        ww[np.isin(vals, [72, 73, 86])] = 9
        ww[np.isin(vals, [74, 75, 76, 77, 78, 79, 87, 88, 89])] = 10
        ww[np.isin(vals, [91, 92, 93, 94, 95])] = 11
        ww[np.isin(vals, [96, 97, 98, 99])] = 12
        ww[ww == 0] = np.nan
        vals = ww

    return lons, lats, vals, title, pmsl_data, extra_overlay

# --- MAP RENDERER ---
def get_scientific_cmap(param_name):
    # Automatische Zuweisung fehlerfreier, wissenschaftlicher Farbskalen
    if "Temp" in param_name: return "turbo"
    if "Wind" in param_name or "Scherung" in param_name: return "plasma"
    if "Niederschlag" in param_name or "Regen" in param_name or "PWAT" in param_name: return "viridis_r"
    if "CAPE" in param_name or "LPI" in param_name or "SCP" in param_name or "Chaser" in param_name: return "magma_r"
    if "Bewölkung" in param_name: return "Greys_r"
    if "Radar" in param_name: return "nipy_spectral"
    if "Hagel" in param_name: return "inferno_r"
    return "turbo"

def create_map(config_list, lons, lats, data, map_title_time, legend_title, model_type, region, overlays, design):
    world, bundeslaender = load_borders()
    
    levels = [c['value'] for c in sorted(config_list, key=lambda x: x['value'])]
    colors = [c['color'] for c in sorted(config_list, key=lambda x: x['value'])]
    min_v, max_v = min(levels), max(levels)
    if max_v == min_v: max_v += 1 
    
    is_categorical = (legend_title == "Signifikantes Wetter")
    is_discrete = design.get('discrete_colors', False)
    is_live_radar = (model_type == "Live-Radar (DWD)")
    use_sci_cmap = design.get('scientific_cmap', False)
    
    if not is_live_radar:
        if is_categorical:
            cmap = mcolors.ListedColormap(colors)
            cmap.set_bad('none')
            bounds = [v - 0.5 for v in levels] + [levels[-1] + 0.5]
            norm = mcolors.BoundaryNorm(bounds, cmap.N)
        elif use_sci_cmap:
            cmap = plt.get_cmap(get_scientific_cmap(legend_title))
            contour_levels = np.linspace(min_v, max_v, 150)
            norm = None
        elif is_discrete:
            cmap = mcolors.ListedColormap(colors)
            bounds = levels + [max_v + 1.0]
            norm = mcolors.BoundaryNorm(bounds, cmap.N)
        else:
            cmap = mcolors.LinearSegmentedColormap.from_list("custom", list(zip([(v - min_v) / (max_v - min_v) for v in levels], colors)))
            contour_levels = np.linspace(min_v, max_v, 150)
            norm = None

    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(design['bg_color'])
    ax.set_facecolor(design['bg_color'])
    
    # NEU: Karten-Umrandung
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor(design['border_color'])
        spine.set_linewidth(1.5)
        spine.set_visible(True)
    
    if region in REGIONS: 
        ax.set_xlim(REGIONS[region][0], REGIONS[region][1])
        ax.set_ylim(REGIONS[region][2], REGIONS[region][3])

    # Z-ORDER SYSTEM:
    # 0=Radar, 1.5=Wolken, 2=Daten, 3=Isobaren, 4=Grenzen, 5=Städte, 6=Zahlen
    if is_live_radar:
        # Direkter Abruf des DWD Live-Radars (RX) für exakt diese Bounding Box
        import urllib.request
        bbox_str = f"{REGIONS[region][0]},{REGIONS[region][2]},{REGIONS[region][1]},{REGIONS[region][3]}"
        url = f"https://maps.dwd.de/geoserver/dwd/wms?service=WMS&request=GetMap&version=1.1.1&layers=dwd:RX-Produkt&format=image/png&transparent=true&width=1000&height=1000&srs=EPSG:4326&bbox={bbox_str}"
        try:
            req = urllib.request.urlopen(url)
            radar_img = plt.imread(req, format='png')
            ax.imshow(radar_img, extent=[REGIONS[region][0], REGIONS[region][1], REGIONS[region][2], REGIONS[region][3]], aspect='auto', zorder=2)
        except: pass
    else:
        if overlays.get('clouds') and overlays.get('extra_data') is not None and legend_title == "Signifikantes Wetter":
            cloud_cmap = mcolors.LinearSegmentedColormap.from_list("clouds", ["#ffffff00", "#ffffff"])
            ax.contourf(lons, lats, overlays['extra_data'], levels=np.linspace(10, 100, 15), cmap=cloud_cmap, alpha=0.75, zorder=1.5)

        if is_categorical:
            karte = ax.pcolormesh(lons, lats, data, cmap=cmap, norm=norm, alpha=0.95, shading='nearest', zorder=2)
            cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
            cbar.ax.set_xticklabels([SIG_WETTER_LABELS.get(int(v), str(v)) for v in levels], rotation=45, ha='right', fontsize=8)
        elif is_discrete and not use_sci_cmap:
            karte = ax.contourf(lons, lats, data, levels=bounds, cmap=cmap, norm=norm, extend='max', alpha=0.95, zorder=2)
            cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
        else:
            karte = ax.contourf(lons, lats, data, levels=contour_levels, cmap=cmap, norm=norm, extend='both', alpha=0.95, zorder=2)
            tick_step = int(design.get('cbar_step', 1))
            visible_ticks = levels[::tick_step]
            cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=visible_ticks, aspect=40)
        
        cbar.set_label(legend_title, color=design['text_color'], size=int(design.get('cbar_size', 11)), fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'))
        cbar.ax.xaxis.set_tick_params(color=design['text_color'], labelcolor=design['text_color'], labelsize=9)
        for label in cbar.ax.get_xticklabels(): label.set_fontfamily(design.get('font_family', 'sans-serif'))
    
    line_w = float(design.get('line_width', 0.8))
    world.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=line_w, alpha=float(design.get('border_alpha', 0.4)), zorder=4)
    bundeslaender.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=line_w + 0.4, alpha=float(design.get('border_alpha', 0.4)), zorder=4)

    if overlays.get('pmsl_data') is not None:
        iso = ax.contour(lons, lats, overlays['pmsl_data'], levels=np.arange(900, 1100, 5), colors=design['text_color'], linewidths=1.0, alpha=0.6, zorder=3)
        ax.clabel(iso, inline=True, fontsize=9, fmt='%d', colors=design['text_color'])

    if overlays.get('cities'):
        c_lons = [coords[0] for coords in GERMAN_CITIES.values()]
        c_lats = [coords[1] for coords in GERMAN_CITIES.values()]
        c_names = list(GERMAN_CITIES.keys())
        ax.plot(c_lons, c_lats, 'o', color=design['text_color'], markersize=3, alpha=0.8, zorder=5)
        for lon_c, lat_c, name in zip(c_lons, c_lats, c_names):
            ax.text(lon_c + 0.08, lat_c + 0.08, name, color=design['text_color'], fontsize=8, fontweight='bold',
                    fontfamily=design.get('font_family', 'sans-serif'),
                    path_effects=[path_effects.withStroke(linewidth=1.5, foreground=design['bg_color'])], zorder=5)

    # NEU: Smart Zoom für Zahlenwerte! Erkennt kleine Bundesländer und passt die Größe/Dichte an
    if overlays.get('numbers') and not is_categorical and not is_live_radar:
        xmin, xmax, ymin, ymax = ax.get_xlim()[0], ax.get_xlim()[1], ax.get_ylim()[0], ax.get_ylim()[1]
        try: dy_km = abs(lats[0, 0] - lats[-1, 0]) / max(1, lats.shape[0]) * 111.0
        except: dy_km = 2.2
        if dy_km < 0.1: dy_km = 2.2
        
        dx_deg = xmax - xmin
        zoom_factor = 15.0 / max(1.0, dx_deg)
        target_km = max(15.0, 60.0 / zoom_factor)
        dyn_fontsize = min(12, max(5, int(5 * zoom_factor)))
        
        mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
        
        if legend_title == "Regenrate in mm/h" or legend_title == "Niederschlag in mm" or "Hagel" in legend_title:
            size_px = max(3, int((target_km/1.5) / dy_km))
            local_max = ndimage.maximum_filter(data, size=size_px) == data
            valid_mask = mask & local_max & (data >= 0.1)
        else:
            step = max(1, int(target_km / dy_km)) 
            grid_mask = np.zeros_like(mask, dtype=bool)
            grid_mask[::step, ::step] = True
            valid_mask = mask & grid_mask
        
        for lon_val, lat_val, val in zip(lons[valid_mask], lats[valid_mask], data[valid_mask]):
            if ("Niederschlag" in legend_title or "Regen" in legend_title or "Hagel" in legend_title) and val < 0.1: continue
            if "CAPE" in legend_title and val < 50: continue
            txt = f"{val:.1f}" if ("Niederschlag" in legend_title or "Regen" in legend_title or "Hagel" in legend_title) else f"{val:.0f}"
            ax.text(lon_val, lat_val, txt, fontsize=dyn_fontsize, fontfamily=design.get('font_family', 'sans-serif'), fontweight='bold', 
                    color=design.get('number_color', '#000000'), ha='center', va='center', 
                    path_effects=[path_effects.withStroke(linewidth=1.5, foreground=design.get('number_outline', '#FFFFFF'))], zorder=6)

    if design.get('watermark'):
        ax.text(0.5, 0.02, design['watermark'], transform=ax.transAxes, color=design['text_color'], 
                fontsize=10, fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'),
                ha='center', va='bottom', alpha=0.5, zorder=10)
    
    bg_rgba = mcolors.to_rgba(design.get('title_bg', '#0E1117'), alpha=0.4)
    ec_rgba = mcolors.to_rgba(design['border_color'], alpha=0.6)
    bbox_props = dict(boxstyle="round,pad=0.5", fc=bg_rgba, ec=ec_rgba, lw=1.2)
    
    eps_label = f" | {overlays.get('eps_choice')}" if overlays.get('eps_choice') and overlays.get('eps_choice') != "Ensemble-Mittel" else ""
    ax.text(0.015, 0.985, f"{model_type}{eps_label} | {map_title_time}", transform=ax.transAxes, 
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
    with st.popover(f"🌍 Modell: {st.session_state.model_choice}", width="stretch"):
        idx_m = ["Live-Radar (DWD)", "ICON-D2 (2.2km)", "ICON-D2-RUC (+27h)", "ICON-D2-EPS (+48h)", "ICON-EU (+120h)", "GFS (+384h)"].index(st.session_state.model_choice)
        st.radio("Modell", ["Live-Radar (DWD)", "ICON-D2 (2.2km)", "ICON-D2-RUC (+27h)", "ICON-D2-EPS (+48h)", "ICON-EU (+120h)", "GFS (+384h)"], index=idx_m, key="m_radio", label_visibility="collapsed")
    if st.session_state.m_radio != st.session_state.model_choice:
        st.session_state.model_choice = st.session_state.m_radio
        st.rerun()

    model_choice = st.session_state.model_choice
    
    if "Live-Radar" not in model_choice:
        available_runs = get_available_runs(model_choice)
        run_label = st.selectbox("Modelllauf:", list(available_runs.keys()))
        run_time = available_runs[run_label]
        
        eps_choice = None
        if "EPS (+48h)" in model_choice:
            eps_members = ["Ensemble-Mittel"] + [f"Member {i}" for i in range(1, 21)]
            eps_choice = st.selectbox("Ensemble-Mitglied:", eps_members, index=0)
        
        param_list = ["Temperatur (2m)", "Windböen 10m", "Gesamtbewölkung (%)", "PWAT (mm)", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "500 hPa Geopot. Height", "850 hPa Temp.", "MLCAPE", "CIN", "CAPE & CIN (Deckel)"]
        if "D2" in model_choice:
            param_list.extend(["Signifikantes Wetter", "Radarreflektivität (dBZ)", "Blitzrate (LPI)", "Scherung 0-1 km", "Scherung 0-6 km", "SCP-Index", "Chaser Target-Index", "Simulierte Hagelgröße"])

        if st.session_state.param_choice not in param_list:
            st.session_state.param_choice = param_list[0]

        with st.popover(f"🌡️ Parameter: {st.session_state.param_choice}", width="stretch"):
            idx_p = param_list.index(st.session_state.param_choice)
            st.radio("Parameter", param_list, index=idx_p, key="p_radio", label_visibility="collapsed")
        if st.session_state.p_radio != st.session_state.param_choice:
            st.session_state.param_choice = st.session_state.p_radio
            st.rerun()
            
        param_choice = st.session_state.param_choice
        
        if param_choice not in st.session_state.config: 
            st.session_state.config[param_choice] = load_param_config(param_choice)
    else:
        st.info("Live-Radar aktiv. Zeit- & Parameterauswahl deaktiviert.")
        run_time = datetime.now(timezone.utc)
        param_choice = "Radarreflektivität (Live)"
        eps_choice = None
        
    region_options = list(REGIONS.keys())
    if "D2" in model_choice or "Live" in model_choice: region_options.remove("Europa") 
    if st.session_state.region_choice not in region_options: st.session_state.region_choice = "Deutschland"
    
    with st.popover(f"📍 Region: {st.session_state.region_choice}", width="stretch"):
        idx_r = region_options.index(st.session_state.region_choice)
        st.radio("Region", region_options, index=idx_r, key="r_radio", label_visibility="collapsed")
    if st.session_state.r_radio != st.session_state.region_choice:
        st.session_state.region_choice = st.session_state.r_radio
        st.rerun()
        
    region_choice = st.session_state.region_choice
    
    run_to_run = False
    if "Live-Radar" not in model_choice:
        run_to_run = st.toggle("🔄 Run-to-Run Shift (zum Vorlauf)", value=False)

with tab_overlays:
    st.info("Kombiniere mehrere Karten-Layer:")
    show_cities = st.toggle("🏙️ Wichtige Städte anzeigen", value=True) if region_choice == "Deutschland" else False
    show_pmsl = st.toggle("💨 Isobaren (Luftdruck)", value=True) if param_choice == "850 hPa Temp." else False
    
    show_numbers = False
    if param_choice in ["Temperatur (2m)", "Windböen 10m", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "Simulierte Hagelgröße"]:
        show_numbers = st.toggle("🔢 Zahlenwerte auf Karte", value=False)
        
    show_clouds = False
    if param_choice == "Signifikantes Wetter":
        show_clouds = st.toggle("☁️ Gesamtbewölkung (als Hintergrund)", value=False)

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

    # NEU: Wissenschaftliche Farbskalen Schalter!
    st.session_state.design['scientific_cmap'] = st.toggle("🧪 Wissenschaftliche Farbskalen (Modern)", value=st.session_state.design.get('scientific_cmap', False))

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
    if st.button("💾 Design & Wasserzeichen Speichern", type="primary", width="stretch"): save_design_config(st.session_state.design)

    if "Live-Radar" not in model_choice:
        st.divider()
        st.subheader("🔢 Zahlen-Design")
        c_z1, c_z2 = st.columns(2)
        with c_z1: st.session_state.design['number_color'] = st.color_picker("Zahlfarbe", value=st.session_state.design.get('number_color', '#000000'))
        with c_z2: st.session_state.design['number_outline'] = st.color_picker("Umrandung", value=st.session_state.design.get('number_outline', '#FFFFFF'))

        if not st.session_state.design.get('scientific_cmap', False):
            st.divider()
            st.subheader(f"📊 Manuelle Skala: {param_choice}")
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
                if st.button("➕ Neu", width="stretch"): st.session_state.config[param_choice].append({"value": max([c['value'] for c in new_config]) + 1 if new_config else 0.0, "color": "#ffffff", "_id": str(uuid.uuid4())}); st.rerun()
            with col_btn2:
                if st.button("💾 Skala Speichern", width="stretch"): save_param_config(param_choice, st.session_state.config[param_choice])
                
            st.divider()
            st.subheader("📥 Gespeicherte Skala laden")
            cloud_files = get_saved_config_files()
            if cloud_files:
                selected_file = st.selectbox("Cloud-Dateien:", ["-- Wählen --"] + cloud_files, label_visibility="collapsed")
                if selected_file != "-- Wählen --":
                    if st.button("Laden & Anwenden", width="stretch"):
                        try:
                            g = get_github_client()
                            repo = g.get_repo(st.secrets["GITHUB_REPO"])
                            st.session_state.config[param_choice] = json.loads(repo.get_contents(f"configs/{selected_file}").decoded_content.decode())
                            st.success(f"{selected_file} geladen!"); st.rerun()
                        except Exception as e: st.error(f"Fehler: {e}")

# --- HAUPTBEREICH TABS ---
tab_map, tab_ens = st.tabs(["🗺️ Karten-Terminal", "📈 Ensemble (Spaghetti)"])

with tab_map:
    max_h = 0 if "Live" in model_choice else (384 if "GFS" in model_choice else (120 if "EU" in model_choice else (48 if "EPS" in model_choice else (27 if "RUC" in model_choice else 48))))
    step_h = 3 if "GFS" in model_choice else 1
    tz_berlin = ZoneInfo("Europe/Berlin")
    start_time_local = run_time.astimezone(tz_berlin)

    st.markdown(f"""
        <div class="glass-banner" style="color: {st.session_state.design['text_color']}; border-color: {st.session_state.design['border_color']};">
            🌤️ {model_choice} | 🌡️ {param_choice}
        </div>
    """, unsafe_allow_html=True)

    if not "Live" in model_choice:
        selected_datetime = st.slider("Zeitpunkt", min_value=start_time_local, max_value=start_time_local + timedelta(hours=max_h), 
                                      value=start_time_local + timedelta(hours=min(st.session_state.f_hour, max_h)), step=timedelta(hours=step_h), format="ddd, DD.MM. - HH:mm")
        chosen_f_hour = int((selected_datetime - start_time_local).total_seconds() / 3600)
        st.session_state.f_hour = chosen_f_hour
    else:
        chosen_f_hour = 0
        selected_datetime = start_time_local

    config_hash = hash(str(st.session_state.config.get(param_choice)) + str(st.session_state.design) + str(show_cities) + str(show_clouds) + str(show_numbers) + (str(eps_choice) if not "Live" in model_choice else "") + str(run_to_run))
    cache_key = f"{model_choice}_{run_time.strftime('%Y%m%d%H') if not 'Live' in model_choice else 'live'}_{param_choice}_{region_choice}_{chosen_f_hour}_{show_pmsl}_{config_hash}"

    if cache_key in st.session_state.map_cache:
        st.image(st.session_state.map_cache[cache_key]["image"], width="stretch")
        if st.session_state.map_cache[cache_key].get("extremes"):
            st.info(f"**Extremwerte (Deutschland):** {st.session_state.map_cache[cache_key]['extremes']}")
    else:
        btn_label = "🗺️ Live-Radar laden" if "Live" in model_choice else f"🗺️ Karte für +{chosen_f_hour}h berechnen & anzeigen"
        if st.button(btn_label, type="primary", width="stretch"):
            with st.spinner("Lade Daten und rendere Karte..."):
                if "Live-Radar" in model_choice:
                    img_bytes = create_map([], None, None, None, f"Aktuell | {selected_datetime.strftime('%d.%m. %H:%M')} Uhr", "", model_choice, region_choice, {"cities": show_cities}, st.session_state.design)
                    st.session_state.map_cache[cache_key] = {"image": img_bytes, "extremes": None}
                    st.rerun()
                else:
                    overlays_dict = {"pmsl": show_pmsl, "numbers": show_numbers, "cities": show_cities, "clouds": show_clouds, "eps_choice": eps_choice}

                    if run_to_run:
                        runs_list = list(available_runs.values())
                        run_step = int((runs_list[0] - runs_list[1]).total_seconds() / 3600) if len(runs_list) > 1 else 6
                        prev_run_time = run_time - timedelta(hours=run_step)
                        target_valid = run_time + timedelta(hours=chosen_f_hour)
                        prev_f_hour = int((target_valid - prev_run_time).total_seconds() / 3600)

                        if prev_f_hour < 0:
                            st.error("Run-to-Run Shift: Der Vorlauf reicht nicht weit genug in die Zukunft für diesen Zeitpunkt!")
                        else:
                            lons, lats, data_curr, title, pmsl, extra = load_parameter_data(run_time, chosen_f_hour, param_choice, model_choice, overlays_dict, eps_choice)
                            _, _, data_prev, _, _, _ = load_parameter_data(prev_run_time, prev_f_hour, param_choice, model_choice, overlays_dict, eps_choice)

                            if data_curr is not None and data_prev is not None:
                                data = data_curr - data_prev
                                title = f"Run-to-Run Shift | {title}"
                                r2r_config = [
                                    {"value": -15.0, "color": "#053061"}, {"value": -5.0, "color": "#2166ac"}, {"value": -2.0, "color": "#4393c3"},
                                    {"value": -0.5, "color": "#92c5de"}, {"value": 0.0, "color": "#ffffff"}, {"value": 0.5, "color": "#f4a582"},
                                    {"value": 2.0, "color": "#d6604d"}, {"value": 5.0, "color": "#b2182b"}, {"value": 15.0, "color": "#67001f"}
                                ]
                                img_bytes = create_map(r2r_config, lons, lats, data, f"+{chosen_f_hour}h | {selected_datetime.strftime('%d.%m. %H:00')} Uhr", title, model_choice, region_choice, overlays_dict, st.session_state.design)
                                st.session_state.map_cache[cache_key] = {"image": img_bytes, "extremes": None}
                                st.rerun()
                            else:
                                st.error("Daten für den Vorlauf auf dem Server nicht verfügbar.")
                    else:
                        lons, lats, data, title, pmsl, extra_overlay = load_parameter_data(run_time, chosen_f_hour, param_choice, model_choice, overlays_dict, eps_choice)
                        
                        if lons is not None:
                            extremes_txt = None
                            if region_choice == "Deutschland" and param_choice != "Signifikantes Wetter":
                                xmin, xmax, ymin, ymax = REGIONS["Deutschland"]
                                mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
                                if np.any(mask):
                                    unit = title.split("in ")[-1] if "in " in title else title.split("(")[-1].replace(")", "")
                                    extremes_txt = f"Min: {np.nanmin(data[mask]):.1f} {unit} | Max: {np.nanmax(data[mask]):.1f} {unit}"

                            overlays_dict['pmsl_data'], overlays_dict['extra_data'] = pmsl, extra_overlay
                            t_str = selected_datetime.strftime('%d.%m. %H:00')
                            img_bytes = create_map(st.session_state.config[param_choice], lons, lats, data, f"+{chosen_f_hour}h | {t_str} Uhr", title, model_choice, region_choice, overlays_dict, st.session_state.design)
                            
                            st.session_state.map_cache[cache_key] = {"image": img_bytes, "extremes": extremes_txt}
                            st.rerun() 
                        else:
                            st.error(f"Ein Datensatz für diesen Parameter (+{chosen_f_hour}h) ist auf den Servern für diesen Modelllauf noch nicht verfügbar.")

with tab_ens:
    st.markdown("### 📈 Profi-Ensemble Prognose (Punktabfrage)")
    st.info("Hinweis: Da Ensemble-Berechnungen tausende Gigabyte erfordern, wird diese Ansicht ressourcenschonend direkt aus der Open-Meteo API generiert.")
    
    col_e1, col_e2, col_e3 = st.columns(3)
    
    with col_e1: ens_city = st.selectbox("Ort:", list(GERMAN_CITIES.keys()))
    with col_e2: ens_model = st.selectbox("Modell-Ensemble:", ["ICON-EPS (DWD)", "ICON-D2-EPS (DWD)", "GFS-ENS (NOAA)", "ECMWF-EPS"])
    with col_e3: ens_param = st.selectbox("Wetter-Parameter:", ["Temperatur (2m)", "850 hPa Temp.", "Niederschlag (mm/h)", "Windböen (km/h)", "CAPE (J/kg)"])
    
    om_model_map = {"ICON-EPS (DWD)": "icon_ensemble", "ICON-D2-EPS (DWD)": "icon_d2_ensemble", "GFS-ENS (NOAA)": "gfs_seamless", "ECMWF-EPS": "ecmwf_ensemble"}
    om_param_map = {"Temperatur (2m)": "temperature_2m", "850 hPa Temp.": "temperature_850hPa", "Niederschlag (mm/h)": "precipitation", "Windböen (km/h)": "wind_gusts_10m", "CAPE (J/kg)": "cape"}
    
    if st.button("🚀 Ensemble-Diagramm berechnen", type="primary", width="stretch"):
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
                    if ens_param == "Windböen (km/h)" and "icon" not in om_model_map[ens_model]: vals = vals * 3.6
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
                st.error("Fehler beim Abruf der Ensemble-Daten.")
