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

# --- SEITEN-LAYOUT & MODERNES CSS (UI-Design) ---
st.set_page_config(page_title="Profi-Wetterterminal", page_icon="🌤️", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
        html, body, [class*="css"] {
            font-family: 'Inter', sans-serif !important;
        }
        img {
            border-radius: 12px;
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.5);
            transition: all 0.3s ease;
        }
        .glass-banner {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 12px;
            padding: 18px 25px;
            text-align: center;
            font-size: 1.25em;
            font-weight: 600;
            color: #f1f3f5;
            margin-bottom: 25px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
            letter-spacing: 0.5px;
        }
        .stSlider > div > div > div {
            background: linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%);
        }
    </style>
""", unsafe_allow_html=True)

st.title("🗺️ Statische Modellkarte (Profi-Terminal)")

if "map_cache" not in st.session_state: st.session_state.map_cache = {}
if "f_hour" not in st.session_state: st.session_state.f_hour = 0
if "config" not in st.session_state: st.session_state.config = {}

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

# --- REGIONEN ---
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

# --- NEU: SICHERES GITHUB SPEICHER-SYSTEM PRO PARAMETER ---
def get_github_client(): 
    return Github(auth=Auth.Token(st.secrets["GITHUB_TOKEN"])) if "GITHUB_TOKEN" in st.secrets else None

def get_config_filename(param_name):
    # Ersetzt Leerzeichen und Sonderzeichen für saubere Dateinamen
    safe_name = param_name.replace(" ", "_").replace("/", "_").replace(".", "")
    return f"config_{safe_name}.json"

def load_param_config(param_name):
    g = get_github_client()
    if g and "GITHUB_REPO" in st.secrets:
        try: 
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            filename = get_config_filename(param_name)
            file_content = repo.get_contents(filename).decoded_content.decode()
            loaded_data = json.loads(file_content)
            if isinstance(loaded_data, list):
                return loaded_data
        except Exception: 
            pass # Datei existiert noch nicht, wir nutzen den Fallback
            
    return DEFAULT_CONFIGS.get(param_name, DEFAULT_CONFIGS["Temperatur (2m)"])

def save_param_config(param_name, config_list):
    g, repo_name = get_github_client(), st.secrets.get("GITHUB_REPO")
    if g and repo_name:
        try:
            repo = g.get_repo(repo_name)
            filename = get_config_filename(param_name)
            try: 
                # Aktualisieren, falls die Datei schon existiert
                file = repo.get_contents(filename)
                repo.update_file(filename, f"Update Farbskala für {param_name}", json.dumps(config_list, indent=4), file.sha)
            except: 
                # Neu anlegen, falls sie noch nicht existiert
                repo.create_file(filename, f"Create Farbskala für {param_name}", json.dumps(config_list, indent=4))
            st.success(f"Farbskala für {param_name} erfolgreich isoliert gespeichert!")
        except Exception as e: 
            st.error(f"Fehler beim Speichern: {e}")

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
    effective_now = now - timedelta(hours=delay)
    latest_run = effective_now.replace(hour=(effective_now.hour // step) * step, minute=0, second=0, microsecond=0)
    return {f"Lauf: { (latest_run - timedelta(hours=i*step)).strftime('%d.%m.%Y | %H:02d') }Z": (latest_run - timedelta(hours=i*step)) for i in range(6)}

@st.cache_data(ttl=3600, show_spinner=False)
def download_and_extract(url, is_bz2=False):
    if not url: return None, None, None
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla"}, timeout=15)
        if resp.status_code != 200: return None, None, None
        with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f: f.write(bz2.decompress(resp.content) if is_bz2 else resp.content); temp_path = f.name
        ds = xr.open_dataset(temp_path, engine='cfgrib')
        if ds['longitude'].max() > 180: ds = ds.assign_coords(longitude=(((ds.longitude + 180) % 360) - 180)).sortby('longitude')
        act_var = next((v for v in ['t2m','2t','t','d2m','2d','vmax_10m','gust','tp','tot_prec','fi','z','gh','cape','cape_ml'] if v in ds.variables), list(ds.data_vars)[0])
        vals, lats, lons = np.squeeze(ds[act_var].values), ds['latitude'].values, ds['longitude'].values
        pmsl_vals = next((np.squeeze(ds[p].values) for p in ['prmsl', 'pmsl', 'msl'] if p in ds.variables), None)
        while vals.ndim > 2: vals = vals[0]
        if lons.ndim == 1: lons, lats = np.meshgrid(lons, lats)
        while lons.ndim > 2: lons, lats = lons[0], lats[0]
        ds.close(); os.remove(temp_path)
        if pmsl_vals is not None:
            while pmsl_vals.ndim > 2: pmsl_vals = pmsl_vals[0]
            return lons, lats, (vals, pmsl_vals)
        return lons, lats, vals
    except: return None, None, None

def get_raw_grib(run_time, forecast_hour, model, param_name):
    run_str, date_str, hour_str = f"{run_time.hour:02d}", run_time.strftime("%Y%m%d"), f"{forecast_hour:03d}"
    if "AIFS" in model: return download_and_extract(f"https://data.ecmwf.int/forecasts/{date_str}/{run_str}z/aifs/0p25/oper/{date_str}{run_str}0000-{str(forecast_hour)}h-oper-fc.grib2")
    if "GFS" in model:
        vm = {"Temperatur (2m)": "var_TMP=on&lev_2_m_above_ground=on", "Akk. Niederschlag (mm)": "var_APCP=on&lev_surface=on", "MLCAPE": "var_CAPE=on&lev_surface=on", "PMSL": "var_PRMSL=on&lev_mean_sea_level=on"}
        fs = vm.get(param_name, "")
        if param_name == "850 hPa Temp.": fs = "var_TMP=on&lev_850_mb=on&var_PRMSL=on&lev_mean_sea_level=on"
        return download_and_extract(f"https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?dir=%2Fgfs.{date_str}%2F{run_str}%2Fatmos&file=gfs.t{run_str}z.pgrb2.0p25.f{hour_str}&{fs}" if fs else None)
    
    dm = {"Temperatur (2m)": ("t_2m", "2d_t_2m", None), "Taupunkt (2m)": ("td_2m", "2d_td_2m", None), "Windböen 10m": ("vmax_10m", "2d_vmax_10m", None), "Akk. Niederschlag (mm)": ("tot_prec", "2d_tot_prec", None), "Niederschlagsrate (mm/h)": ("tot_prec", "2d_tot_prec", None), "500 hPa Geopot. Height": ("fi", "fi", "500"), "850 hPa Temp.": ("t", "t", "850"), "MLCAPE": ("cape_ml", "cape_ml", None), "PMSL": ("pmsl", "pmsl", None)}
    if param_name not in dm: return None, None, None
    fld, var, lvl = dm[param_name]
    
    if lvl: 
        if "D2" in model: u = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/{fld}/icon-d2_germany_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_{var.upper()}.grib2.bz2"
        else: u = f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{fld}/icon-eu_europe_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_{var.upper()}.grib2.bz2"
    else: 
        if "D2" in model: u = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/{fld}/icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_{var}.grib2.bz2"
        else: u = f"https://opendata.dwd.de/weather/nwp/icon-eu/grib/{run_str}/{fld}/icon-eu_europe_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_{var.replace('2d_', '').upper()}.grib2.bz2"
        
    return download_and_extract(u, is_bz2=True)

def load_parameter_data(run_time, forecast_hour, param_name, model_type, show_pmsl=False):
    pmsl_data = None
    lons, lats, vals = get_raw_grib(run_time, forecast_hour, model_type, param_name)
    if isinstance(vals, tuple): vals, p_raw = vals; pmsl_data = (p_raw / 100.0) if show_pmsl else None
    if vals is None: return None, None, None, "", None
    vals = np.squeeze(vals)
    
    title = ""
    if "Temp" in param_name or param_name == "Taupunkt (2m)": vals -= 273.15; title = "Temperatur in °C"
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
    return lons, lats, vals, title, pmsl_data

# --- MODERNISIERTE KARTE ZEICHNEN ---
def create_map(config_list, lons, lats, data, map_title_time, legend_title, model_type, region, pmsl_data=None, show_numbers=False):
    world, bundeslaender = load_borders()
    
    levels = [c['value'] for c in sorted(config_list, key=lambda x: x['value'])]
    colors = [c['color'] for c in sorted(config_list, key=lambda x: x['value'])]
    min_v, max_v = min(levels), max(levels)
    if max_v == min_v: max_v += 1 
    
    cmap = mcolors.LinearSegmentedColormap.from_list("custom", list(zip([(v - min_v) / (max_v - min_v) for v in levels], colors)))
    
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor('#0E1117')
    ax.set_facecolor('#0E1117')
    
    if region in REGIONS: 
        ax.set_xlim(REGIONS[region][0], REGIONS[region][1])
        ax.set_ylim(REGIONS[region][2], REGIONS[region][3])
        
    karte = ax.contourf(lons, lats, data, levels=np.linspace(min_v, max_v, 150), cmap=cmap, extend='both', alpha=0.95)
    
    # Elegante, horizontale Farbskala unten
    cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
    cbar.set_label(legend_title, color='white', size=11, fontweight='bold')
    cbar.ax.xaxis.set_tick_params(color='white', labelcolor='white', labelsize=9)
    
    world.boundary.plot(ax=ax, edgecolor='white', linewidth=0.8, alpha=0.2)
    bundeslaender.boundary.plot(ax=ax, edgecolor='white', linewidth=1.2, alpha=0.4)

    if pmsl_data is not None:
        iso = ax.contour(lons, lats, pmsl_data, levels=np.arange(900, 1100, 5), colors='white', linewidths=1.0, alpha=0.6)
        ax.clabel(iso, inline=True, fontsize=9, fmt='%d', colors='white')

    if show_numbers:
        xmin, xmax = ax.get_xlim()
        ymin, ymax = ax.get_ylim()
        try: dy = abs(lats[0, 0] - lats[-1, 0]) / max(1, lats.shape[0]) * 111.0
        except: dy = 2.2
        if dy < 0.1: dy = 2.2
            
        target_km = 12 if region == "Europa" else (5 if region == "Deutschland" else 2)
        step = max(1, int(target_km / dy))
        
        mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
        grid_mask = np.zeros_like(mask, dtype=bool)
        grid_mask[::step, ::step] = True
        final_mask = mask & grid_mask
        
        valid_lons, valid_lats, valid_data = lons[final_mask], lats[final_mask], data[final_mask]
        
        for lon_val, lat_val, val in zip(valid_lons, valid_lats, valid_data):
            if ("Niederschlag" in legend_title or "Regen" in legend_title) and val < 0.1: continue
            if "CAPE" in legend_title and val < 50: continue
            txt = f"{val:.1f}" if ("Niederschlag" in legend_title or "Regen" in legend_title) else f"{val:.0f}"
            
            ax.text(lon_val, lat_val, txt, fontsize=8, fontfamily='sans-serif', fontweight='bold', 
                    color='black', ha='center', va='center', 
                    path_effects=[path_effects.withStroke(linewidth=1.5, foreground='white')])

    ax.axis('off')
    
    # Modernes Header-Label oben links
    bbox_props = dict(boxstyle="round,pad=0.4", fc="#0E1117", ec="white", lw=0.5, alpha=0.85)
    ax.text(0.015, 0.985, f"{model_type} | {map_title_time}", transform=ax.transAxes, 
            color='white', fontsize=11, fontweight='bold', fontfamily='sans-serif', 
            ha='left', va='top', bbox=bbox_props)
    
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight', pad_inches=0.1, facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()

# --- BENUTZEROBERFLÄCHE (SEITENLEISTE) ---
st.sidebar.header("⚙️ Karteneinstellungen")
model_choice = st.sidebar.selectbox("Modell:", ["ICON-D2 (2.2km)", "ICON-EU (+120h)", "GFS (+384h)", "AIFS (+360h)"])

available_runs = get_available_runs(model_choice)
run_label = st.sidebar.selectbox("Modelllauf:", list(available_runs.keys()))
run_time = available_runs[run_label]

param_list = ["Temperatur (2m)", "Taupunkt (2m)", "Windböen 10m", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "500 hPa Geopot. Height", "850 hPa Temp.", "MLCAPE"]
if "AIFS" in model_choice: param_list = ["Temperatur (2m)", "Windböen 10m", "500 hPa Geopot. Height", "850 hPa Temp."]
param_choice = st.sidebar.selectbox("Parameter:", param_list)

# Wenn ein Parameter gewählt wird, lade gezielt seine Farb-Datei (falls noch nicht passiert)
if param_choice not in st.session_state.config: 
    st.session_state.config[param_choice] = load_param_config(param_choice)

region_options = list(REGIONS.keys())
if "D2" in model_choice: region_options.remove("Europa") 
region_choice = st.sidebar.selectbox("Region:", region_options, index=region_options.index("Deutschland") if "Deutschland" in region_options else 0)

st.sidebar.divider()
st.sidebar.subheader("🎨 Optik & Details")
show_pmsl = st.sidebar.toggle("Isobaren (Luftdruck) einblenden", value=True) if param_choice == "850 hPa Temp." else False
show_numbers = st.sidebar.toggle("Zahlenwerte auf Karte anzeigen", value=False) if param_choice in ["Temperatur (2m)", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "MLCAPE"] else False

with st.sidebar.expander(f"Farbskala anpassen"):
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
            st.session_state.config[param_choice].append({"value": 0.0, "color": "#ffffff"})
            st.rerun()
    with col_btn2:
        if st.button("💾 Speichern"): 
            save_param_config(param_choice, st.session_state.config[param_choice])

# --- HAUPTBEREICH & SCHIEBEREGLER ---
max_h = {"ICON-D2 (2.2km)": 48, "ICON-EU (+120h)": 120, "GFS (+384h)": 384, "AIFS (+360h)": 360}[model_choice]
tz_berlin = ZoneInfo("Europe/Berlin")
start_time_local = run_time.astimezone(tz_berlin)
end_time_local = start_time_local + timedelta(hours=max_h)

selected_datetime = st.slider(
    "Zeitpunkt wählen:", 
    min_value=start_time_local, 
    max_value=end_time_local, 
    value=start_time_local + timedelta(hours=min(st.session_state.f_hour, max_h)), 
    step=timedelta(hours=1), 
    format="ddd, DD.MM. - HH:mm"
)

chosen_f_hour = int((selected_datetime - start_time_local).total_seconds() / 3600)
st.session_state.f_hour = chosen_f_hour

st.markdown(f"""
    <div class="glass-banner">
        🌤️ {model_choice} | 🌡️ {param_choice}<br>
        <span style="color: #60a5fa;">Gültig für: {selected_datetime.strftime('%A, %d.%m.%Y - %H:%00')} Uhr (+{chosen_f_hour}h)</span>
    </div>
""", unsafe_allow_html=True)

config_hash = hash(str(st.session_state.config[param_choice]))
cache_key = f"{model_choice}_{run_label}_{param_choice}_{region_choice}_{chosen_f_hour}_{show_pmsl}_{show_numbers}_{config_hash}"

if cache_key in st.session_state.map_cache:
    st.image(st.session_state.map_cache[cache_key], use_container_width=True)
else:
    if st.button(f"🗺️ Karte für +{chosen_f_hour}h berechnen & anzeigen", type="primary", use_container_width=True):
        with st.spinner("Lade GRIB-Daten und rendere Karte im neuen Design..."):
            lons, lats, data, title, pmsl = load_parameter_data(run_time, chosen_f_hour, param_choice, model_choice, show_pmsl)
            if lons is not None:
                t_str = selected_datetime.strftime('%d.%m. %H:00')
                img_bytes = create_map(st.session_state.config[param_choice], lons, lats, data, f"+{chosen_f_hour}h | {t_str} Uhr", title, model_choice, region_choice, pmsl, show_numbers)
                st.session_state.map_cache[cache_key] = img_bytes
                st.rerun() 
            else:
                st.error("Ein Datensatz für diesen Parameter ist auf den Servern noch nicht verfügbar.")
