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
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import xarray as xr
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
    </style>
""", unsafe_allow_html=True)

st.title("🗺️ Statische Modellkarte (Profi-Terminal)")

if "map_cache" not in st.session_state: st.session_state.map_cache = {}
if "f_hour" not in st.session_state: st.session_state.f_hour = 0
if "config" not in st.session_state: st.session_state.config = {}

# --- DESIGN & KATEGORIEN DEFAULTS ---
DEFAULT_DESIGN = {"bg_color": "#0E1117", "text_color": "#FFFFFF", "border_color": "#FFFFFF"}
if "design" not in st.session_state: st.session_state.design = DEFAULT_DESIGN.copy()

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
    "Signifikantes Wetter": [
        {"value": 1, "color": "#a1d99b"}, {"value": 2, "color": "#31a354"}, {"value": 3, "color": "#006d2c"},
        {"value": 4, "color": "#fcc5c0"}, {"value": 5, "color": "#f768a1"}, {"value": 6, "color": "#ae017e"},
        {"value": 7, "color": "#c6dbef"}, {"value": 8, "color": "#6baed6"}, {"value": 9, "color": "#2171b5"},
        {"value": 10, "color": "#fd8d3c"}, {"value": 11, "color": "#e31a1c"}
    ]
}

REGIONS = {
    "Europa": [-15.0, 30.0, 35.0, 65.0],
    "Deutschland": [5.5, 15.5, 47.0, 55.0],
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

# --- GITHUB, CONFIGS & DOWNLOAD LOGIK ---
def get_github_client(): return Github(auth=Auth.Token(st.secrets["GITHUB_TOKEN"])) if "GITHUB_TOKEN" in st.secrets else None

def load_param_config(param_name):
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try:
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            data = json.loads(repo.get_contents(f"config_{param_name.replace(' ', '_').replace('/', '_')}.json").decoded_content.decode())
            if isinstance(data, list): return data
        except: pass
    return DEFAULT_CONFIGS.get(param_name, DEFAULT_CONFIGS["Temperatur (2m)"])

def save_param_config(param_name, config_list):
    g, repo_name = get_github_client(), st.secrets.get("GITHUB_REPO")
    if g and repo_name:
        try:
            repo = g.get_repo(repo_name)
            filename = f"config_{param_name.replace(' ', '_').replace('/', '_')}.json"
            try: repo.update_file(filename, f"Update {param_name}", json.dumps(config_list, indent=4), repo.get_contents(filename).sha)
            except: repo.create_file(filename, f"Create {param_name}", json.dumps(config_list, indent=4))
            st.success(f"Farbskala erfolgreich gespeichert!")
        except Exception as e: st.error(f"Fehler beim Speichern: {e}")

@st.cache_data
def load_borders():
    w_r = requests.get("https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson").text
    bl_r = requests.get("https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json").text
    with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f1, tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f2:
        f1.write(w_r); f1_name = f1.name; f2.write(bl_r); f2_name = f2.name
    return gpd.read_file(f1_name), gpd.read_file(f2_name)

def get_available_runs(model_name):
    now = datetime.now(timezone.utc)
    step, delay = (12, 9.5) if "AIFS" in model_name else ((6, 5.0) if "GFS" in model_name else ((6, 3.0) if "EU" in model_name else (3, 2.0)))
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
    
    # NEU: Wind Download Logik
    if param_name == "U-Wind": dm = {"U-Wind": ("u_10m", "10m_u", None)}
    elif param_name == "V-Wind": dm = {"V-Wind": ("v_10m", "10m_v", None)}
    else:
        dm = {"Temperatur (2m)": ("t_2m", "2d_t_2m", None), "Windböen 10m": ("vmax_10m", "2d_vmax_10m", None), 
              "Akk. Niederschlag (mm)": ("tot_prec", "2d_tot_prec", None), "Niederschlagsrate (mm/h)": ("tot_prec", "2d_tot_prec", None), 
              "500 hPa Geopot. Height": ("fi", "fi", "500"), "850 hPa Temp.": ("t", "t", "850"), "MLCAPE": ("cape_ml", "cape_ml", None), 
              "PMSL": ("pmsl", "pmsl", None), "Signifikantes Wetter": ("ww", "ww", None)}
        
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
    lons, lats, vals = get_raw_grib(run_time, forecast_hour, model_type, param_name)
    pmsl_data = None
    if isinstance(vals, tuple): vals, p_raw = vals; pmsl_data = (p_raw / 100.0) if overlays.get('pmsl') else None
    if vals is None: return None, None, None, "", None, None, None
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
    elif param_name == "Signifikantes Wetter":
        title = "Signifikantes Wetter"
        # Logik-Umwandlung WMO 4677 in unsere 1-11 Kategorien
        ww = np.zeros_like(vals)
        ww[np.isin(vals, [50, 51, 58, 61, 80])] = 1
        ww[np.isin(vals, [52, 53, 59, 62, 81])] = 2
        ww[np.isin(vals, [54, 55, 63, 64, 65, 82])] = 3
        ww[np.isin(vals, [68, 83])] = 4
        ww[np.isin(vals, [69, 84])] = 5
        ww[np.isin(vals, [70, 71, 85])] = 7
        ww[np.isin(vals, [72, 73, 86])] = 8
        ww[np.isin(vals, [74, 75])] = 9
        ww[np.isin(vals, [91, 92, 93, 94, 95])] = 10
        ww[np.isin(vals, [96, 97, 98, 99])] = 11
        ww[ww == 0] = np.nan
        vals = ww

    # Lade Wind-Daten für Pfeile, falls aktiv
    u, v = None, None
    if overlays.get('wind') and param_name in ["Temperatur (2m)", "Windböen 10m", "Niederschlagsrate (mm/h)"]:
        _, _, raw_u = get_raw_grib(run_time, forecast_hour, model_type, "U-Wind")
        _, _, raw_v = get_raw_grib(run_time, forecast_hour, model_type, "V-Wind")
        if raw_u is not None and raw_v is not None:
            u, v = np.squeeze(raw_u), np.squeeze(raw_v)
            if isinstance(u, tuple): u = u[0]
            if isinstance(v, tuple): v = v[0]

    return lons, lats, vals, title, pmsl_data, u, v

# --- MAP RENDERER ---
def create_map(config_list, lons, lats, data, map_title_time, legend_title, model_type, region, overlays, design):
    world, bundeslaender = load_borders()
    
    levels = [c['value'] for c in sorted(config_list, key=lambda x: x['value'])]
    colors = [c['color'] for c in sorted(config_list, key=lambda x: x['value'])]
    min_v, max_v = min(levels), max(levels)
    if max_v == min_v: max_v += 1 
    
    # Unterscheidung zwischen normaler Farbskala und kategorischem (Sig. Wetter)
    is_categorical = (legend_title == "Signifikantes Wetter")
    
    if is_categorical:
        cmap = mcolors.ListedColormap(colors)
        contour_levels = np.arange(0.5, len(levels) + 1.5, 1.0)
    else:
        cmap = mcolors.LinearSegmentedColormap.from_list("custom", list(zip([(v - min_v) / (max_v - min_v) for v in levels], colors)))
        contour_levels = np.linspace(min_v, max_v, 150)

    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(design['bg_color'])
    ax.set_facecolor(design['bg_color'])
    
    if region in REGIONS: 
        ax.set_xlim(REGIONS[region][0], REGIONS[region][1])
        ax.set_ylim(REGIONS[region][2], REGIONS[region][3])
        
    karte = ax.contourf(lons, lats, data, levels=contour_levels, cmap=cmap, extend='both' if not is_categorical else 'neither', alpha=0.95)
    
    # Farbskala zeichnen
    if is_categorical:
        cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
        cbar.ax.set_xticklabels([SIG_WETTER_LABELS.get(int(v), str(v)) for v in levels], rotation=45, ha='right', fontsize=8)
    else:
        cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
    
    cbar.set_label(legend_title, color=design['text_color'], size=11, fontweight='bold')
    cbar.ax.xaxis.set_tick_params(color=design['text_color'], labelcolor=design['text_color'], labelsize=9)
    
    # Grenzen
    world.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=0.8, alpha=0.2)
    bundeslaender.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=1.2, alpha=0.4)

    # 1. OVERLAY: Isobaren
    if overlays.get('pmsl_data') is not None:
        iso = ax.contour(lons, lats, overlays['pmsl_data'], levels=np.arange(900, 1100, 5), colors=design['text_color'], linewidths=1.0, alpha=0.6)
        ax.clabel(iso, inline=True, fontsize=9, fmt='%d', colors=design['text_color'])

    # 2. OVERLAY: Topographie / Höhenlinien (250m)
    if overlays.get('topo'):
        t_lons, t_lats, t_data = get_topography(model_type)
        if t_data is not None:
            topo = ax.contour(t_lons, t_lats, t_data, levels=np.arange(250, 4000, 250), colors=design['text_color'], alpha=0.25, linewidths=0.6)

    # 3. OVERLAY: Windrichtungs-Pfeile
    u, v = overlays.get('u'), overlays.get('v')
    if u is not None and v is not None:
        try: dy = abs(lats[0, 0] - lats[-1, 0]) / max(1, lats.shape[0]) * 111.0
        except: dy = 2.2
        step = max(1, int(35 / dy)) # Etwa alle 35 km ein Pfeil (perfekte Dichte)
        ax.quiver(lons[::step, ::step], lats[::step, ::step], u[::step, ::step], v[::step, ::step], 
                  pivot='middle', color=design['text_color'], alpha=0.7, scale=400, width=0.003)

    # 4. OVERLAY: Wichtige Städte
    if overlays.get('cities') and region == "Deutschland":
        c_lons = [coords[0] for coords in GERMAN_CITIES.values()]
        c_lats = [coords[1] for coords in GERMAN_CITIES.values()]
        c_names = list(GERMAN_CITIES.keys())
        ax.plot(c_lons, c_lats, 'o', color=design['text_color'], markersize=3, alpha=0.8)
        for lon_c, lat_c, name in zip(c_lons, c_lats, c_names):
            ax.text(lon_c + 0.08, lat_c + 0.08, name, color=design['text_color'], fontsize=8, fontweight='bold',
                    path_effects=[path_effects.withStroke(linewidth=1.5, foreground=design['bg_color'])])

    # 5. OVERLAY: Zahlenwerte
    if overlays.get('numbers') and not is_categorical:
        xmin, xmax, ymin, ymax = ax.get_xlim()[0], ax.get_xlim()[1], ax.get_ylim()[0], ax.get_ylim()[1]
        try: dy = abs(lats[0, 0] - lats[-1, 0]) / max(1, lats.shape[0]) * 111.0
        except: dy = 2.2
        target_km = 12 if region == "Europa" else (5 if region == "Deutschland" else 2)
        step = max(1, int(target_km / max(0.1, dy)))
        
        mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
        grid_mask = np.zeros_like(mask, dtype=bool); grid_mask[::step, ::step] = True
        
        for lon_val, lat_val, val in zip(lons[mask & grid_mask], lats[mask & grid_mask], data[mask & grid_mask]):
            if ("Niederschlag" in legend_title or "Regen" in legend_title) and val < 0.1: continue
            if "CAPE" in legend_title and val < 50: continue
            txt = f"{val:.1f}" if ("Niederschlag" in legend_title or "Regen" in legend_title) else f"{val:.0f}"
            ax.text(lon_val, lat_val, txt, fontsize=8, fontfamily='sans-serif', fontweight='bold', 
                    color='black', ha='center', va='center', path_effects=[path_effects.withStroke(linewidth=1.5, foreground='white')])

    ax.axis('off')
    
    # Modernes Header-Label
    bbox_props = dict(boxstyle="round,pad=0.4", fc=design['bg_color'], ec=design['border_color'], lw=0.5, alpha=0.85)
    ax.text(0.015, 0.985, f"{model_type} | {map_title_time}", transform=ax.transAxes, 
            color=design['text_color'], fontsize=11, fontweight='bold', fontfamily='sans-serif', 
            ha='left', va='top', bbox=bbox_props)
    
    buf = io.BytesIO()
    # Sicheres Speichern (Hintergrundfarbe dynamisch)
    fig.savefig(buf, format="png", bbox_inches='tight', pad_inches=0.1, facecolor=design['bg_color'] if design['bg_color'] else '#0E1117')
    plt.close(fig)
    return buf.getvalue()

# --- BENUTZEROBERFLÄCHE (SEITENLEISTE MIT TABS) ---
st.sidebar.header("⚙️ Terminal-Steuerung")
tab_main, tab_overlays, tab_design = st.sidebar.tabs(["⚙️ Basis", "🔣 Overlays", "🎨 Design"])

with tab_main:
    model_choice = st.selectbox("Modell:", ["ICON-D2 (2.2km)", "ICON-EU (+120h)"])
    available_runs = get_available_runs(model_choice)
    run_label = st.selectbox("Modelllauf:", list(available_runs.keys()))
    run_time = available_runs[run_label]
    
    param_list = ["Temperatur (2m)", "Windböen 10m", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "500 hPa Geopot. Height", "850 hPa Temp.", "MLCAPE", "Signifikantes Wetter"]
    param_choice = st.selectbox("Parameter:", param_list)
    
    if param_choice not in st.session_state.config: 
        st.session_state.config[param_choice] = load_param_config(param_choice)
        
    region_options = list(REGIONS.keys())
    if "D2" in model_choice: region_options.remove("Europa") 
    region_choice = st.selectbox("Region:", region_options, index=region_options.index("Deutschland") if "Deutschland" in region_options else 0)

with tab_overlays:
    st.info("Kombiniere mehrere Karten-Layer:")
    show_topo = st.toggle("⛰️ Höhenlinien (250m Raster)", value=False)
    show_cities = st.toggle("🏙️ Wichtige Städte anzeigen", value=True) if region_choice == "Deutschland" else False
    show_pmsl = st.toggle("💨 Isobaren (Luftdruck)", value=True) if param_choice == "850 hPa Temp." else False
    
    show_wind = False
    if param_choice in ["Temperatur (2m)", "Windböen 10m", "Niederschlagsrate (mm/h)"]:
        show_wind = st.toggle("🌬️ Windrichtungs-Pfeile", value=False)
        
    show_numbers = st.toggle("🔢 Zahlenwerte auf Karte", value=False) if param_choice not in ["Signifikantes Wetter"] else False

with tab_design:
    st.subheader("Farben & Stil")
    st.session_state.design['bg_color'] = st.color_picker("Hintergrundfarbe", value=st.session_state.design['bg_color'])
    st.session_state.design['text_color'] = st.color_picker("Text- & Linienfarbe", value=st.session_state.design['text_color'])
    st.session_state.design['border_color'] = st.color_picker("Grenzen-Farbe", value=st.session_state.design['border_color'])
    
    st.divider()
    st.subheader(f"Skala: {param_choice}")
    
    new_config = []
    for i, item in enumerate(st.session_state.config[param_choice]):
        c1, c2, c3 = st.columns([2, 2, 1])
        with c1: val = st.number_input("W", value=float(item['value']), step=1.0, key=f"v_{i}", label_visibility="collapsed")
        with c2: col = st.color_picker("F", value=item['color'], key=f"c_{i}", label_visibility="collapsed")
        with c3:
            if st.button("🗑️", key=f"d_{i}"): 
                st.session_state.config[param_choice].pop(i)
                st.rerun()
        new_config.append({"value": val, "color": col})
    
    st.session_state.config[param_choice] = new_config
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("➕ Neu"): 
            st.session_state.config[param_choice].append({"value": max([c['value'] for c in new_config]) + 1 if new_config else 0.0, "color": "#ffffff"})
            st.rerun()
    with col_btn2:
        if st.button("💾 Speichern"): save_param_config(param_choice, st.session_state.config[param_choice])

# --- HAUPTBEREICH & SCHIEBEREGLER ---
max_h = 48 if "D2" in model_choice else 120
tz_berlin = ZoneInfo("Europe/Berlin")
start_time_local = run_time.astimezone(tz_berlin)

st.markdown(f"""
    <div class="glass-banner" style="color: {st.session_state.design['text_color']}; border-color: {st.session_state.design['border_color']};">
        🌤️ {model_choice} | 🌡️ {param_choice}
    </div>
