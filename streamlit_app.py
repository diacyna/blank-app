import streamlit as st
import pandas as pd
import rasterio
from rasterio.transform import Affine
import folium
from branca.element import MacroElement, Template
from PIL import Image
import numpy as np
import base64
from pyproj import Transformer
import matplotlib.pyplot as plt
import seaborn as sns
from streamlit_folium import st_folium
import io
import os
import difflib
import plotly.express as px

formation_colors = {
    'Treuchtlingen': '#ADD8E6',
    'Arzberg': '#0000CD',
    'Dietfurt': '#00008B',
    'Segenthal': '#8B4513',
    'Eisensandstein': '#8B0000',
    'Opalinuston': '#C68642',
    'Keuper': '#FF4500',
    'Hauptmuschelkalk': '#E6A8D7',
    'Mittlerer Muschelkalk': '#008000',
    'Wellenkalk': '#4B0082',
    'Oberer Buntsandstein': '#FFFF00',
    'Mittlerer Buntsandstein': '#FFA500',
}

canonical_formations = list(formation_colors.keys())

formation_aliases = {
    'mittlerer muschelkalk': 'Mittlerer Muschelkalk',
    'mitllerer muschelkalk': 'Mittlerer Muschelkalk',
    'mittlerer buntsandstein': 'Mittlerer Buntsandstein',
    'mitllerer buntsandstein': 'Mittlerer Buntsandstein',
}


