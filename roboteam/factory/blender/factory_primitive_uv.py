"""Texture coordinates for the primitive faces used by the factory renderer."""


def primitive_uv(kind, co, normal):
    axis = max(range(3), key=lambda i: abs(normal[i]))
    i, j = ((1, 2), (0, 2), (0, 1))[axis]
    u, v = (co[i] + 1) / 2, (co[j] + 1) / 2
    # MuJoCo maps the top cap of a cylinder differently from a box's top.
    # The exported image is unchanged, so the Blender V coordinate must flip.
    if kind == 5 and axis == 2 and normal[2] > 0:
        v = 1 - v
    return u, v
