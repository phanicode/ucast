# Copyright (C) 2020 Chi-kwan Chan
# Copyright (C) 2020 Steward Observatory
#
# This file is part of `ucast`.
#
# `Ucast` is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# `Ucast` is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with `ucast`.  If not, see <http://www.gnu.org/licenses/>.

import numpy as np

from ...weather.gfs.nomads import levels

# Physical constants
G_STD               = 9.80665  # standard gravity [m / s^2]
M_AIR               = 28.964   # average dry air mass [g / mole]
M_O3                = 47.997   # O3 mass [g / mole]
H2O_SUPERCOOL_LIMIT = 238.     # Assume ice below this temperature [K]
PASCAL_ON_MBAR      = 100.     # conversion from mbar (hPa) to Pa

def column(name, value):
    fu_map = {
        'o3 vmr'          :('.3e', ''        ),
        'h2o RH'          :('.2f', '%'       ),
        'h2o RHi'         :('.2f', '%'       ),
        'lwp_abs_Rayleigh':('.3e', ' kg*m^-2'),
        'iwp_abs_Rayleigh':('.3e', ' kg*m^-2'),
    }
    if value > 0:
        fmt, unit = fu_map[name]
        return f"column {name} {value:{fmt}}{unit}"
    else:
        return None

def layer(Pb, zb, Tb, T, o3_vmr, RH, ctw, cti):
    if T > H2O_SUPERCOOL_LIMIT:
        h2o_label = "h2o RH"
        ctw_label = "lwp_abs_Rayleigh"
    else:
        # Below the supercooling limit, assume any liquid water
        # is really ice.  (GFS 15 occasionally has numerically
        # negligible amounts of liquid water at unphysically
        # low temperature.)
        h2o_label = "h2o RHi"
        ctw_label = "iwp_abs_Rayleigh"
    return '\n'.join(filter(None, [
        "layer",
       f"Pbase {Pb:.1f} mbar  # {zb:.1f} m",
       f"Tbase {Tb:.1f} K",
        "column dry_air vmr",
        column("o3 vmr", o3_vmr),
        column(h2o_label, RH),
        column(ctw_label, ctw),
        column("iwp_abs_Rayleigh", cti),
    ]))

def interpos(a, b, u, log=False):
    if log:
        return np.exp(np.log(a) + np.log(b/a) * u)
    else:
        c = a + (b - a) * u
        return c if c > 0.0 else 0.0

def base(arr, n, u, log=False):
    if u == 0.0:
        return arr[:n]
    else:
        return np.r_[arr[:n], interpos(arr[n-1], arr[n], u, log=log)]

def average(arr, n, u):
    arr = base(arr, n, u)
    return np.r_[arr[0], 0.5 * (arr[:-1]+arr[1:])]

def delta(arr, n, u):
    arr = base(arr, n, u)
    return np.r_[0, arr[1:]-arr[:-1]]

def config(gfs):

    z = gfs.site.alt

    # Prepare for regriding
    if z > gfs.z[0]:
        raise ValueError("User-specified altitude exceeds top GFS level")

    # For pressure, height, and temperature, use the base values.
    # The surface (last) value is interpolated with respect to z
    n = np.argmax(gfs.z < z)
    u = (gfs.z[n-1]-z) / (gfs.z[n-1]-gfs.z[n])

    Pb = base(gfs.P, n, u, log=True)
    zb = base(gfs.z, n, u)
    Tb = base(gfs.T, n, u)

    # For mixing ratios and RH, use averages over the two levels
    # bounding the layer.
    # The surface (last) value is interpolated with respect to P
    u = (gfs.P[n-1]-Pb[-1]) / (gfs.P[n-1]-gfs.P[n])

    T         = average(gfs.T,         n, u)
    o3_vmr    = average(gfs.o3_mmr,    n, u) * (M_AIR/M_O3) # convert mass mixing ratio to volume mixing ratio
    RH        = average(gfs.RH,        n, u)
    cloud_lmr = average(gfs.cloud_lmr, n, u)
    cloud_imr = average(gfs.cloud_imr, n, u)

    # Convert cloud liquid water mixing ratios (lmr) and ice mixing
    # ratio (imr) [kg / kg] to cloud total liquid water (ctw) and
    # cloud total ice (cti) across the layer [kg / m^2].
    m   = delta(Pb, n, u) * (PASCAL_ON_MBAR/G_STD)
    ctw = cloud_lmr * m
    cti = cloud_imr * m

    l = [f"""#
# Layer data below were derived from NCEP GFS model data obtained
# from the NOAA Operational Model Archive Distribution System
# (NOMADS).  See http://nomads.ncep.noaa.gov for more information.
#
#         Production date: {gfs.cycle:%Y%m%d}
#                   Cycle: {gfs.cycle:%H} UT
#                 Product: {gfs.product}
#
# Interpolated to
#
#                latitude: {gfs.site.lat} deg. N
#               longitude: {gfs.site.lon} deg. E
#   Geopotential altitude: {gfs.site.alt} m
#"""]

    for i in range(len(T)):
        l.append(layer(
            Pb[i], zb[i], Tb[i],
            T[i], o3_vmr[i], RH[i], ctw[i], cti[i]))

    return "\n\n".join(l)
