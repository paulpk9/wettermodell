import os
import json
import requests
import bz2
import tempfile
from datetime import datetime, timedelta, timezone
import xarray as xr
import numpy as np
import matplotlib
# Zwingt Matplotlib in den Server-Modus (viel schneller, da keine GUI geladen wird)
matplotlib.use('Agg') 
import matplotlib.subplots
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as path_effects
import geopandas as gpd
import shutil
import concurrent.futures

# --- EINSTELLUNGEN FÜR DEN WORKER ---
MODELS_TO_RENDER = ["ICON-D2"] 
REGIONS_TO_RENDER = ["Deutschland"]
PARAMS_TO_RENDER = ["Temperatur (2m)", "Akk. Niederschlag (mm)"]
FORECAST_HOURS = list(range(0, 49, 1))

print("🚀 Starte High-Performance Render-Worker (Multiprocessing)...")

DEFAULT_CONFIGS = {
    "Temperatur (2m)": [{"value": -10.0, "color": "#313695"}, {"value": 0.0, "color": "#74add1"}, {"value": 15.0, "color": "#fdae61"}, {"value": 30.0, "color": "#d73027"}],
    "Akk. Niederschlag (mm)": [{"value": 0.0, "color": "#ffffff"}, {"value": 1.0, "color": "#a6cee3"}, {"value": 10.0, "color": "#1f78b4"}, {"value": 30.0, "color": "#33a02c"}],
}

try:
    with open("config.json", "r") as f: config_data = json.load(f)
except Exception:
    config_data = DEFAULT_CONFIGS

# --- GRENZEN NUR EINMALIG LADEN ---
print("🌍 Lade Kartengrenzen (nur einmalig für alle Worker)...")
with tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f1, tempfile.NamedTemporaryFile(suffix=".geojson", mode="w+", delete=False) as f2:
    f1.write(requests.get("https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson").text); f1_name = f1.name
    f2.write(requests.get("https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json").text); f2_name = f2.name
world_gdf = gpd.read_file(f1_name)
bl_gdf = gpd.read_file(f2_name)
os.remove(f1_name); os.remove(f2_name)

