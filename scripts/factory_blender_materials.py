"""Explicit presentation materials; never mutate frozen MuJoCo assets or RGBA events."""
import re
import colorsys


ROBOT_BODY = re.compile(r'__[A-Z]_(?:link\d|hand|left_?finger|right_?finger)$')


def apply_recorded_appearance(obj, original, rgba, geom_material):
    """Update only the geometry whose recorded appearance has changed."""
    if any(abs(float(a)-float(b)) > 1e-7 for a,b in zip(rgba,original['rgba'])):
        spec = dict(original, material=-1, rgba=list(rgba))
        obj.material_slots[0].material = geom_material(spec)


def robot_role(spec):
    """Classify the neutral authored robot parts, leaving colored indicators intact."""
    rgb = spec['rgba'][:3]
    if max(rgb) - min(rgb) < .06:
        if max(rgb) <= .30:
            return 'joint'
        if min(rgb) >= .75:
            return 'shell'
    return 'hardware'


def task_role(geom):
    name=geom.get('name','')
    if '__' not in name:return None
    if any(mark in name for mark in ('_label','_print','_mark','__score_title_geom')):return 'print'
    if (name.startswith('relay-') and re.search(r'__payload_\d+_beam$',name)
            or name.startswith('mosaic-') and re.search(r'__[A-Z]_stock\d+_geom$',name)):
        return 'painted_wood'
    if (name.startswith('transport-') and re.search(r'__(?:[A-Z]_item\d+_geom|[A-Z]_slot\d+_cue_color\d+|board_[A-Z]_plate)$',name)
            or name.startswith('relay-') and re.search(r'__relay_(?:direction|start|goal)_',name)
            or name.startswith('dial-') and re.search(r'__D\d+_(?:module_disk|red_knob|red_knob_grip_\d+|orange_pointer|pointer_tip)$',name)):
        return 'task_color'
    return None


def resolve(spec, role=None, calibrated=True):
    result = dict(spec)
    # Replay events arrive as NumPy float32; normalize at this boundary so the
    # effective material audit remains JSON-safe when a new color appears.
    result['rgba']=[float(c) for c in result['rgba']]
    # Negative MuJoCo values are unspecified, not physical PBR coefficients.
    for key, default in [('roughness', .52), ('metallic', 0.)]:
        value = result.get(key, -1.)
        result[key] = float(default if value < 0 else min(1., value))
    if calibrated and role in ('joint', 'shell'):
        # A documented display palette, not an assumed global sRGB conversion.
        result.update(rgba=[.025, .030, .036, result['rgba'][3]] if role == 'joint'
                      else [.67, .70, .72, result['rgba'][3]],
                      roughness=.54 if role == 'joint' else .46,
                      metallic=0., specular=.30)
    if role in ('print','painted_wood'):
        result.update(roughness=.95 if role=='print' else .58,metallic=0.,specular=0. if role=='print' else .25)
    if role=='task_color' and max(result['rgba'][:3])-min(result['rgba'][:3]) < .06:
        result.update(roughness=.65,metallic=0.,specular=.18)
    if role in ('print','painted_wood','task_color'):
        # Presentation-only chroma adjustment; neutral whites and alpha remain
        # unchanged, as do the frozen source and replay event values.
        h,s,v=colorsys.rgb_to_hsv(*result['rgba'][:3])
        if s > .08:
            result['rgba'][:3]=colorsys.hsv_to_rgb(h,min(1.,s*1.65),v)
    return result
