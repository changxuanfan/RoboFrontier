"""Compare animated mesh rotations in the exported asset's coordinate frame."""
import numpy as np


def asset_frame_rotation(kind, body_rotation, local_rotation, recorded_rotation):
    """Reconcile proper 180-degree mesh-axis flips introduced by mesh compilation."""
    recorded=np.asarray(recorded_rotation)
    if kind!=7:return recorded,False
    asset=np.asarray(body_rotation)@np.asarray(local_rotation)
    if np.allclose(asset,recorded,atol=1e-6,rtol=0):return recorded,False
    delta=asset.T@recorded
    diagonal=np.diag(delta)
    signs=np.where(diagonal>=0,1.,-1.)
    if np.prod(signs)>0 and np.allclose(delta,np.diag(signs),atol=1e-6,rtol=0):
        return asset,True
    return recorded,False
