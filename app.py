import streamlit as st
import numpy as np
import geopandas as gpd
from github import Github, Auth
import json
import requests
import tempfile
import uuid
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# --- EIGENE MODULE IMPORTIEREN ---
from config import DEFAULT_DESIGN, SIG_WETTER_LABELS, DEFAULT_CONFIGS, REGIONS, GERMAN_CITIES
from data_loader import get_available_runs, load_parameter_data, fetch_ensemble_data, get_rainviewer_radar
from renderer import create_map

# --- SEITEN-LAYOUT & CSS ---
st.set_page_config(page_title="Profi-Wetterterminal", page_icon="🌤️", layout="wide")

st.markdown("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;800&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif !important; }
        img { border-radius: 16px; box-shadow: 0 10px 30px rgba(0, 0, 0, 0.4); transition: all 0.3s ease; }
        
        .glass-banner {
            background: linear-gradient(135deg, rgba(255,255,255,0.08) 0%, rgba(255,255,255,0.02) 100%);
            backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.15); border-radius: 16px; padding: 20px 30px;
            text-align: center; font-size: 1.3em; font-weight: 600; margin-bottom: 25px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3); letter-spacing: 0.5px;
        }
        
        .stSlider > div > div > div { background: linear-gradient(90deg, #3b82f6 0%, #8b5cf6 100%); }
        [data-testid="stColorPicker"] input { display: none !important; }
        
        /* Mobile-Friendly Buttons in der Sidebar */
        div.stRadio > div[role="radiogroup"] > label {
            background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255,255,255,0.1);
            padding: 10px 15px; border-radius: 8px; margin-bottom: 4px; transition: 0.2s;
            cursor: pointer;
        }
        div.stRadio > div[role="radiogroup"] > label:hover { background: rgba(255, 255, 255, 0.1); }
    </style>
""", unsafe_allow_html=True)

st.title("🗺️ Statische Modellkarte (Profi-Terminal)")

# --- GITHUB CLIENT & DESIGN LOGIK ---
def get_github_client(): return Github(auth=Auth.Token(st.secrets["GITHUB_TOKEN"])) if "GITHUB_TOKEN" in st.secrets else None

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

# --- SYSTEM STATES ---
if "map_cache" not in st.session_state: st.session_state.map_cache = {}
if "f_hour" not in st.session_state: st.session_state.f_hour = 0
if "config" not in st.session_state: st.session_state.config = {}
if "design" not in st.session_state: st.session_state.design = load_design_config()

if "model_choice" not in st.session_state: st.session_state.model_choice = "AI-Blend (GFS 20%, ICON 20%, AIFS 30%, AICON 30%) (+168h)"
if "param_choice" not in st.session_state: st.session_state.param_choice = "Temperatur (2m)"
if "region_choice" not in st.session_state: st.session_state.region_choice = "Deutschland"
if "eps_choice" not in st.session_state: st.session_state.eps_choice = "Ensemble-Mittel"
if "radar_color" not in st.session_state: st.session_state.radar_color = 2

world_gdf, bundeslaender_gdf = load_borders()

# --- BENUTZEROBERFLÄCHE (SEITENLEISTE MIT TABS) ---
st.sidebar.header("⚙️ Terminal-Steuerung")
tab_main, tab_overlays, tab_design = st.sidebar.tabs(["⚙️ Basis", "🔣 Overlays", "🎨 Design"])

with tab_main:
    # NEU: Das fehlerhafte ICON-D2-RUC Modell wurde restlos entfernt.
    model_options = ["AI-Blend (GFS 20%, ICON 20%, AIFS 30%, AICON 30%) (+168h)", "Live-Radar (Rainviewer)", "ICON-D2 (2.2km)", "ICON-D2-EPS (+48h)", "ICON-EU (+120h)", "ICON-EU-EPS (+120h)", "ICON-Global (+120h)", "GFS (+384h)"]
    st.session_state.model_choice = st.radio("🌍 Modell:", model_options, index=model_options.index(st.session_state.model_choice) if st.session_state.model_choice in model_options else 2)
    
    model_choice = st.session_state.model_choice
    
    if "Live-Radar" not in model_choice:
        st.divider()
        available_runs = get_available_runs(model_choice)
        run_label = st.radio("🕒 Modelllauf:", list(available_runs.keys()))
        run_time = available_runs[run_label]
        
        eps_choice = None
        if "EPS" in model_choice:
            st.divider()
            eps_members = ["Ensemble-Mittel"] + [f"Member {i}" for i in range(1, 21 if "D2" in model_choice else 41)]
            st.session_state.eps_choice = st.radio("🔀 Member:", eps_members, index=eps_members.index(st.session_state.eps_choice) if st.session_state.eps_choice in eps_members else 0)
            eps_choice = st.session_state.eps_choice
        
        st.divider()
        base_params = ["Temperatur (2m)", "Taupunkt (2m)", "Relative Luftfeuchte 2m (%)", "Windböen 10m", "Windgeschw. Mittel 10m", "Luftdruck (hPa)", "Gesamtbewölkung (%)", "PWAT (mm)", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "Schneehöhe (cm)", "500 hPa Geopot. Height", "850 hPa Temp.", "MLCAPE", "CIN", "CAPE & CIN (Deckel)", "Blanko / Nur Basiskarte"]
        
        if "D2" in model_choice or "AI-Blend" in model_choice:
            param_list = base_params + ["Signifikantes Wetter", "Radarreflektivität (dBZ)", "Blitzrate (LPI)", "Tiefe Wolken (%)", "Sichtweite (m)", "Sonneneinstrahlung (W/m²)", "Scherung 0-1 km", "Scherung 0-6 km", "SCP-Index", "Chaser Target-Index"]
        elif "EU" in model_choice or "Global" in model_choice:
            param_list = base_params + ["Signifikantes Wetter", "Tiefe Wolken (%)", "Sichtweite (m)", "Sonneneinstrahlung (W/m²)", "Scherung 0-1 km", "Scherung 0-6 km", "SCP-Index", "Chaser Target-Index"]
        elif "GFS" in model_choice:
            param_list = base_params + ["Tiefe Wolken (%)", "Sichtweite (m)", "Sonneneinstrahlung (W/m²)"]
        else:
            param_list = base_params

        if st.session_state.param_choice not in param_list:
            st.session_state.param_choice = param_list[0]

        st.session_state.param_choice = st.radio("🌡️ Parameter:", param_list, index=param_list.index(st.session_state.param_choice))
        param_choice = st.session_state.param_choice
        
        if param_choice not in st.session_state.config and param_choice != "Blanko / Nur Basiskarte": 
            st.session_state.config[param_choice] = load_param_config(param_choice)
    else:
        st.info("Rainviewer Live-Radar aktiv. Zeit- & Parameterauswahl deaktiviert.")
        rv_colors = {1: "Original", 2: "Universal Blue", 3: "TITAN", 4: "The Weather Channel", 5: "Meteored", 6: "NEXRAD Level-III", 7: "Rainbow", 8: "Dark Sky"}
        st.session_state.radar_color = st.radio("🎨 Radar Farbschema:", list(rv_colors.keys()), index=1, format_func=lambda x: rv_colors[x])
        run_time = datetime.now(timezone.utc)
        param_choice = "Radarreflektivität (Live)"
        eps_choice = None
        
    st.divider()
    region_options = list(REGIONS.keys())
    if "D2" in model_choice or "Live" in model_choice:
        if "Europa" in region_options: region_options.remove("Europa") 
    if st.session_state.region_choice not in region_options: st.session_state.region_choice = "Deutschland"
    
    st.session_state.region_choice = st.radio("📍 Region:", region_options, index=region_options.index(st.session_state.region_choice))
    region_choice = st.session_state.region_choice
    
    run_to_run = False
    if "Live-Radar" not in model_choice:
        st.divider()
        run_to_run = st.toggle("🔄 Run-to-Run Shift (zum Vorlauf)", value=False)

with tab_overlays:
    st.info("Kombiniere mehrere Karten-Layer:")
    show_cities = st.toggle("🏙️ Wichtige Städte anzeigen", value=True) if region_choice == "Deutschland" else False
    show_pmsl = st.toggle("💨 Isobaren (Luftdruck)", value=True) if param_choice == "850 hPa Temp." else False
    
    show_numbers = False
    if param_choice in ["Temperatur (2m)", "Taupunkt (2m)", "Windböen 10m", "Akk. Niederschlag (mm)", "Niederschlagsrate (mm/h)", "Schneehöhe (cm)"]:
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

    if "Live-Radar" not in model_choice and param_choice != "Blanko / Nur Basiskarte":
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
    max_h = 0 if "Live" in model_choice else (168 if "AI-Blend" in model_choice else (384 if "GFS" in model_choice else (120 if "EU" in model_choice or "Global" in model_choice else (48 if "EPS" in model_choice else 48))))
    step_h = 3 if "GFS" in model_choice or "AI-Blend" in model_choice else 1
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

    config_hash = hash(str(st.session_state.config.get(param_choice)) + str(st.session_state.design) + str(show_cities) + str(show_clouds) + str(show_numbers) + (str(eps_choice) if not "Live" in model_choice else "") + str(run_to_run) + str(st.session_state.get('radar_color', 2)))
    cache_key = f"{model_choice}_{run_time.strftime('%Y%m%d%H') if not 'Live' in model_choice else 'live'}_{param_choice}_{region_choice}_{chosen_f_hour}_{show_pmsl}_{config_hash}"

    if cache_key in st.session_state.map_cache:
        st.image(st.session_state.map_cache[cache_key]["image"])
        if st.session_state.map_cache[cache_key].get("extremes"):
            st.info(f"**Extremwerte (Deutschland):** {st.session_state.map_cache[cache_key]['extremes']}")
    else:
        btn_label = "🗺️ Rainviewer-Radar laden" if "Live" in model_choice else f"🗺️ Karte für +{chosen_f_hour}h berechnen & anzeigen"
        if st.button(btn_label, type="primary", width="stretch"):
            with st.spinner("Lade Daten und rendere Karte..."):
                if "Live-Radar" in model_choice:
                    color_scheme = st.session_state.get('radar_color', 2)
                    radar_img, r_extent = get_rainviewer_radar(REGIONS[region_choice][0], REGIONS[region_choice][1], REGIONS[region_choice][2], REGIONS[region_choice][3], color_scheme)
                    img_bytes = create_map([], None, None, None, f"Aktuell | {selected_datetime.strftime('%d.%m. %H:%M')} Uhr", "", model_choice, region_choice, {"cities": show_cities}, st.session_state.design, world_gdf, bundeslaender_gdf, radar_img, r_extent)
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
                                img_bytes = create_map(r2r_config, lons, lats, data, f"+{chosen_f_hour}h | {selected_datetime.strftime('%d.%m. %H:00')} Uhr", title, model_choice, region_choice, overlays_dict, st.session_state.design, world_gdf, bundeslaender_gdf)
                                st.session_state.map_cache[cache_key] = {"image": img_bytes, "extremes": None}
                                st.rerun()
                            else:
                                st.error("Daten für den Vorlauf auf dem Server nicht verfügbar.")
                    else:
                        lons, lats, data, title, pmsl, extra_overlay = load_parameter_data(run_time, chosen_f_hour, param_choice, model_choice, overlays_dict, eps_choice)
                        
                        if lons is not None:
                            extremes_txt = None
                            if region_choice == "Deutschland" and "Signifikantes Wetter" not in param_choice and param_choice != "Blanko / Nur Basiskarte":
                                xmin, xmax, ymin, ymax = REGIONS["Deutschland"]
                                mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
                                if np.any(mask):
                                    unit = title.split("in ")[-1] if "in " in title else title.split("(")[-1].replace(")", "")
                                    extremes_txt = f"Min: {np.nanmin(data[mask]):.1f} {unit} | Max: {np.nanmax(data[mask]):.1f} {unit}"

                            overlays_dict['pmsl_data'], overlays_dict['extra_data'] = pmsl, extra_overlay
                            t_str = selected_datetime.strftime('%d.%m. %H:00')
                            img_bytes = create_map(st.session_state.config.get(param_choice, []), lons, lats, data, f"+{chosen_f_hour}h | {t_str} Uhr", title, model_choice, region_choice, overlays_dict, st.session_state.design, world_gdf, bundeslaender_gdf)
                            
                            st.session_state.map_cache[cache_key] = {"image": img_bytes, "extremes": extremes_txt}
                            st.rerun() 
                        else:
                            st.error(f"Ein Datensatz für diesen Parameter (+{chosen_f_hour}h) ist auf den Servern für diesen Modelllauf noch nicht verfügbar.")

    if not "Live" in model_choice:
        st.divider()
        if st.button("🔄 Alle Karten vorladen (Zwischenspeicher)", width="stretch"):
            progress_bar = st.progress(0.0)
            status_text = st.empty()
            
            hours_to_load = list(range(0, max_h + 1, step_h))
            total_hours = len(hours_to_load)
            
            overlays_dict = {"pmsl": show_pmsl, "numbers": show_numbers, "cities": show_cities, "clouds": show_clouds, "eps_choice": eps_choice}
            
            for i, fh in enumerate(hours_to_load):
                status_text.text(f"Lade Karte +{fh}h ({i+1}/{total_hours}) in den Cache...")
                
                c_hash = hash(str(st.session_state.config.get(param_choice)) + str(st.session_state.design) + str(show_cities) + str(show_clouds) + str(show_numbers) + (str(eps_choice) if not "Live" in model_choice else "") + str(run_to_run))
                c_key = f"{model_choice}_{run_time.strftime('%Y%m%d%H')}_{param_choice}_{region_choice}_{fh}_{show_pmsl}_{c_hash}"
                
                if c_key not in st.session_state.map_cache:
                    lons, lats, data, title, pmsl, extra_overlay = load_parameter_data(run_time, fh, param_choice, model_choice, overlays_dict, eps_choice)
                    if lons is not None:
                        extremes_txt = None
                        if region_choice == "Deutschland" and "Signifikantes Wetter" not in param_choice and param_choice != "Blanko / Nur Basiskarte":
                            xmin, xmax, ymin, ymax = REGIONS["Deutschland"]
                            mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
                            if np.any(mask):
                                unit = title.split("in ")[-1] if "in " in title else title.split("(")[-1].replace(")", "")
                                extremes_txt = f"Min: {np.nanmin(data[mask]):.1f} {unit} | Max: {np.nanmax(data[mask]):.1f} {unit}"
                        
                        overlays_dict_pass = overlays_dict.copy()
                        overlays_dict_pass['pmsl_data'] = pmsl
                        overlays_dict_pass['extra_data'] = extra_overlay
                        
                        t_str = (start_time_local + timedelta(hours=fh)).strftime('%d.%m. %H:00')
                        img_bytes = create_map(st.session_state.config.get(param_choice, []), lons, lats, data, f"+{fh}h | {t_str} Uhr", title, model_choice, region_choice, overlays_dict_pass, st.session_state.design, world_gdf, bundeslaender_gdf)
                        
                        st.session_state.map_cache[c_key] = {"image": img_bytes, "extremes": extremes_txt}
                
                progress_bar.progress((i + 1) / total_hours)
                
            status_text.text("✅ Alle Karten erfolgreich geladen! Du kannst nun verzögerungsfrei durchscrollen.")

with tab_ens:
    st.markdown("### 📈 Profi-Ensemble Prognose (Punktabfrage)")
    st.info("Hinweis: Da Ensemble-Berechnungen tausende Gigabyte erfordern, wird diese Ansicht ressourcenschonend direkt aus der Open-Meteo API generiert.")
    
    col_e1, col_e2, col_e3 = st.columns(3)
    
    with col_e1: ens_city = st.selectbox("Ort:", list(GERMAN_CITIES.keys()))
    with col_e2: ens_model = st.selectbox("Modell-Ensemble:", ["ICON-EPS (DWD)", "ICON-D2-EPS (DWD)", "GFS-ENS (NOAA)", "ECMWF-EPS"])
    with col_e3: ens_param = st.selectbox("Wetter-Parameter:", ["Temperatur (2m)", "850 hPa Temp.", "Niederschlag (mm/h)", "Windböen (km/h)", "CAPE (J/kg)"])
    
    om_model_map = {"ICON-EPS (DWD)": "icon_seamless", "ICON-D2-EPS (DWD)": "icon_d2", "GFS-ENS (NOAA)": "gfs_seamless", "ECMWF-EPS": "ecmwf_ensemble"}
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