def normalize_formation(name):
    if pd.isna(name):
        return None
    text = str(name).strip()
    if not text:
        return None
    normalized_text = formation_aliases.get(text.lower(), text)
    if normalized_text in canonical_formations:
        return normalized_text
    lower = normalized_text.lower()
    for canonical in canonical_formations:
        if lower.replace(' ', '') == canonical.lower().replace(' ', ''):
            return canonical
    best_match = None
    best_ratio = 0.0
    for canonical in canonical_formations:
        ratio = difflib.SequenceMatcher(None, lower, canonical.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = canonical
    return best_match if best_match is not None else None


def get_formation_color(name):
    if name is None or pd.isna(name):
        return '#7F7F7F'
    normalized = normalize_formation(name)
    return formation_colors.get(normalized, '#7F7F7F')


def dm_to_dd(degrees, minutes):
    """Converts degrees and minutes to decimal degrees."""
    return degrees + minutes / 60

st.set_page_config(layout="wide")
st.title('Georeferencing and Geological Data Viewer')

st.write("Upload your image (e.g., screenshot) and Excel file with geological coordinates.")

image_file = st.file_uploader("Upload Image (PNG/JPG)", type=['png', 'jpg', 'jpeg'])
excel_file = st.file_uploader("Upload Excel File (.xlsx)", type=['xlsx'])

if image_file and excel_file:
    st.success("Files uploaded successfully! Starting processing...")

    # Temporary paths for processing
    input_image_path = io.BytesIO(image_file.getvalue())
    output_geotiff_path = "/tmp/georeferenced_screenshot.tif" # Use a temporary file
    output_png_path = "/tmp/georeferenced_screenshot.png"

    ### 1. Georeference the Image
    st.subheader("1. Georeferencing Image")
    st.info("Start fresh by entering the four image corner coordinates manually.")

    with st.form("georef_coordinates"):
        st.write("Enter the corner coordinates for the image (latitude/longitude).")
        col1, col2 = st.columns(2)
        with col1:
            top_left_lat = st.text_input("Top Left Latitude", value="50.2", placeholder="e.g. 50.2")
            bottom_left_lat = st.text_input("Bottom Left Latitude", value="50.1", placeholder="e.g. 50.1")
            top_left_lon = st.text_input("Top Left Longitude", value="11.3333", placeholder="e.g. 11.3333")
            bottom_left_lon = st.text_input("Bottom Left Longitude", value="11.3333", placeholder="e.g. 11.3333")
        with col2:
            top_right_lat = st.text_input("Top Right Latitude", value="50.2", placeholder="e.g. 50.2")
            bottom_right_lat = st.text_input("Bottom Right Latitude", value="50.1", placeholder="e.g. 50.1")
            top_right_lon = st.text_input("Top Right Longitude", value="11.5", placeholder="e.g. 11.5")
            bottom_right_lon = st.text_input("Bottom Right Longitude", value="11.5", placeholder="e.g. 11.5")
        submitted = st.form_submit_button("Use these coordinates")

    if not submitted:
        st.info("No georeferencing coordinates were submitted yet. The app is waiting for the four corner values.")
        st.stop()

    try:
        top_left = {'lat': float(top_left_lat), 'lon': float(top_left_lon)}
        top_right = {'lat': float(top_right_lat), 'lon': float(top_right_lon)}
        bottom_left = {'lat': float(bottom_left_lat), 'lon': float(bottom_left_lon)}
        bottom_right = {'lat': float(bottom_right_lat), 'lon': float(bottom_right_lon)}
    except ValueError:
        st.error("Please enter valid numeric values for all corner coordinates.")
        st.stop()

    st.write("Defined corner coordinates:")
    st.write(pd.DataFrame([
        ['Links oben', top_left['lat'], top_left['lon']],
        ['Rechts oben', top_right['lat'], top_right['lon']],
        ['Links unten', bottom_left['lat'], bottom_left['lon']],
        ['Rechts unten', bottom_right['lat'], bottom_right['lon']]
    ], columns=['Position', 'Latitude', 'Longitude']))

    # Load the image using Pillow
    img = Image.open(input_image_path)
    img_array = np.array(img)

    # Get image dimensions
    height, width = img_array.shape[:2]
    bands = img_array.shape[2] if img_array.ndim == 3 else 1

    # Compute an affine transform from pixel coordinates to geographic coordinates
    # using the three known corners (top-left, top-right, bottom-left).
    src_points = np.array([
        [0, 0, 1],
        [width, 0, 1],
        [0, height, 1]
    ], dtype=float)
    dst_lon = np.array([top_left['lon'], top_right['lon'], bottom_left['lon']], dtype=float)
    dst_lat = np.array([top_left['lat'], top_right['lat'], bottom_left['lat']], dtype=float)

    lon_coeffs = np.linalg.solve(src_points, dst_lon)
    lat_coeffs = np.linalg.solve(src_points, dst_lat)

    transform = Affine(lon_coeffs[0], lon_coeffs[1], lon_coeffs[2],
                       lat_coeffs[0], lat_coeffs[1], lat_coeffs[2])

    west = min(top_left['lon'], bottom_left['lon'])
    east = max(top_right['lon'], bottom_right['lon'])
    south = min(bottom_left['lat'], bottom_right['lat'])
    north = max(top_left['lat'], top_right['lat'])

    st.write(f"Approximate rectangular bounds: West={west}°, South={south}°, East={east}°, North={north}°")

    # Define the Coordinate Reference System (CRS) - WGS84 for lat/lon
    crs = 'EPSG:4326'

    # Write the image as a GeoTIFF
    with rasterio.open(
        output_geotiff_path,
        'w',
        driver='GTiff',
        height=height,
        width=width,
        count=bands,
        dtype=img_array.dtype,
        crs=crs,
        transform=transform,
    ) as dst:
        for i in range(bands):
            dst.write(img_array[:, :, i], i + 1)
    st.success(f"Image successfully georeferenced to {output_geotiff_path}")

    # Convert GeoTIFF to PNG for Folium overlay (if original was not PNG already)
    with rasterio.open(output_geotiff_path) as src:
        geotiff_data = src.read()
        if src.count == 4:
            pil_image_array = np.transpose(geotiff_data, (1, 2, 0)).astype(np.uint8)
            pil_img = Image.fromarray(pil_image_array, 'RGBA')
        elif src.count == 3:
            pil_image_array = np.transpose(geotiff_data, (1, 2, 0)).astype(np.uint8)
            pil_img = Image.fromarray(pil_image_array, 'RGB')
        else:
            pil_image_array = geotiff_data[0, :, :].astype(np.uint8)
            pil_img = Image.fromarray(pil_image_array, 'L')

        pil_img.save(output_png_path)
    st.success(f"GeoTIFF converted to PNG for display: {output_png_path}")


    ### 2. Convert Coordinates
    st.subheader("2. Converting UTM to Latitude/Longitude")
    coordinates_df = pd.read_excel(excel_file)

    if 'UTM Zone' in coordinates_df.columns and 'Easting' in coordinates_df.columns and 'Northing' in coordinates_df.columns:
        try:
            if 'Formation' in coordinates_df.columns:
                coordinates_df['Formation'] = coordinates_df['Formation'].apply(normalize_formation)
            utm_zone_str = coordinates_df['UTM Zone'].iloc[0]
            zone_number = int(utm_zone_str[:-1])
            hemisphere = 'north' if utm_zone_str[-1].upper() >= 'N' else 'south'

            if hemisphere == 'north':
                utm_epsg_code = 32600 + zone_number
            else:
                utm_epsg_code = 32700 + zone_number

            transformer = Transformer.from_crs(f"epsg:{utm_epsg_code}", "epsg:4326", always_xy=True)

            latitudes = []
            longitudes = []
            for idx, row in coordinates_df.iterrows():
                easting = row['Easting']
                northing = row['Northing']
                lon, lat = transformer.transform(easting, northing)
                longitudes.append(lon)
                latitudes.append(lat)

            coordinates_df['Latitude'] = latitudes
            coordinates_df['Longitude'] = longitudes
            st.success("UTM coordinates successfully converted to Latitude and Longitude.")
            st.dataframe(coordinates_df.head())
        except Exception as e:
            st.error(f"Error converting UTM coordinates: {e}")
            st.stop()
    else:
        st.warning("UTM Zone, Easting, or Northing columns not found in Excel file. Skipping coordinate conversion.")
        st.stop()


    ### 3. Display on an Interactive Map
    st.subheader("3. Interactive Map with Data Overlay")

    center_lat = (north + south) / 2
    center_lon = (east + west) / 2

    m = folium.Map(location=[center_lat, center_lon], zoom_start=12)
    points_layer = folium.FeatureGroup(name='Points from Excel').add_to(m)

    overlay_bounds = [[south, west], [north, east]]
    folium.raster_layers.ImageOverlay(
        name='Georeferenced Screenshot',
        image=output_png_path,
        bounds=overlay_bounds,
        opacity=0.5,
        interactive=True,
        cross_origin=False,
        zindex=1,
    ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    m.fit_bounds([
        [top_left['lat'], top_left['lon']],
        [top_right['lat'], top_right['lon']],
        [bottom_left['lat'], bottom_left['lon']],
        [bottom_right['lat'], bottom_right['lon']]
    ])

    if 'Latitude' in coordinates_df.columns and 'Longitude' in coordinates_df.columns:
        for idx, row in coordinates_df.iterrows():
            lat = row['Latitude']
            lon = row['Longitude']
            formation = normalize_formation(row['Formation']) if 'Formation' in row else None
            point_name = formation if formation else f"Point {idx+1}"
            marker_color = get_formation_color(formation)

            folium.CircleMarker(
                location=[lat, lon],
                radius=6,
                color=marker_color,
                fill=True,
                fill_color=marker_color,
                fill_opacity=0.9,
                popup=point_name,
            ).add_to(points_layer)
    else:
        st.warning("Latitude or Longitude columns not found after conversion. Skipping marker display.")

    # folium.LayerControl().add_to(m)  # Temporarily disabled to debug set serialization error

    # Debug: Inspect layer names to find set instances
    print("DEBUG: Checking layer_names:")
    for child_name, child in m._children.items():
        if hasattr(child, 'layer_name'):
            print(f"  {child_name}: layer_name={repr(child.layer_name)} (type={type(child.layer_name).__name__})")
        if hasattr(child, 'overlay'):
            print(f"  {child_name}: overlay={child.overlay}")

    legend_items = [(formation, formation_colors[formation]) for formation in canonical_formations]
    legend_html = """
    <style>
    .legend-box {display: flex; align-items: center; margin-bottom: 8px;}
    .legend-color {width: 18px; height: 18px; margin-right: 8px; border: 1px solid #555;}
    .legend-container {font-size: 14px; line-height: 1.6;}
    .legend-title {font-weight: bold; margin-bottom: 10px;}
    </style>
    <div class='legend-container'>
      <div class='legend-title'>Formation Legende</div>
"""
    for name, color in legend_items:
        legend_html += f"      <div class='legend-box'><div class='legend-color' style='background:{color}'></div>{name}</div>\n"
    legend_html += "</div>\n"

    col_map, col_legend = st.columns([3, 1])

    # Sanitize Folium map object: replace any Python `set` instances in attributes
    # with lists so Jinja2/JSON serialization does not fail. Also provide a
    # diagnostic routine that records the path to any set found for debugging.
    def _sanitize_sets_in_obj(obj, path=(), seen=None, found=None):
        if seen is None:
            seen = set()
        if found is None:
            found = []
        oid = id(obj)
        if oid in seen:
            return found
        seen.add(oid)
        if isinstance(obj, set):
            found.append((path, obj))
            return found
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                key_path = path + (f"dict_key({repr(k)})",)
                if isinstance(k, set):
                    found.append((key_path, k))
                    newk = tuple(k)
                    obj[newk] = obj.pop(k)
                    k = newk
                val_path = path + (f"dict_val({repr(k)})",)
                if isinstance(v, set):
                    found.append((val_path, v))
                    obj[k] = list(v)
                else:
                    _sanitize_sets_in_obj(v, val_path, seen, found)
            return found
        if isinstance(obj, (list, tuple)):
            for i, it in enumerate(obj):
                _sanitize_sets_in_obj(it, path + (f'[{i}]',), seen, found)
            return found
        # For objects, inspect __dict__ where possible
        try:
            for attr, val in list(getattr(obj, '__dict__', {}).items()):
                attr_path = path + (f"attr.{attr}",)
                if isinstance(val, set):
                    found.append((attr_path, val))
                    try:
                        setattr(obj, attr, list(val))
                    except Exception:
                        pass
                else:
                    _sanitize_sets_in_obj(val, attr_path, seen, found)
        except Exception:
            pass
        return found

    # Run sanitization across map children and record any sets found
    found_sets = []
    for name, child in list(m._children.items()):
        found_sets.extend(_sanitize_sets_in_obj(child, path=(f'child:{name}',)))
    if found_sets:
        import sys
        for p, s in found_sets:
            try:
                print('SANITIZE_FOUND_SET at ' + '/'.join(p) + f' => {repr(s)}', file=sys.stderr)
            except Exception:
                print('SANITIZE_FOUND_SET (unprintable) at ' + '/'.join(p), file=sys.stderr)
    with col_map:
        # Render the folium map with a guarded approach so we can capture
        # and display detailed diagnostics if JSON serialization fails.
        import streamlit.components.v1 as components
        try:
            html = m.get_root().render()
            components.html(html, height=600)
        except Exception as _e:
            import traceback, sys
            tb = traceback.format_exc()
            st.error("Fehler beim Rendern der Karte: " + str(_e))
            st.text("--- Traceback ---")
            st.text(tb)

            # Run sanitization/diagnostics again and show findings to the user
            try:
                found_sets = []
                for name, child in list(m._children.items()):
                    found_sets.extend(_sanitize_sets_in_obj(child, path=(f'child:{name}',)))
                if found_sets:
                    st.warning("Gefundene Python `set`-Instanzen in Map-Objekt:")
                    for p, s in found_sets:
                        try:
                            st.write({'path': '/'.join(p), 'value_repr': repr(s)})
                        except Exception:
                            st.write({'path': '/'.join(p), 'value_repr': '<unprintable>'})
                else:
                    st.info("Keine `set`-Instanzen gefunden. Weitere Diagnose erforderlich.")
            except Exception as _d:
                st.text("Fehler während Diagnose: " + repr(_d))
            st.stop()
    with col_legend:
        import streamlit.components.v1 as components
        components.html(legend_html, height=max(200, 40 * len(legend_items)), scrolling=True)

    # Debug: Prüfe Map-Objekt auf Python `set`-Instanzen (helfen beim ToJSON-Fehler)
    try:
        import sys
        from collections import deque

        def _find_sets(root, limit=2000):
            seen = set()
            q = deque([root])
            found = []
            while q and len(found) < limit:
                obj = q.popleft()
                oid = id(obj)
                if oid in seen:
                    continue
                seen.add(oid)
                if isinstance(obj, set):
                    found.append((type(obj).__name__, repr(obj)))
                    continue
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(k, set):
                            found.append(('dict_key', repr(k)))
                        if isinstance(v, set):
                            found.append(('dict_val', repr(v)))
                        q.append(k)
                        q.append(v)
                    continue
                if isinstance(obj, (list, tuple)):
                    for it in obj:
                        if isinstance(it, set):
                            found.append(('container', repr(it)))
                        q.append(it)
                    continue
                for attr in dir(obj):
                    if attr.startswith('__'):
                        continue
                    try:
                        val = getattr(obj, attr)
                    except Exception:
                        continue
                    if isinstance(val, set):
                        found.append(('attr', type(obj).__name__, attr, repr(val)))
                    elif isinstance(val, (list, tuple, dict)):
                        q.append(val)
            return found

        sets_found = _find_sets(m)
        if sets_found:
            print('DEBUG_FOUND_SETS:', sets_found, file=sys.stderr)
        # Zusätzlich: gezielt layer_name prüfen
        try:
            for child_name, child in m._children.items():
                try:
                    ln = getattr(child, 'layer_name', None)
                except Exception:
                    ln = '<error>'
                if isinstance(ln, set):
                    print('DEBUG_LAYER_SET:', child_name, type(child).__name__, repr(ln), file=sys.stderr)
                else:
                    # kurze Ausgabe zur Kontrolle
                    print('DEBUG_LAYER:', child_name, type(child).__name__, type(ln).__name__, file=sys.stderr)
        except Exception as _e:
            print('DEBUG_LAYER_CHECK_FAILED', _e, file=sys.stderr)
    except Exception as _dbg:
        print('DEBUG_SEARCH_FAILED', _dbg, file=sys.stderr)

    st.subheader("5. Kartiergebiet-Erklärung")
    kartiergebiet_text = """
    Dies ist ein Kartiergebiet bei Kirchleus! Es handelt sich dabei um stratigraphische Einheiten
    vom Buntsandstein bis einschließlich Oberjura mit deutlichen tektonischen Strukturen.
    Diese wurden anhand von Aufschlüssen, Lesesteinen und Messwerten bestimmt.
    Besonders ist in diesem Gebiet eine steile Aufschiebung; entlang dieser Unterjura-Schichten
    fehlen vollständig und Trias-Schichten folgen abrupt. Diese tektonische Überprägung wird
    von plötzlich steilen Einfallswinkeln, Falten und sekundär gebildeten Kalziten bestätigt.
    Die erstellte geologische Karte zeigt die räumliche Verteilung der Formationen und den
    östlichen verlaufenden Versatz.
    Insgesamt zeigt das Gebiet einen Teil der komplexen Bruchschollenstruktur des Fränkischen Jura.
    """

    info_image_path = "kartiergebiet.png"
    col_desc, col_image_desc = st.columns([2, 1])
    with col_desc:
        st.markdown(kartiergebiet_text)
    with col_image_desc:
        if os.path.exists(info_image_path):
            st.image(info_image_path, caption="Kartiergebiet", use_column_width=True)
        uploaded_info_image = st.file_uploader(
            "Optional: Kartiergebiet-Bild hochladen",
            type=['png', 'jpg', 'jpeg'],
            key='kartiergebiet_image_upload'
        )
        if uploaded_info_image:
            st.image(Image.open(uploaded_info_image), caption="Kartiergebiet Illustration", use_column_width=True)


    ### 4. Data Exploration and Visualizations
    st.subheader("4. Data Visualizations")

    if 'Formation' in coordinates_df.columns:
        coordinates_df['Formation'] = coordinates_df['Formation'].apply(normalize_formation)
        all_formation_counts = coordinates_df['Formation'].value_counts().reset_index()
        all_formation_counts.columns = ['Formation', 'Häufigkeit']

        observed_formations = [formation for formation in coordinates_df['Formation'].dropna().unique().tolist() if formation]
        ordered_formations = [f for f in canonical_formations if f in observed_formations]

        show_all_formations = st.checkbox('Alle Formationen anzeigen', value=True, help='Wähle alle verfügbaren Formationen für die Diagramme aus.')
        selected_formations = ordered_formations if show_all_formations else st.multiselect(
            'Formationen anzeigen',
            options=ordered_formations,
            default=ordered_formations,
            help='Wähle aus, welche Formationen in den Diagrammen sichtbar sein sollen.'
        )
        if show_all_formations:
            st.caption(f"{len(ordered_formations)} Formationen gefunden.")

        if selected_formations:
            filtered_all_counts = all_formation_counts[all_formation_counts['Formation'].isin(selected_formations)].copy()
            filtered_all_counts = filtered_all_counts.sort_values('Formation', key=lambda s: s.map({formation: index for index, formation in enumerate(selected_formations)}))
            color_map = {formation: get_formation_color(formation) for formation in filtered_all_counts['Formation']}

            fig_all = px.bar(
                filtered_all_counts,
                x='Formation',
                y='Häufigkeit',
                color='Formation',
                color_discrete_map=color_map,
                title='Häufigkeit aller Formationen',
                labels={'Formation': 'Formation', 'Häufigkeit': 'Anzahl der Vorkommen'}
            )
            fig_all.update_layout(
                xaxis={'categoryorder': 'array', 'categoryarray': selected_formations},
                template='plotly_white',
                legend_title_text='Formation'
            )
            fig_all.update_traces(marker_line_width=0)
            st.plotly_chart(fig_all, use_container_width=True, key='all-formations-chart')

            if 'Aufschlusswand?' in coordinates_df.columns:
                aufschlusswand_df = coordinates_df[coordinates_df['Aufschlusswand?'] == 'Ja']
                if not aufschlusswand_df.empty:
                    formation_counts = aufschlusswand_df['Formation'].value_counts().reset_index()
                    formation_counts.columns = ['Formation', 'Häufigkeit']
                    filtered_aufschluss_counts = formation_counts[formation_counts['Formation'].isin(selected_formations)].copy()
                    filtered_aufschluss_counts = filtered_aufschluss_counts.sort_values('Formation', key=lambda s: s.map({formation: index for index, formation in enumerate(selected_formations)}))
                    color_map_aufschluss = {formation: get_formation_color(formation) for formation in filtered_aufschluss_counts['Formation']}

                    fig1 = px.bar(
                        filtered_aufschluss_counts,
                        x='Formation',
                        y='Häufigkeit',
                        color='Formation',
                        color_discrete_map=color_map_aufschluss,
                        title='Häufigkeit von Aufschlusswänden pro Formation',
                        labels={'Formation': 'Formation', 'Häufigkeit': 'Anzahl der Aufschlusswände'}
                    )
                    fig1.update_layout(
                        xaxis={'categoryorder': 'array', 'categoryarray': selected_formations},
                        template='plotly_white',
                        legend_title_text='Formation'
                    )
                    fig1.update_traces(marker_line_width=0)
                    st.plotly_chart(fig1, use_container_width=True, key='aufschluss-formations-chart')
                else:
                    st.info("Keine Daten für 'Aufschlusswand?' == 'Ja' verfügbar.")
        else:
            st.info('Bitte mindestens eine Formation auswählen, um die Diagramme anzuzeigen.')
    else:
        st.warning("Columns 'Formation' not found in Excel file. Skipping visualizations.")
