# What a real OrcaSlicer project file looks like

Everything here was read out of a genuine painted project
(`Baby_Dragon_4Color_Orca_Painted_v3_REPAIRED.3mf`, OrcaSlicer 2.6.32 writing as
BambuStudio-02.06.00.51). Before this file arrived, the settings half of the
plugin was written from inference. These are measurements.

## The paint encoding was already right

The codec in `paintlib/encoding.py` was ported from OrcaSlicer's source before any
real file was available. The real file agrees exactly:

| value in the file | count | decodes to |
|---|---|---|
| `4` | 1,218 | filament 1 |
| `8` | 61,458 | filament 2 |
| `1C` | 177,882 | filament 4 |

240,558 painted triangles of 475,556. Filament 3 never appears as paint, because
**the default filament is an object property, not paint**:
`Metadata/model_settings.config` carries `<metadata key="extruder" value="3"/>`
on the object, and every unpainted triangle prints in that filament. A plugin
that painted all four colors explicitly would produce a correct-looking file that
does 235,000 triangles of work the slicer would have done for free.

## Archive layout

Real project files use the 3MF production extension:

```
3D/3dmodel.model                      4 KB   metadata, build item, component ref
3D/Objects/<name>.stl_1.model        43 MB   the actual mesh, with paint_color
Metadata/project_settings.config     33 KB   672 keys of JSON
Metadata/model_settings.config        2 KB   per-object extruder, plate config
Metadata/plate_1.png, top_1.png, ...         previews the slicer regenerates
Auxiliaries/...                              model pictures, thumbnails
```

Object ids are unique only within a part, which is why `apply_plan.py` resolves
on `(part, object_id)`. The root model holds the placement, and it is not
identity: this file carries a 45 degree rotation
(`0.707106781 0.707106781 0 -0.707106781 ...`) on its build item. That is why the
exported STL measured 153 x 153 mm when the model is 108 x 187 mm. The rotation
lives in the project, not in the mesh.

## Filament keys, verified

```json
"filament_colour":        ["#FFFFFF", "#000000", "#FF8000", "#808080"],
"filament_multi_colour":  ["#FFFFFF", "#000000", "#FF8000", "#808080"],
"filament_type":          ["PLA", "PLA", "PLA", "PLA"],
"filament_ids":           ["OGFL99", "OGFL99", "OGFL99", "OGFL99"],
"filament_colour_type":   ["1", "1", "1", "1"],
"filament_settings_id":   ["Generic PLA @FF C5P - Copy", ...]
```

`filament_multi_colour` mirrors `filament_colour` and is what the slicer draws the
plate from. Out of step, Orca shows the previous colors over correct paint, which
looks exactly like the plugin failing.

`Metadata/model_settings.config` also carries the plate's nozzle mapping:
`filament_maps` = `1 2 3 4` with `filament_map_mode` = `Auto For Flush`.

## Printer

```
printer_model                  Flashforge Creator 5 Pro
nozzle_diameter                ["0.4", "0.4", "0.4", "0.4"]
extruder_type                  ["Direct Drive", ...]
single_extruder_multi_material 0
```

Four independent nozzles, no tool changes, no purge tower. Color count is a
hardware fact here, not a preference, which is why plans cap at four.

## Consequence for the plugin

Never synthesize `project_settings.config` when the input already has one. It
holds 672 keys describing the printer, the filaments, and the print profile, and
the plugin understands about eight of them. `orca.py` reads the existing object,
patches the filament arrays, and writes the rest back untouched. Verified on this
file: 672 keys in, 672 keys out, printer profile intact.

## Round-trip proof

Reading this file, repainting 2,000 triangles, and writing it back:

```
geometry_matches: True -- 1 object(s), 475556 triangles, geometry and placement identical
triangles outside the edit unchanged: 473556 / 473556
archive entries: 27 -> 27, missing: none
non-mesh entries that changed: none
```
