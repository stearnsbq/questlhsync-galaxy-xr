"""Factory optics used to prepare private pixel maps.

The radial spline is inferred from the firmware's scalar radial evaluator.
The central curved-window projection uses the firmware's one-metre reference
plane and 1,000-entry correction lookup.
"""
from functools import lru_cache
import numpy as np


def validate_camera(camera):
    """Reject unsupported inventory data before attempting any ray conversion."""
    if camera.get('distortion_model') != 'fisheye_spline3':
        raise ValueError('Unsupported factory distortion model')
    if (camera.get('width'), camera.get('height')) != (640, 640):
        raise ValueError('Expected a 640x640 tracking camera')
    for name in ('focal_length', 'principal_point', 'distortion_offset'):
        value = np.asarray(camera[name], dtype=float)
        if value.shape != (2,) or not np.all(np.isfinite(value)):
            raise ValueError('Invalid factory ' + name)
    if np.any(np.asarray(camera['focal_length']) <= 0):
        raise ValueError('Focal lengths must be positive')
    for name in ('max_valid_distorted_radius', 'max_valid_undistorted_radius'):
        radius = camera.get(name)
        if radius is None or not np.isfinite(radius) or radius <= 0:
            raise ValueError('Missing/invalid factory radius; regenerate inventory: ' + name)
    radial = distorted_radius(np.linspace(0, np.pi/2-1e-7, 4097), camera['distortion_coefficients'])
    if np.any(np.diff(radial) <= 0):
        raise ValueError('Spline must be monotonic over the supported ray domain')
    w = camera.get('curved_window')
    if w is not None:
        center = np.asarray(w['center'], dtype=float)
        values = np.asarray([w['radius'], w['thickness'], w['refractive_index']], dtype=float)
        if center.shape != (3,) or not np.all(np.isfinite(np.r_[center, values])):
            raise ValueError('Invalid window parameters')
        if not 0 <= w['thickness'] < w['radius'] or w['refractive_index'] < 1:
            raise ValueError('Invalid window radius, thickness or refractive index')


def distorted_radius(theta, coefficients):
    """Three Hermite segments, with value/slope pairs at pi/6, pi/3, pi/2."""
    theta = np.asarray(theta, dtype=float)
    k = np.asarray(coefficients, dtype=float)
    if k.shape != (6,) or not np.all(np.isfinite(k)):
        raise ValueError('Expected six finite spline coefficients')
    if not np.all(np.isfinite(theta)) or np.any(theta < 0) or np.any(theta >= np.pi/2):
        raise ValueError('Only forward-facing rays are supported')
    segment = np.minimum((theta / (np.pi/6)).astype(int), 2)
    u = theta/(np.pi/6) - segment
    values = np.r_[0., k[::2]]
    slopes = np.r_[0., k[1::2]]
    a, b = values[segment], values[segment+1]
    da, db = slopes[segment], slopes[segment+1]
    gain = 1+a + u*(da+u*((3*(b-a)-2*da-db)+u*(2*(a-b)+da+db)))
    return theta*gain


def lens_rays(camera, pixels):
    pixels = np.asarray(pixels, dtype=float)
    if pixels.ndim != 2 or pixels.shape[1] != 2 or not np.all(np.isfinite(pixels)):
        raise ValueError('Expected finite Nx2 pixel coordinates')
    xy = (pixels-camera['principal_point'])/camera['focal_length']
    radius = np.linalg.norm(xy, axis=-1)
    if np.any(radius > camera['max_valid_distorted_radius']):
        raise ValueError('Pixel outside factory calibrated distortion radius')
    hi = np.full(radius.shape, np.pi/2-1e-7)
    lo = np.zeros(radius.shape)
    if np.any(radius > distorted_radius(hi, camera['distortion_coefficients'])):
        raise ValueError('Pixel outside supported forward lens domain')
    for _ in range(50):
        mid = (lo+hi)/2
        below = distorted_radius(mid, camera['distortion_coefficients']) < radius
        lo = np.where(below, mid, lo)
        hi = np.where(below, hi, mid)
    undistorted_radius = np.tan((lo+hi)/2)
    if np.any(undistorted_radius > camera['max_valid_undistorted_radius']):
        raise ValueError('Ray outside factory calibrated undistorted radius')
    scale = np.divide(undistorted_radius, radius, out=np.ones_like(radius), where=radius>1e-12)
    xy = xy*scale[..., None] + camera.get('distortion_offset', [0, 0])
    rays = np.concatenate([xy, np.ones((*xy.shape[:-1], 1))], axis=-1)
    return rays/np.linalg.norm(rays, axis=-1, keepdims=True)


@lru_cache(maxsize=16)
def _window_lookup(center, radius, thickness, refractive_index):
    """Axisymmetric refraction followed by the native central approximation."""
    distance = float(np.linalg.norm(center))
    if distance <= 0 or distance > radius-thickness/2:
        raise ValueError('Unsupported window centre outside inner sphere')
    cosine = np.linspace(-1., 1., 1000)
    sine = np.sqrt(1-cosine*cosine)
    direction = np.column_stack((cosine, sine))
    origin = np.zeros_like(direction)
    sphere_center = np.array([-distance, 0.])
    for surface, eta in ((radius-thickness/2, 1/refractive_index),
                         (radius+thickness/2, refractive_index)):
        delta = origin-sphere_center
        dot = np.sum(delta*direction, axis=1)
        travel = -dot+np.sqrt(dot*dot-np.sum(delta*delta, axis=1)+surface*surface)
        origin = origin+travel[:, None]*direction
        normal = (origin-sphere_center)/surface
        incidence = np.sum(normal*direction, axis=1)
        direction = eta*direction+(np.sqrt(1-eta*eta*(1-incidence*incidence))
                                   -eta*incidence)[:, None]*normal
        direction /= np.linalg.norm(direction, axis=1)[:, None]
    # The firmware uses a plane one metre along -centre/|centre|, not infinity
    # and not camera z=1. Store the amount to subtract along that axis.
    travel = (1.-origin[:, 0])/direction[:, 0]
    target = origin+travel[:, None]*direction
    correction = cosine-np.divide(sine*target[:, 0], target[:, 1],
                                  out=np.zeros_like(sine), where=sine>0)
    correction[[0, -1]] = 0.  # Native lookup's axial endpoint convention.
    if not np.all(np.isfinite(correction)):
        raise ValueError('Invalid curved-window lookup')
    return cosine, correction


def factory_projection_rays(camera, pixels):
    """Central camera rays for the factory model, suitable for QuestLHSync."""
    rays = lens_rays(camera, pixels)
    w = camera['curved_window']
    center = tuple(w['center'])
    cosine, correction = _window_lookup(center, w['radius'], w['thickness'], w['refractive_index'])
    axis = -np.asarray(center)/np.linalg.norm(center)
    amount = np.interp(rays@axis, cosine, correction)
    rays = rays-amount[:, None]*axis
    return rays/np.linalg.norm(rays, axis=1)[:, None]
