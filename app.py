import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import geopandas as gpd
from github import Github
import json

# --- SEITEN-LAYOUT ---
st.set_page_config(page_title="Modellkarten-Generator", page_icon="🗺️", layout="wide")
st.title("🗺️ Statische Modellkarte (Profi-Ansicht)")

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
def load_config():
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            g = Github(st.secrets["GITHUB_TOKEN"])
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file = repo.get_contents("config.json")
            return json.loads(file.decoded_content.decode())
        except Exception as e:
            st.warning("Keine config.json gefunden oder Fehler beim Laden. Nutze Standardwerte.")
    else:
        st.info("GitHub-Secrets nicht gefunden. Speichern läuft vorerst nur lokal in dieser Sitzung.")
    return DEFAULT_CONFIG

def save_config(config_data):
    if "GITHUB_TOKEN" in st.secrets and "GITHUB_REPO" in st.secrets:
        try:
            g = Github(st.secrets["GITHUB_TOKEN"])
            repo = g.get_repo(st.secrets["GITHUB_REPO"])
            file_path = "config.json"
            content = json.dumps(config_data, indent=4)
            
            try:
                # Prüfen, ob die Datei schon existiert, dann updaten
                file = repo.get_contents(file_path)
                repo.update_file(file_path, "Update Farbskala (via Streamlit)", content, file.sha)
            except:
                # Andernfalls neu anlegen
                repo.create_file(file_path, "Create config.json", content)
            
            st.success("Erfolgreich auf GitHub gespeichert!")
        except Exception as e:
            st.error(f"Fehler beim Speichern: {e}")
    else:
        st.error("Bitte richte die GitHub Secrets in Streamlit ein, um dauerhaft zu speichern.")

# Lade Konfiguration in den Zwischenspeicher (Session State)
if "config" not in st.session_state:
    st.session_state.config = load_config()

# --- DATEN LADEN (Cache) ---
@st.cache_data
def load_borders():
    # Weltweite Grenzen (für die Nachbarländer)
    world_url = "https://raw.githubusercontent.com/datasets/geo-countries/master/data/countries.geojson"
    world = gpd.read_file(world_url)
    
    # Detaillierte deutsche Bundesländer
    bl_url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    bundeslaender = gpd.read_file(bl_url)
    
    return world, bundeslaender

# --- KARTE ZEICHNEN ---
def create_map(config_data):
    world, bundeslaender = load_borders()
    
    # 1. Raster erzeugen
    lons = np.linspace(5.0, 16.0, 200)
    lats = np.linspace(46.5, 56.0, 200)
    Lons, Lats = np.meshgrid(lons, lats)
    
    # 2. Fiktives Temperatur-Modell
    Temp = 25 - (Lats - 46.5) * 2 + np.sin(Lons * 4) * 2 + np.cos(Lats * 3) * 1.5

    # 3. Farbskala aus der Konfiguration generieren
    sorted_conf = sorted(config_data, key=lambda x: x['value'])
    levels = [c['value'] for c in sorted_conf]
    colors = [c['color'] for c in sorted_conf]
    
    bg_color = '#0E1117'
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    # Diskrete Farbskala aufbauen (nur wenn mehr als 1 Wert existiert)
    if len(levels) > 1:
        # Die Konturen zeichnen
        karte = ax.contourf(Lons, Lats, Temp, levels=levels, colors=colors[:-1], extend='both', alpha=0.9)
        
        cbar = fig.colorbar(karte, ax=ax, fraction=0.046, pad=0.04)
        cbar.set_label('Temperatur in °C', color='white', size=12)
        cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')

    # 4. Grenzen zeichnen
    # Nachbarländer im Hintergrund (Grau, dünner)
    world.boundary.plot(ax=ax, edgecolor='#666666', linewidth=0.8, alpha=0.8)
    
    # Bundesländer im Vordergrund (Weiß, dicker)
    bundeslaender.boundary.plot(ax=ax, edgecolor='#ffffff', linewidth=1.5, alpha=1.0)
    
    # 5. Fokus auf Deutschland und Ränder verstecken
    ax.set_xlim(5.5, 15.5)
    ax.set_ylim(47.0, 55.5)
    ax.axis('off')
    
    return fig


# --- BENUTZEROBERFLÄCHE (UI) ---
st.sidebar.header("⚙️ Karteneinstellungen")
st.sidebar.write("Definiere deine eigenen Schwellenwerte und Farben:")

# Dynamische Liste für die Werte und Farben aufbauen
new_config = []
for i, item in enumerate(st.session_state.config):
    col1, col2, col3 = st.sidebar.columns([2, 2, 1])
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

# Buttons für die Steuerung
col_add, col_save = st.sidebar.columns(2)
with col_add:
    if st.button("➕ Neuer Wert"):
        st.session_state.config.append({"value": 0.0, "color": "#ffffff"})
        st.rerun()
with col_save:
    if st.button("💾 Speichern"):
        with st.spinner("Speichere auf GitHub..."):
            save_config(st.session_state.config)

st.sidebar.divider()

# Karten-Generierung
if st.button("🚀 Karte rendern", type="primary"):
    with st.spinner("Lade Geodaten und rendere Grafik..."):
        fertige_grafik = create_map(st.session_state.config)
        st.pyplot(fertige_grafik)
        st.success("Karte erfolgreich generiert!")
