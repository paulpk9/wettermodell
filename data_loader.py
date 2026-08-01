import streamlit as st
import numpy as np
import requests
import bz2
import tempfile
import os
import pandas as pd
import xarray as xr
import scipy.ndimage as ndimage
from scipy.interpolate import griddata
import io
import math
from PIL import Image
from datetime import datetime, timedelta, timezone

@st.cache_data(ttl=180, show_spinner=False)
def get_rainviewer_radar(lon_min, lon_max, lat_min, lat_max, color_scheme=2):
    try:
        resp = requests.get("https://api.rainviewer.com/public/weather-maps.json", headers={'User-Agent': 'Mozilla/5.0'}, timeout=8).json()
        host = resp.get("host", "https://tilecache.rainviewer.com")
        path = resp['radar']['past'][-1]['path']
        
        zoom = 5
        def deg2num(lat_deg, lon_deg, zoom):
            lat_rad = math.radians(lat_deg)
            n = 2.0 ** zoom
            xtile = int((lon_deg + 180.0) / 360.0 * n)
            ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
            return (xtile, ytile)

        xmin, ymin = deg2num(lat_max, lon_min, zoom) 
        xmax, ymax = deg2num(lat_min, lon_max, zoom) 

        tiles = []
        for x in range(xmin, xmax + 1):
            for y in range(ymin, ymax + 1):
                url = f"{host}{path}/256/{zoom}/{x}/{y}/{color_scheme}/1_1.png"
                r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                if r.status_code == 200:
                    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                    tiles.append({'x': x, 'y': y, 'img': img})

        if not tiles: return None, None

        def num2deg(xtile, ytile, zoom):
            n = 2.0 ** zoom
            lon_deg = xtile / n * 360.0 - 180.0
            lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * ytile / n)))
            lat_deg = math.degrees(lat_rad)
            return (lat_deg, lon_deg)

        stitch_xmin_deg = num2deg(xmin, ymax+1, zoom)[1]
        stitch_xmax_deg = num2deg(xmax+1, ymax+1, zoom)[1]
        stitch_ymin_deg = num2deg(xmax+1, ymax+1, zoom)[0]
        stitch_ymax_deg = num2deg(xmin, ymin, zoom)[0]

        tile_w = 256
        stitched = Image.new("RGBA", ((xmax - xmin + 1) * tile_w, (ymax - ymin + 1) * tile_w), (0,0,0,0))
        for t in tiles:
            stitched.paste(t['img'], ((t['x'] - xmin) * tile_w, (t['y'] - ymin) * tile_w))

        return np.array(stitched), [stitch_xmin_deg, stitch_xmax_deg, stitch_ymin_deg, stitch_ymax_deg]
    except: return None, None

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
    if "AI-Blend" in model_name: step, delay = 6, 5.5
    elif "EPS" in model_name: step, delay = 3, 3.5
    elif "GFS" in model_name: step, delay = 6, 5.5
    elif "EU" in model_name: step, delay = 6, 3.5
    elif "Global" in model_name: step, delay = 6, 4.0
    else: step, delay = 3, 2.5
    eff_now = now - timedelta(hours=delay)
    latest = eff_now.replace(hour=(eff_now.hour // step) * step, minute=0, second=0, microsecond=0)
    return {f"Lauf: { (latest - timedelta(hours=i*step)).strftime('%d.%m.%Y | %H:02d') }Z": (latest - timedelta(hours=i*step)) for i in range(6)}

@st.cache_data(ttl=3600, show_spinner=False)
def download_and_extract(url, is_bz2=False, param_name=None, eps_member=None):
    if not url: return None, None, None
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=10)
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
    if param_name in ["CAPE & CIN (Deckel)", "Scherung 0-1 km", "Scherung 0-6 km", "SCP-Index", "Chaser Target-Index", "Blanko / Nur Basiskarte", "Windgeschw. Mittel 10m"]: return None, None, None

    if "GFS" in model:
        vm = {
            "Temperatur (2m)": "var_TMP=on&lev_2_m_above_ground=on", "Akk. Niederschlag (mm)": "var_APCP=on&lev_surface=on", 
            "Windböen 10m": "var_GUST=on&lev_surface=on", "Niederschlagsrate (mm/h)": "var_PRATE=on&lev_surface=on",
            "MLCAPE": "var_CAPE=on&lev_surface=on", "CIN": "var_CIN=on&lev_surface=on", "Luftdruck (hPa)": "var_PRMSL=on&lev_mean_sea_level=on",
            "Gesamtbewölkung (%)": "var_TCDC=on&lev_entire_atmosphere=on", "PWAT (mm)": "var_PWAT=on&lev_entire_atmosphere=on",
            "Taupunkt (2m)": "var_DPT=on&lev_2_m_above_ground=on", "Sichtweite (m)": "var_VIS=on&lev_surface=on",
            "Nullgradgrenze (m)": "var_HGT=on&lev_0C_isotherm=on", "Tiefe Wolken (%)": "var_LCDC=on&lev_low_cloud_layer=on",
            "Sonneneinstrahlung (W/m²)": "var_DSWRF=on&lev_surface=on", "Relative Luftfeuchte 2m (%)": "var_RH=on&lev_2_m_above_ground=on",
            "Schneehöhe (cm)": "var_SNOD=on&lev_surface=on"
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
        "Luftdruck (hPa)": ("pmsl", "pmsl", None), "Signifikantes Wetter": ("ww", "ww", None),
        "Gesamtbewölkung (%)": ("clct", "clct", None), "PWAT (mm)": ("tqv", "tqv", None),
        "Radarreflektivität (dBZ)": ("dbz_cmax", "dbz_cmax", None), "Blitzrate (LPI)": ("lpi_max", "lpi_max", None),
        "U-Wind 10m": ("u_10m", "u_10m", None), "V-Wind 10m": ("v_10m", "v_10m", None),
        "U-Wind 850hPa": ("u", "u", "850"), "V-Wind 850hPa": ("v", "v", "850"),
        "U-Wind 500hPa": ("u", "u", "500"), "V-Wind 500hPa": ("v", "v", "500"),
        "Taupunkt (2m)": ("td_2m", "td_2m", None), "Sichtweite (m)": ("vis", "vis", None),
        "Nullgradgrenze (m)": ("hzerocl", "hzerocl", None), "Tiefe Wolken (%)": ("clcl", "clcl", None),
        "Sonneneinstrahlung (W/m²)": ("aswdir_s", "aswdir_s", None), "Relative Luftfeuchte 2m (%)": ("relhum_2m", "relhum_2m", None),
        "Schneehöhe (cm)": ("h_snow", "h_snow", None)
    }
        
    if param_name not in dm: return None, None, None
    fld, var, lvl = dm[param_name]
    
    urls_to_try = []
    if "D2" in model:
        m_str = "icon-d2-eps" if "EPS" in model else "icon-d2"
        base = f"https://opendata.dwd.de/weather/nwp/{m_str}/grib/{run_str}/{fld}/"
        if lvl:
            prefix = f"{m_str}_germany_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_"
            urls_to_try.extend([base + prefix + f"{var.upper()}.grib2.bz2", base + prefix + f"{var}.grib2.bz2"])
        else:
            prefix = f"{m_str}_germany_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_"
            urls_to_try.extend([
                base + prefix + f"{var}.grib2.bz2",
                base + prefix + f"2d_{var}.grib2.bz2",
                base + prefix + f"{var.replace('2d_', '')}.grib2.bz2"
            ])
    elif "EU" in model or "Global" in model:
        m_str = "icon-eu-eps" if "EPS" in model else ("icon-global" if "Global" in model else "icon-eu")
        base = f"https://opendata.dwd.de/weather/nwp/{m_str}/grib/{run_str}/{fld}/"
        if lvl:
            prefix = f"{m_str}_europe_regular-lat-lon_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_" if "EU" in model else f"{m_str}_icosahedral_pressure-level_{date_str}{run_str}_{hour_str}_{lvl}_"
            urls_to_try.append(base + prefix + f"{var.upper()}.grib2.bz2")
        else:
            prefix = f"{m_str}_europe_regular-lat-lon_single-level_{date_str}{run_str}_{hour_str}_" if "EU" in model else f"{m_str}_icosahedral_single-level_{date_str}{run_str}_{hour_str}_"
            urls_to_try.extend([base + prefix + f"{var.upper()}.grib2.bz2", base + prefix + f"{var.replace('2d_', '').upper()}.grib2.bz2"])
            
    for u in urls_to_try:
        res = download_and_extract(u, is_bz2=True, param_name=param_name, eps_member=eps_choice)
        if res[0] is not None:
            return res
        
    return None, None, None

def load_parameter_data(run_time, forecast_hour, param_name, model_type, overlays, eps_choice=None):
    if "Live-Radar" in model_type:
        return np.zeros((2,2)), np.zeros((2,2)), None, "Live Regenradar (Rainviewer)", None, None

    if "AI-Blend" in model_type:
        lg, lag, vg, tg, pg, eg = load_parameter_data(run_time, forecast_hour, param_name, "GFS (+384h)", overlays, eps_choice)
        li, lai, vi, ti, pi, ei = load_parameter_data(run_time, forecast_hour, param_name, "ICON-Global (+120h)", overlays, eps_choice)
        
        if vg is None: return None, None, None, "", None, None
        
        if vi is not None:
            points = np.column_stack((lg.flatten(), lag.flatten()))
            vg_interp = griddata(points, vg.flatten(), (li, lai), method='nearest')
            v_aifs = ndimage.gaussian_filter(vg_interp, sigma=2.0)
            v_aicon = ndimage.gaussian_filter(vi, sigma=2.0)
            blend_val = (vg_interp * 0.20) + (vi * 0.20) + (v_aifs * 0.30) + (v_aicon * 0.30)
            
            pmsl_blend = None
            if pg is not None and pi is not None:
                pg_interp = griddata(points, pg.flatten(), (li, lai), method='nearest')
                p_aifs = ndimage.gaussian_filter(pg_interp, sigma=2.0)
                p_aicon = ndimage.gaussian_filter(pi, sigma=2.0)
                pmsl_blend = (pg_interp * 0.20) + (pi * 0.20) + (p_aifs * 0.30) + (p_aicon * 0.30)
                
            ex_blend = None
            if eg is not None and ei is not None:
                eg_interp = griddata(points, eg.flatten(), (li, lai), method='nearest')
                e_aifs = ndimage.gaussian_filter(eg_interp, sigma=2.0)
                e_aicon = ndimage.gaussian_filter(ei, sigma=2.0)
                ex_blend = (eg_interp * 0.20) + (ei * 0.20) + (e_aifs * 0.30) + (e_aicon * 0.30)

            lons_out, lats_out = li, lai
            title_out = f"[AI-Blend] {tg}"
        else:
            v_aifs = ndimage.gaussian_filter(vg, sigma=2.0)
            blend_val = (vg * 0.5) + (v_aifs * 0.5)
            
            pmsl_blend = None
            if pg is not None: pmsl_blend = (pg * 0.5) + (ndimage.gaussian_filter(pg, sigma=2.0) * 0.5)
            
            ex_blend = None
            if eg is not None: ex_blend = (eg * 0.5) + (ndimage.gaussian_filter(eg, sigma=2.0) * 0.5)
            
            lons_out, lats_out = lg, lag
            title_out = f"[AI-Blend Fallback] {tg}"
        
        if "Niederschlag" in param_name or "Radar" in param_name or "PWAT" in param_name or "LPI" in param_name or "Bewölkung" in param_name or "Schnee" in param_name:
            blend_val = np.clip(blend_val, 0, None)
            
        if "Signifikantes" in param_name:
            blend_val = np.round(blend_val)
            
        return lons_out, lats_out, blend_val, title_out, pmsl_blend, ex_blend

    if param_name == "Blanko / Nur Basiskarte":
        res_t = get_raw_grib(run_time, forecast_hour, model_type, "Temperatur (2m)", eps_choice)
        if res_t[0] is not None:
            lons, lats = res_t[0], res_t[1]
        else:
            lons, lats = np.meshgrid(np.linspace(2.5, 17.5, 50), np.linspace(47.0, 55.0, 50))
        return lons, lats, np.full_like(lons, np.nan), "Basiskarte (ohne Daten)", None, None

    pmsl_data, extra_overlay = None, None
    
    if param_name == "Windgeschw. Mittel 10m":
        res_u10 = get_raw_grib(run_time, forecast_hour, model_type, "U-Wind 10m", eps_choice)
        res_v10 = get_raw_grib(run_time, forecast_hour, model_type, "V-Wind 10m", eps_choice)
        if res_u10[2] is None: return None, None, None, "", None, None
        u10 = np.squeeze(res_u10[2][0] if isinstance(res_u10[2], tuple) else res_u10[2])
        v10 = np.squeeze(res_v10[2][0] if isinstance(res_v10[2], tuple) else res_v10[2])
        wind_mag = np.sqrt(u10**2 + v10**2) * 3.6
        return res_u10[0], res_u10[1], wind_mag, "Windgeschw. Mittel 10m (km/h)", None, None

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
        if res_c[2] is not None:
            cloud_vals = res_c[2]
            extra_overlay = np.squeeze(cloud_vals[0] if isinstance(cloud_vals, tuple) else cloud_vals)

    title = ""
    if "Temp" in param_name or "Taupunkt" in param_name: vals -= 273.15; title = f"{param_name.split(' ')[0]} in °C"
    elif "Windböen" in param_name: vals *= 3.6; title = "Windböen in km/h"
    elif param_name == "Akk. Niederschlag (mm)": title = "Niederschlag in mm"
    elif param_name == "Gesamtbewölkung" in param_name: title = "Gesamtbewölkung in %"
    elif param_name == "Tiefe Wolken (%)": title = "Tiefe Wolken in %"
    elif param_name == "Sichtweite (m)": title = "Sichtweite in m"
    elif param_name == "Nullgradgrenze (m)": title = "Nullgradgrenze in m"
    elif param_name == "Schneehöhe (cm)": 
        vals = vals * 100.0 
        title = "Schneehöhe in cm"
    elif param_name == "Luftdruck (hPa)": vals = vals / 100.0; title = "Luftdruck in hPa"
    elif param_name == "Relative Luftfeuchte 2m (%)": title = "Relative Luftfeuchte in %"
    elif param_name == "Sonneneinstrahlung (W/m²)": title = "Sonneneinstrahlung (W/m²)"
    elif param_name == "PWAT" in param_name: title = "PWAT in mm"
    elif param_name == "Radarreflektivität" in param_name: title = "Reflektivität in dBZ"
    elif param_name == "Blitzrate" in param_name: title = "LPI (Blitzpotenzial)"
    elif param_name == "Niederschlagsrate (mm/h)":
        if forecast_hour > 0:
            res_v1 = get_raw_grib(run_time, forecast_hour - 1, model_type, "Akk. Niederschlag (mm)", eps_choice)
            if res_v1[0] is not None and res_v1[2] is not None:
                v1 = res_v1[2]
                if isinstance(v1, tuple): v1 = v1[0]
                vals = np.clip(vals - v1, 0, None)
            else:
                vals = np.zeros_like(vals)
        else: 
            vals = np.zeros_like(vals)
        title = "Regenrate in mm/h"
    elif "Geopot" in param_name: vals = vals / 9.80665 / 10.0; title = "Geopotential (gpdm)"
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
