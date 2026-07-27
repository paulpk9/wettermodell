import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import geopandas as gpd

# Seiten-Layout
st.set_page_config(page_title="Modellkarten-Generator", page_icon="🗺️", layout="wide")

st.title("🗺️ Statische Modellkarte (Darkmode & Grenzen)")
st.write("Jetzt mit echten Bundesland-Grenzen und modernem Darkmode-Design.")

# --- DATEN LADEN (mit Cache, damit es schnell geht) ---
@st.cache_data
def load_borders():
    # Lädt eine offene, leichte GeoJSON-Datei mit den deutschen Bundesländern
    url = "https://raw.githubusercontent.com/isellsoap/deutschlandGeoJSON/main/2_bundeslaender/4_niedrig.geo.json"
    return gpd.read_file(url)

# --- ZEICHNEN DER KARTE ---
def create_dark_map():
    # 1. Grenzen laden
    borders = load_borders()
    
    # 2. Koordinaten-Gitter für Deutschland (etwas größer gefasst)
    lons = np.linspace(5.5, 15.5, 150)
    lats = np.linspace(47.0, 55.5, 150)
    Lons, Lats = np.meshgrid(lons, lats)
    
    # 3. Fiktive Daten generieren (mit etwas komplexeren "Wellen" für eine echte Optik)
    Temp = 25 - (Lats - 47.0) * 2 + np.sin(Lons * 4) * 2 + np.cos(Lats * 3) * 1.5

    # 4. Karte einrichten (Darkmode)
    # Farbe #0E1117 ist exakt der Hintergrund-Farbton des Streamlit Darkmodes
    bg_color = '#0E1117'
    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)
    
    # 5. Temperatur-Felder plotten
    # 'magma' sieht im Darkmode extrem gut und modern aus. alpha=0.85 macht es leicht transparent.
    karte = ax.contourf(Lons, Lats, Temp, levels=25, cmap='magma', alpha=0.85)
    
    # 6. Bundesländer darüberlegen
    # Wir zeichnen nur die Ränder (boundary) in strahlendem Weiß
    borders.boundary.plot(ax=ax, edgecolor='#ffffff', linewidth=1.2, alpha=0.9)
    
    # 7. Ansicht auf Deutschland zuschneiden und Rahmen ausblenden
    ax.set_xlim(5.5, 15.5)
    ax.set_ylim(47.0, 55.5)
    ax.axis('off') # Versteckt die X/Y Achsen für einen reinen "Karten"-Look
    
    # 8. Die Farbskala (Legende) anpassen (auch im Darkmode-Stil)
    cbar = fig.colorbar(karte, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label('Temperatur in °C', color='white', size=12)
    cbar.ax.yaxis.set_tick_params(color='white', labelcolor='white')
    
    return fig

# --- STREAMLIT OBERFLÄCHE ---
if st.button("Darkmode-Karte generieren"):
    with st.spinner("Lade Geodaten und rendere Grafik..."):
        fertige_grafik = create_dark_map()
        st.pyplot(fertige_grafik)
        st.success("Sieht das nicht gleich viel mehr nach Profi-Wettermodell aus?")
