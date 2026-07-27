import streamlit as st

st.set_page_config(
    page_title="Regionale Wetter-KI & Modellkarten",
    page_icon="🗺️",
    layout="wide"
)

st.title("🗺️ Regionale Wetter-Zentrale & Modellkarten")
st.write("Hier siehst du die Modellkarten-Ansicht ähnlich wie bei großen Wetterportalen – angepasst auf deine Region.")

# Sidebar für die Steuerung
st.sidebar.header("⚙️ Modell-Steuerung")
region = st.sidebar.selectbox(
    "Region wählen:",
    ["Deutschland", "Mitteldeutschland", "Brandenburg (Elbe-Elster)"]
)

parameter = st.sidebar.selectbox(
    "Meteorologischer Parameter:",
    ["Temperatur (2m)", "Niederschlag / Radar", "Windböen"]
)

st.sidebar.divider()
st.sidebar.info("Modell-Basis: DWD ICON / Open Data")

# Hauptbereich: Anzeige der "Modellkarte"
st.subheader(f"Modellkarte: {parameter} für {region}")

# Platzhalter für die Karte (hier binden wir später die echten Daten oder gerenderten GRIB2-Plots ein)
if parameter == "Temperatur (2m)":
    st.success("Lade Temperatur-Gitterdaten...")
    # Hier könnte später deine gerenderte Karte stehen
    st.image("https://images.unsplash.com/photo-1592210454359-9043f067919b?auto=format&fit=crop&w=1000&q=80", 
             caption=f"Beispiel-Ansicht: Temperaturmodell für {region}")

elif parameter == "Niederschlag / Radar":
    st.warning("Verknüpfe Regenradar-Echtzeitdaten...")
    st.image("https://images.unsplash.com/photo-1534274988757-a28bf1a57c17?auto=format&fit=crop&w=1000&q=80", 
             caption=f"Beispiel-Ansicht: Niederschlag/Radar für {region}")

else:
    st.info("Lade Winddaten...")
    st.markdown("*(Hier erscheint demnächst die Wind-Modellkarte)*")
