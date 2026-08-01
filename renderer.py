# renderer.py
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patheffects as path_effects
import scipy.ndimage as ndimage
import io
from config import REGIONS, GERMAN_CITIES, SIG_WETTER_LABELS

def get_scientific_cmap(param_name):
    if "Temp" in param_name or "Taupunkt" in param_name: return "turbo"
    if "Wind" in param_name or "Scherung" in param_name: return "plasma"
    if "Niederschlag" in param_name or "Regen" in param_name or "PWAT" in param_name: return "viridis_r"
    if "CAPE" in param_name or "LPI" in param_name or "SCP" in param_name or "Chaser" in param_name or "Sonnen" in param_name: return "magma_r"
    if "Bewölkung" in param_name or "Tiefe Wolken" in param_name or "Sichtweite" in param_name: return "Greys_r"
    if "Radar" in param_name: return "nipy_spectral"
    if "Feuchte" in param_name or "Schnee" in param_name: return "YlGnBu"
    if "Luftdruck" in param_name: return "BrBG"
    return "turbo"

def create_map(config_list, lons, lats, data, map_title_time, legend_title, model_type, region, overlays, design, world, bundeslaender, radar_img=None, radar_extent=None):
    is_categorical = (legend_title == "Signifikantes Wetter" or "[AI-Blend] Signifikantes Wetter" in legend_title)
    is_discrete = design.get('discrete_colors', False)
    is_live_radar = (model_type == "Live-Radar (Rainviewer)")
    is_blanko = (legend_title == "Basiskarte (ohne Daten)")
    use_sci_cmap = design.get('scientific_cmap', False)
    
    if not config_list:
        config_list = [{"value": 0.0, "color": "#000000"}, {"value": 1.0, "color": "#ffffff"}]
    
    if not is_live_radar and not is_blanko:
        levels = [c['value'] for c in sorted(config_list, key=lambda x: x['value'])]
        colors = [c['color'] for c in sorted(config_list, key=lambda x: x['value'])]
        min_v, max_v = min(levels), max(levels)
        if max_v == min_v: max_v += 1 
        
        if is_categorical:
            cmap = mcolors.ListedColormap(colors)
            cmap.set_bad('none')
            bounds = [v - 0.5 for v in levels] + [levels[-1] + 0.5]
            norm = mcolors.BoundaryNorm(bounds, cmap.N)
        elif use_sci_cmap:
            cmap = plt.get_cmap(get_scientific_cmap(legend_title))
            contour_levels = np.linspace(min_v, max_v, 150)
            norm = None
        elif is_discrete:
            cmap = mcolors.ListedColormap(colors)
            bounds = levels + [max_v + 1.0]
            norm = mcolors.BoundaryNorm(bounds, cmap.N)
        else:
            cmap = mcolors.LinearSegmentedColormap.from_list("custom", list(zip([(v - min_v) / (max_v - min_v) for v in levels], colors)))
            contour_levels = np.linspace(min_v, max_v, 150)
            norm = None

    fig, ax = plt.subplots(figsize=(10, 10))
    fig.patch.set_facecolor(design['bg_color'])
    ax.set_facecolor(design['bg_color'])
    
    ax.set_xticks([]); ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_edgecolor(design['border_color'])
        spine.set_linewidth(1.5)
        spine.set_visible(True)
    
    if region in REGIONS: 
        ax.set_xlim(REGIONS[region][0], REGIONS[region][1])
        ax.set_ylim(REGIONS[region][2], REGIONS[region][3])

    if is_live_radar and radar_img is not None:
        ax.imshow(radar_img, extent=radar_extent, aspect='auto', zorder=2)
    elif not is_blanko:
        if overlays.get('clouds') and overlays.get('extra_data') is not None and "Signifikantes Wetter" in legend_title:
            cloud_cmap = mcolors.LinearSegmentedColormap.from_list("clouds", ["#ffffff00", "#ffffff"])
            ax.contourf(lons, lats, overlays['extra_data'], levels=np.linspace(10, 100, 15), cmap=cloud_cmap, alpha=0.75, zorder=1.5)

        if is_categorical:
            karte = ax.pcolormesh(lons, lats, data, cmap=cmap, norm=norm, alpha=0.95, shading='nearest', zorder=2)
            cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
            cbar.ax.set_xticklabels([SIG_WETTER_LABELS.get(int(v), str(v)) for v in levels], rotation=45, ha='right', fontsize=8)
        elif is_discrete and not use_sci_cmap:
            karte = ax.contourf(lons, lats, data, levels=bounds, cmap=cmap, norm=norm, extend='max', alpha=0.95, zorder=2)
            cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=levels, aspect=40)
        else:
            karte = ax.contourf(lons, lats, data, levels=contour_levels, cmap=cmap, norm=norm, extend='both', alpha=0.95, zorder=2)
            tick_step = int(design.get('cbar_step', 1))
            visible_ticks = levels[::tick_step]
            cbar = fig.colorbar(karte, ax=ax, orientation='horizontal', fraction=0.04, pad=0.03, ticks=visible_ticks, aspect=40)
        
        cbar.set_label(legend_title, color=design['text_color'], size=int(design.get('cbar_size', 11)), fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'))
        cbar.ax.xaxis.set_tick_params(color=design['text_color'], labelcolor=design['text_color'], labelsize=9)
        for label in cbar.ax.get_xticklabels(): label.set_fontfamily(design.get('font_family', 'sans-serif'))
    
    line_w = float(design.get('line_width', 0.8))
    world.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=line_w, alpha=float(design.get('border_alpha', 0.4)), zorder=4)
    bundeslaender.boundary.plot(ax=ax, edgecolor=design['border_color'], linewidth=line_w + 0.4, alpha=float(design.get('border_alpha', 0.4)), zorder=4)

    if overlays.get('pmsl_data') is not None and not is_blanko:
        iso = ax.contour(lons, lats, overlays['pmsl_data'], levels=np.arange(900, 1100, 5), colors=design['text_color'], linewidths=1.0, alpha=0.6, zorder=3)
        ax.clabel(iso, inline=True, fontsize=9, fmt='%d', colors=design['text_color'])

    if overlays.get('cities'):
        c_lons, c_lats = [coords[0] for coords in GERMAN_CITIES.values()], [coords[1] for coords in GERMAN_CITIES.values()]
        ax.plot(c_lons, c_lats, 'o', color=design['text_color'], markersize=3, alpha=0.8, zorder=5)
        for lon_c, lat_c, name in zip(c_lons, c_lats, list(GERMAN_CITIES.keys())):
            ax.text(lon_c + 0.08, lat_c + 0.08, name, color=design['text_color'], fontsize=8, fontweight='bold',
                    fontfamily=design.get('font_family', 'sans-serif'), path_effects=[path_effects.withStroke(linewidth=1.5, foreground=design['bg_color'])], zorder=5)

    if overlays.get('numbers') and not is_categorical and not is_live_radar and not is_blanko:
        xmin, xmax, ymin, ymax = ax.get_xlim() + ax.get_ylim()
        try: dy_km = abs(lats[0, 0] - lats[-1, 0]) / max(1, lats.shape[0]) * 111.0
        except: dy_km = 2.2
        if dy_km < 0.1: dy_km = 2.2
        
        zoom_factor = 15.0 / max(1.0, xmax - xmin)
        target_km = max(15.0, 60.0 / zoom_factor)
        dyn_fontsize = min(12, max(5, int(5 * zoom_factor)))
        
        mask = (lons >= xmin) & (lons <= xmax) & (lats >= ymin) & (lats <= ymax) & ~np.isnan(data)
        if "Regenrate" in legend_title or "Niederschlag" in legend_title:
            local_max = ndimage.maximum_filter(data, size=max(3, int((target_km/1.5) / dy_km))) == data
            valid_mask = mask & local_max & (data >= 0.1)
        else:
            grid_mask = np.zeros_like(mask, dtype=bool); grid_mask[::max(1, int(target_km / dy_km)), ::max(1, int(target_km / dy_km))] = True
            valid_mask = mask & grid_mask
        
        for lon_val, lat_val, val in zip(lons[valid_mask], lats[valid_mask], data[valid_mask]):
            if ("Niederschlag" in legend_title or "Regen" in legend_title) and val < 0.1: continue
            if "CAPE" in legend_title and val < 50: continue
            txt = f"{val:.1f}" if ("Niederschlag" in legend_title or "Regen" in legend_title) else f"{val:.0f}"
            ax.text(lon_val, lat_val, txt, fontsize=dyn_fontsize, fontfamily=design.get('font_family', 'sans-serif'), fontweight='bold', 
                    color=design.get('number_color', '#000000'), ha='center', va='center', path_effects=[path_effects.withStroke(linewidth=1.5, foreground=design.get('number_outline', '#FFFFFF'))], zorder=6)

    if design.get('watermark'):
        ax.text(0.5, 0.02, design['watermark'], transform=ax.transAxes, color=design['text_color'], fontsize=10, fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'), ha='center', va='bottom', alpha=0.5, zorder=10)
    
    bbox_props = dict(boxstyle="round,pad=0.5", fc=mcolors.to_rgba(design.get('title_bg', '#0E1117'), alpha=0.4), ec=mcolors.to_rgba(design['border_color'], alpha=0.6), lw=1.2)
    eps_label = f" | {overlays.get('eps_choice')}" if overlays.get('eps_choice') and overlays.get('eps_choice') != "Ensemble-Mittel" else ""
    ax.text(0.015, 0.985, f"{model_type}{eps_label} | {map_title_time}", transform=ax.transAxes, color=design['text_color'], fontsize=int(design.get('title_size', 11)), fontweight='bold', fontfamily=design.get('font_family', 'sans-serif'), ha='left', va='top', bbox=bbox_props, zorder=10)
    
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight', pad_inches=0.1, facecolor=design['bg_color'])
    plt.close(fig)
    return buf.getvalue()
