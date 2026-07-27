import streamlit as st
import numpy as np
import matplotlib.pyplot as plt

# Seiten-Layout
st.set_page_config(page_title="Modellkarten-Generator", page_icon="🗺️", layout="wide")

st.title("🗺️ Statische Modellkarte (Prototyp)")
st.write("Hier testen wir die Zeichen-Logik der Modellkarte. Es werden fiktive Daten generiert, die wie ein echtes Temperatur-Raster aussehen.")

# Funktion: Generiert das Bild
def create_dummy_map():
    # 1. Wir definieren das Gitter für Deutschland
    # Längengrad (West-Ost): ca. 5.8 bis 15.0
    # Breitengrad (Süd-Nord): ca. 47.2 bis 55.0
    lons = np.linspace(5.8, 15.0, 100)
    lats = np.linspace(47.2, 55.0, 100)
    
    # Raster erzeugen (wie ein Koordinatensystem)
    Lons, Lats = np.meshgrid(lons, lats)
    
    # 2. Fiktive Wetterdaten erzeugen (Temperatur)
    # Basis 25 Grad, nach Norden kühler, plus ein paar "Wellen" (Sinus) für die Optik
    Temp = 25 - (Lats - 47.2) * 1.8 + np.sin(Lons * 3) * 2 

    # 3. Die Karte zeichnen (Matplotlib)
    fig, ax = plt.subplots(figsize=(10, 8))
    
    # contourf zeichnet die eingefärbten Flächen (die klassische Modellkarten-Optik)
    # cmap='coolwarm' ist die Farbskala von Blau (kalt) zu Rot (warm)
    karte = ax.contourf(Lons, Lats, Temp, levels=20, cmap='coolwarm')
    
    # Eine Farbskala an der Seite hinzufügen
    cbar = fig.colorbar(karte, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label('Temperatur in °C')
    
    # Achsen anpassen
    ax.set_title("Fiktives Temperatur-Modell (Deutschland-Ausschnitt)")
    ax.set_xlabel("Längengrad (Ost)")
    ax.set_ylabel("Breitengrad (Nord)")
    
    # Das fertige Bild zurückgeben
    return fig

# Der Auslöser auf der Webseite
if st.button("Wetterkarte jetzt rendern"):
    with st.spinner("Berechne mathematisches Gitter und zeichne Karte..."):
        # Funktion aufrufen
        fertige_grafik = create_dummy_map()
        
        # Die fertige Grafik in Streamlit anzeigen
        st.pyplot(fertige_grafik)
        
        st.success("Erfolgreich generiert! Genauso funktioniert es später auch mit den echten GRIB2-Daten.")
