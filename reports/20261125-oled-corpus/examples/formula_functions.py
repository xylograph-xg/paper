"""Generated scalar functions. Input domains are documented per function."""
import math


def quantum_yield(k_r,k_nr):
    """Two nonnegative rates in the same units, with positive sum."""
    return k_r/(k_nr + k_r)


def stretched_luminance(L0,t,tau,beta):
    """Nonnegative time and initial luminance, positive tau and beta. Time and tau use the same units."""
    return L0*math.exp(-(t/tau)**beta)


def field_mobility(mu_zero,field,field_scale):
    """Nonnegative field magnitude and positive field scale in the same units. Output has mobility units."""
    return mu_zero*math.exp(math.sqrt(field/field_scale))

