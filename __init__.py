# -*- coding: utf-8 -*-
"""
/******************************************************************************************
 VRI Pivo
                                 A QGIS plugin
 Center Pivot Systems Irrigation
                              -------------------
        begin                : 2025-05-02
        git sha              : $Format:%H$
        copyright            : (C) 2025 by Silas Alves Souza, Romário Moraes Carvalho Neto
                               and Fernando Campos Mendonça
        email                : pluggis.tech@gmail.com
 *****************************************************************************************/
"""

def classFactory(iface): 
    from .pivo import Pivo
    return Pivo(iface)