""", unsafe_allow_html=True)

selected_datetime = st.slider("Zeitpunkt", min_value=start_time_local, max_value=start_time_local + timedelta(hours=max_h), 
                              value=start_time_local + timedelta(hours=min(st.session_state.f_hour, max_h)), step=timedelta(hours=1), format="ddd, DD.MM. - HH:mm")

chosen_f_hour = int((selected_datetime - start_time_local).total_seconds() / 3600)
st.session_state.f_hour = chosen_f_hour

config_hash = hash(str(st.session_state.config[param_choice]) + str(st.session_state.design) + str(show_wind) + str(show_cities) + str(show_topo))
cache_key = f"{model_choice}_{run_label}_{param_choice}_{region_choice}_{chosen_f_hour}_{show_pmsl}_{show_numbers}_{config_hash}"

if cache_key in st.session_state.map_cache:
    st.image(st.session_state.map_cache[cache_key], use_container_width=True)
else:
    if st.button(f"🗺️ Karte für +{chosen_f_hour}h berechnen & anzeigen", type="primary", use_container_width=True):
        with st.spinner("Lade GRIB-Daten und rendere Karte (Overlays werden berechnet)..."):
            overlays_dict = {"pmsl": show_pmsl, "numbers": show_numbers, "cities": show_cities, "topo": show_topo, "wind": show_wind}
            lons, lats, data, title, pmsl, u, v = load_parameter_data(run_time, chosen_f_hour, param_choice, model_choice, overlays_dict)
            
            if lons is not None:
                overlays_dict['pmsl_data'], overlays_dict['u'], overlays_dict['v'] = pmsl, u, v
                t_str = selected_datetime.strftime('%d.%m. %H:00')
                img_bytes = create_map(st.session_state.config[param_choice], lons, lats, data, f"+{chosen_f_hour}h | {t_str} Uhr", title, model_choice, region_choice, overlays_dict, st.session_state.design)
                st.session_state.map_cache[cache_key] = img_bytes
                st.rerun() 
            else:
                st.error("Ein Datensatz für diesen Parameter ist auf den Servern noch nicht verfügbar.")
