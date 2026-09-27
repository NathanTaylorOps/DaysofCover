"""Stage 2: the aggregate cover, impact and (later) buffer LPs.

Analytical, not simulated -- kept apart from :mod:`daysofcover.engine`
the same way :mod:`daysofcover.data` is kept apart from it, since this
package answers "what does the network's own structure say" rather
than "what happens day by day". See :mod:`daysofcover.lp.aggregate`.
"""