# --- ZEIT-LOGIK ---
now = datetime.now(timezone.utc)
effective_now = now - timedelta(hours=2.5)
latest_run = effective_now.replace(hour=(effective_now.hour // 3) * 3, minute=0, second=0, microsecond=0)
run_str = f"{latest_run.hour:02d}"
date_str = latest_run.strftime("%Y%m%d")
run_label = f"{latest_run.strftime('%Y-%m-%d_%H')}Z"
print(f"🕒 Aktueller Modelllauf: {run_label}")

# --- AUFRÄUMEN ---
base_folder = "Karten"
if os.path.exists(base_folder):
    for m_folder in os.listdir(base_folder):
        m_path = os.path.join(base_folder, m_folder)
        if os.path.isdir(m_path):
            for r_folder in os.listdir(m_path):
                try:
                    folder_time = datetime.strptime(r_folder, "%Y-%m-%d_%HZ").replace(tzinfo=timezone.utc)
                    if now - folder_time > timedelta(hours=24):
                        shutil.rmtree(os.path.join(m_path, r_folder))
                except: pass

# --- DIE ARBEITER-FUNKTION (Wird parallel ausgeführt) ---
def process_single_map(args):
    hr, param, region = args
    save_path = os.path.join(base_folder, "ICON-D2", run_label, param, f"{region}_{hr:03d}.png")
    
    if os.path.exists(save_path):
        return f"⏭️ Übersprungen (existiert): {param} +{hr}h"

    # 1. Download
    dwd_map = {"Temperatur (2m)": ("t_2m", "2d_t_2m"), "Akk. Niederschlag (mm)": ("tot_prec", "2d_tot_prec")}
    if param not in dwd_map: return f"❌ Unbekannter Parameter: {param}"
    folder, var = dwd_map[param]
    
    url = f"https://opendata.dwd.de/weather/nwp/icon-d2/grib/{run_str}/{folder}/icon-d2_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hr:03d}_{var}.grib2.bz2"
    
    t_path = None
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200: return f"⚠️ GRIB nicht gefunden: {param} +{hr}h"
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.grib2') as f:
            f.write(bz2.decompress(resp.content))
            t_path = f.name
            
        ds = xr.open_dataset(t_path, engine='cfgrib')
        act_var = list(ds.data_vars)[0]
        vals = np.squeeze(ds[act_var].values)
        lats, lons = ds['latitude'].values, ds['longitude'].values
        if lons.ndim == 1: lons, lats = np.meshgrid(lons, lats)
        ds.close()
        
        if param == "Temperatur (2m)": vals -= 273.15
        
    except Exception as e:
        return f"❌ Fehler bei Download {param} +{hr}h: {e}"
    finally:
        # Absoluter Schutz vor vollem Festplattenspeicher!
        if t_path and os.path.exists(t_path): os.remove(t_path)

    # 2. Rendern
    try:
        conf = config_data.get(param, DEFAULT_CONFIGS.get(param))
        levels = [c['value'] for c in sorted(conf, key=lambda x: x['value'])]
        colors = [c['color'] for c in sorted(conf, key=lambda x: x['value'])]
        min_v, max_v = min(levels), max(levels)
        if min_v == max_v: max_v += 1
        
        norm_levels = [(v - min_v) / (max_v - min_v) for v in levels]
        cmap = mcolors.LinearSegmentedColormap.from_list("custom", list(zip(norm_levels, colors)))
        
        fig, ax = plt.subplots(figsize=(10, 10))
        fig.patch.set_facecolor('#0E1117'); ax.set_facecolor('#0E1117')
        
        if region == "Deutschland": ax.set_xlim(5.5, 15.5); ax.set_ylim(47.0, 55.0)
        
        karte = ax.contourf(lons, lats, vals, levels=np.linspace(min_v, max_v, 150), cmap=cmap, extend='both', alpha=0.95)
        
        # Zahlen rendern (mit dynamischem Raster)
        dy = abs(lats[1, 0] - lats[0, 0]) * 111.0
        if dy < 0.01: dy = 2.2
        step = max(1, int(5 / dy)) 
        
        xmin, xmax, ymin, ymax = ax.get_xlim()[0], ax.get_xlim()[1], ax.get_ylim()[0], ax.get_ylim()[1]
        mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(vals)
        grid_mask = np.zeros_like(mask, dtype=bool)
        grid_mask[::step, ::step] = True
        final_mask = mask & grid_mask
        
        valid_lons, valid_lats, valid_data = lons[final_mask], lats[final_mask], vals[final_mask]
        
        for lon_val, lat_val, val in zip(valid_lons, valid_lats, valid_data):
            if "Niederschlag" in param and val < 0.1: continue
            txt = f"{val:.1f}" if "Niederschlag" in param else f"{val:.0f}"
            ax.text(lon_val, lat_val, txt, fontsize=8, color='black', ha='center', va='center', path_effects=[path_effects.withStroke(linewidth=1.5, foreground='white')])

        world_gdf.boundary.plot(ax=ax, edgecolor='white', linewidth=0.8, alpha=0.8)
        bl_gdf.boundary.plot(ax=ax, edgecolor='white', linewidth=1.2, alpha=1.0)
        ax.axis('off')
        
        title_time = (latest_run + timedelta(hours=hr)).strftime('%d.%m. %H:00 UTC')
        ax.text(ax.get_xlim()[0] + 0.2, ax.get_ylim()[1] - 0.5, f"ICON-D2 | +{hr}h | {title_time}", color='white', fontsize=10, bbox=dict(facecolor='#0E1117', alpha=0.7, edgecolor='none'))
        
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        fig.savefig(save_path, format="png", bbox_inches='tight', pad_inches=0, facecolor='#0E1117')
        plt.close(fig) # GANZ WICHTIG: Speicher wieder freigeben!
        
        return f"✅ Gerendert: {param} +{hr}h"
    except Exception as e:
        return f"❌ Fehler beim Rendern {param} +{hr}h: {e}"

# --- MULTIPROCESSING STARTEN ---
if __name__ == '__main__':
    # Baut eine Liste mit allen Aufgaben (98 Karten)
    tasks = []
    for param in PARAMS_TO_RENDER:
        for hr in FORECAST_HOURS:
            for region in REGIONS_TO_RENDER:
                tasks.append((hr, param, region))
                
    print(f"📦 Starte Verarbeitung von {len(tasks)} Karten...")
    
    # Nutzt bis zu 4 parallele Prozesse (Download & Render gleichzeitig!)
    with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
        results = executor.map(process_single_map, tasks)
        
        for result in results:
            print(result)
            
    print("🎉 High-Performance Render-Job erfolgreich abgeschlossen!")
