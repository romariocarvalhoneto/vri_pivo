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

from qgis.PyQt.QtCore import QSettings, QTranslator, QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction
from qgis.core import ( QgsVectorLayer, QgsFeature, QgsGeometry, QgsProject, QgsRasterLayer,
                        QgsStyle, QgsFeatureRequest, QgsFillSymbol, QgsDistanceArea,
                        QgsRendererCategory, 
                        QgsField, edit, QgsPointXY, QgsCategorizedSymbolRenderer,
                        QgsWkbTypes, QgsSpatialIndex, QgsGradientColorRamp,
                        QgsProcessingException,)

from qgis.PyQt.QtGui import QColor
from PyQt5.QtCore import QVariant

import tempfile
import os, re, uuid, time
from math import radians, cos, sin
from .resources import *
from .pivo_dialog import PivoDialog
import os.path
from qgis import processing
from osgeo import gdal


class Pivo:
    """QGIS Plugin Implementation."""

    def __init__(self, iface):
        """Constructor.

        :param iface: An interface instance that will be passed to this class
            which provides the hook by which you can manipulate the QGIS
            application at run time.
        :type iface: QgsInterface
        """
        # Save reference to the QGIS interface
        self.iface = iface
        # initialize plugin directory
        self.plugin_dir = os.path.dirname(__file__)
        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'Pivo_{}.qm'.format(locale))

        if os.path.exists(locale_path):
            self.translator = QTranslator()
            self.translator.load(locale_path)
            QCoreApplication.installTranslator(self.translator)

        # Declare instance attributes
        self.actions = []
        self.menu = self.tr(u'&VRI Pivo')

        # Check if plugin was started the first time in current QGIS session
        # Must be set in initGui() to survive plugin reloads
        self.first_start = None

    # noinspection PyMethodMayBeStatic
    def tr(self, message):
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('VRI Pivo', message)


    def add_action(
        self,
        icon_path,
        text,
        callback,
        enabled_flag=True,
        add_to_menu=True,
        add_to_toolbar=True,
        status_tip=None,
        whats_this=None,
        parent=None):
        """Add a toolbar icon to the toolbar.

        :param icon_path: Path to the icon for this action. Can be a resource
            path (e.g. ':/plugins/foo/bar.png') or a normal file system path.
        :type icon_path: str

        :param text: Text that should be shown in menu items for this action.
        :type text: str

        :param callback: Function to be called when the action is triggered.
        :type callback: function

        :param enabled_flag: A flag indicating if the action should be enabled
            by default. Defaults to True.
        :type enabled_flag: bool

        :param add_to_menu: Flag indicating whether the action should also
            be added to the menu. Defaults to True.
        :type add_to_menu: bool

        :param add_to_toolbar: Flag indicating whether the action should also
            be added to the toolbar. Defaults to True.
        :type add_to_toolbar: bool

        :param status_tip: Optional text to show in a popup when mouse pointer
            hovers over the action.
        :type status_tip: str

        :param parent: Parent widget for the new action. Defaults None.
        :type parent: QWidget

        :param whats_this: Optional text to show in the status bar when the
            mouse pointer hovers over the action.

        :returns: The action that was created. Note that the action is also
            added to self.actions list.
        :rtype: QAction
        """

        icon = QIcon(icon_path)
        action = QAction(icon, text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if status_tip is not None:
            action.setStatusTip(status_tip)

        if whats_this is not None:
            action.setWhatsThis(whats_this)

        if add_to_toolbar:
            # Adds plugin icon to Plugins toolbar
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(
                self.menu,
                action)

        self.actions.append(action)

        return action

    def initGui(self):
        """Create the menu entries and toolbar icons inside the QGIS GUI."""

        icon_path = ':/plugins/pivo/icon.png'
        self.add_action(
            icon_path,
            text=self.tr(u'Center Pivot Irrigation'),
            callback=self.run,
            parent=self.iface.mainWindow())

        # will be set False in run()
        self.first_start = True


    def unload(self):
        """Removes the plugin menu item and icon from QGIS GUI."""
        for action in self.actions:
            self.iface.removePluginMenu(
                self.tr(u'&VRI Pivo'),
                action)
            self.iface.removeToolBarIcon(action)


    def dividir_em_fatias_pizza(self, geom: QgsGeometry, passo_graus: int):
        # Ensures that it is dealing with the first polygon (in case of MultiPolygon)
        if QgsWkbTypes.isMultiType(geom.wkbType()):
            partes = geom.asGeometryCollection()
            if not partes:
                raise Exception("Geometria MultiPolygon vazia.")
            geom = partes[0]

        # Gets coordinates from the main polygon
        poligono = geom.asPolygon() or geom.asPolygonZ() or geom.asPolygonM()
        if not poligono:
            raise Exception("The provided geometry is not a valid polygon.")

        # Extracts the center point (centroid)
        centroide = geom.centroid().asPoint()

        # Defines radius as the distance to the first border point
        ponto_borda = poligono[0][0]
        raio = QgsPointXY(centroide).distance(QgsPointXY(ponto_borda))

        # Generates the slices
        fatias = []
        for angulo in range(0, 360, passo_graus):
            ang_rad_inicio = radians(angulo)
            ang_rad_fim = radians(angulo + passo_graus)

            # Calculates two points on the circle border
            p1 = QgsPointXY(
                centroide.x() + raio * cos(ang_rad_inicio),
                centroide.y() + raio * sin(ang_rad_inicio)
            )
            p2 = QgsPointXY(
                centroide.x() + raio * cos(ang_rad_fim),
                centroide.y() + raio * sin(ang_rad_fim)
            )

            # Creates a triangle (pizza slice) and intersects it with the original polygon
            triangulo = QgsGeometry.fromPolygonXY([[QgsPointXY(centroide), p1, p2, QgsPointXY(centroide)]])
            intersecao = triangulo.intersection(geom)

            if not intersecao.isEmpty():
                fatias.append(intersecao)

        return fatias
    
    
    def raster_media_por_fatia_e_rasterizar_temporario(self, cam_fatias, raster_path):
        campo_media = 'media_px'

        # Adds mean field if needed
        if campo_media not in [f.name() for f in cam_fatias.fields()]:
            cam_fatias.dataProvider().addAttributes([QgsField(campo_media, QVariant.Double)])
            cam_fatias.updateFields()

        # Processes each slice individually
        with edit(cam_fatias):
            for feat in cam_fatias.getFeatures():
                id_feat = feat.id()
                geom = feat.geometry()

                # Creates a temporary layer with the current slice
                temp_layer = QgsVectorLayer('Polygon?crs=' + cam_fatias.crs().authid(), 'temp', 'memory')
                temp_provider = temp_layer.dataProvider()
                temp_provider.addAttributes([QgsField("id", QVariant.Int)])
                temp_layer.updateFields()

                nova_feat = QgsFeature()
                nova_feat.setGeometry(geom)
                nova_feat.setAttributes([0])
                temp_provider.addFeature(nova_feat)
                temp_layer.updateExtents()

                # Clips the raster with the isolated slice
                out_path = self._temp_tif(f"clip_{id_feat}")
                clip_result = processing.run("gdal:cliprasterbymasklayer", {
                    'INPUT': raster_path,
                    'MASK': temp_layer,
                    'SOURCE_CRS': cam_fatias.crs().authid(),
                    'TARGET_CRS': None,
                    'NODATA': -9999,
                    'ALPHA_BAND': False,
                    'CROP_TO_CUTLINE': True,
                    'KEEP_RESOLUTION': True,
                    'SET_RESOLUTION': False,
                    'OPTIONS': '',
                    'DATA_TYPE': 5,
                    'OUTPUT': out_path
                })

                # Statistics of the rasterized slice
                stats = processing.run("qgis:rasterlayerstatistics", {
                    'INPUT': clip_result['OUTPUT'],
                    'BAND': 1
                })

                media = stats['MEAN']
                cam_fatias.changeAttributeValue(id_feat, cam_fatias.fields().indexOf(campo_media), media)

        # Rasterizes the vector with mean values
        out_path = self._temp_tif("rasterize")
        rasterizado = processing.run("gdal:rasterize", {
            'INPUT': cam_fatias,
            'FIELD': campo_media,
            'BURN': 0,
            'UNITS': 1,
            'WIDTH': 10,  # adjust as needed
            'HEIGHT': 10,
            'EXTENT': cam_fatias.extent(),
            'NODATA': -9999,
            'DATA_TYPE': 5,
            'INIT': None,
            'INVERT': False,
            'EXTRA': '',
            'OUTPUT': out_path
        })

        return rasterizado['OUTPUT']


    def transferir_valores_ponto_para_poligono(self, layer_pontos, layer_poligonos, campo_origem='SPEEDfirst', campo_destino='SPEED'):
        if not layer_poligonos or not layer_pontos:
            print("Error: invalid layer.")
            return

        if layer_poligonos.fields().indexOf(campo_destino) == -1:
            layer_poligonos.startEditing()
            layer_poligonos.dataProvider().addAttributes([QgsField(campo_destino, QVariant.Double)])
            layer_poligonos.updateFields()
            layer_poligonos.commitChanges()

        index = QgsSpatialIndex(layer_poligonos.getFeatures())
        valores_por_poligono = {}

        for ponto_feat in layer_pontos.getFeatures():
            geom_ponto = ponto_feat.geometry()
            valor = ponto_feat[campo_origem]

            ids_possiveis = index.intersects(geom_ponto.boundingBox())
            for fid in ids_possiveis:
                poligono = next(layer_poligonos.getFeatures(QgsFeatureRequest(fid)))
                if poligono.geometry().contains(geom_ponto):
                    valores_por_poligono[poligono.id()] = valor
                    break

        layer_poligonos.startEditing()
        idx_campo = layer_poligonos.fields().indexOf(campo_destino)
        for feat in layer_poligonos.getFeatures():
            fid = feat.id()
            if fid in valores_por_poligono:
                layer_poligonos.changeAttributeValue(fid, idx_campo, valores_por_poligono[fid])
        layer_poligonos.commitChanges()


    def _ensure_gtiff(self, raster_path: str, tag: str = None, force_copy: bool = False) -> str:
        """
        Ensures a GeoTIFF with a UNIQUE NAME.
        - If it is already .tif and force_copy=False: returns the original.
        - Otherwise, creates a faithful copy (.tif) with a unique name.
        """
        is_tif = raster_path.lower().endswith(".tif")
        if is_tif and not force_copy:
            return raster_path

        # readable prefix (or 'preserve' if there is none)
        stem = os.path.splitext(os.path.basename(raster_path))[0] or "preserve"
        base = f"{tag}_{stem}" if tag else stem
        out_tif = self._temp_tif(base)

        # tries via Processing (gdal:translate); if there is no provider, falls back to GDAL
        try:
            processing.run("gdal:translate", {
                'INPUT': raster_path,
                'TARGET_CRS': None,
                'NODATA': None,
                'COPY_SUBDATASETS': False,
                'OPTIONS': 'TILED=YES COMPRESS=LZW',
                'EXTRA': '',
                'DATA_TYPE': 0,      # keeps dtype
                'OUTPUT': out_tif
            })
            return out_tif
        except Exception:
            pass

        # Pure GDAL fallback (CreateCopy) preserving data
        src = gdal.Open(raster_path, gdal.GA_ReadOnly)
        if src is None:
            return raster_path  # last resort
        drv = gdal.GetDriverByName('GTiff')
        dst = drv.CreateCopy(out_tif, src, strict=0, options=['TILED=YES', 'COMPRESS=LZW'])
        # (preserves NoData per band)
        for i in range(1, src.RasterCount + 1):
            nb = src.GetRasterBand(i).GetNoDataValue()
            if nb is not None:
                dst.GetRasterBand(i).SetNoDataValue(nb)
        dst.FlushCache()
        del dst, src
        return out_tif

    def _temp_tif(self, base: str = "out") -> str:
        """
        Generates a unique .tif name in a system folder (tempfile),
        *outside* the QGIS processing_* folder.
        """
        safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(base))[:40]
        uniq = f"{safe}_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}.tif"
        temp_dir = tempfile.gettempdir()
        out_path = os.path.join(temp_dir, uniq)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        return out_path


    def _run_saga_kmeans_rasters(self, grids_path, cluster_path, stats_path,
                                method, ncluster, maxiter, normalise, initialize):
        """
        Runs K-means for rasters with provider fallback (sagang -> saga).
        - Ensures GRIDS with a short .tif path (force_copy=True).
        """
        # Ensures short/stable input (avoids problems on sensitive PCs)
        grids_in = self._ensure_gtiff(grids_path, tag="kmeans_in", force_copy=True)

        params = {
            'GRIDS': [grids_in],
            'CLUSTER': cluster_path,
            'STATISTICS': stats_path,
            'METHOD': method,
            'NCLUSTER': ncluster,
            'MAXITER': maxiter,
            'NORMALISE': normalise,
            'INITIALIZE': initialize,
        }

        # Tries NextGen
        try:
            return processing.run("sagang:kmeansclusteringforrasters", params)
        except Exception:
            # Legacy fallback
            return processing.run("saga:kmeansclusteringforrasters", params)


    def _temp_path(self, ext: str, base: str = "out") -> str:
        """
        Generates a temporary path with an arbitrary extension (gpkg, shp, dbf, csv, etc.)
        in a system folder (tempfile), *outside* the QGIS processing_* folder.
        """
        ext = (ext or "").lstrip(".").lower()
        if not ext:
            ext = "tmp"

        safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(base))[:40]
        uniq = f"{safe}_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}.{ext}"
        temp_dir = tempfile.gettempdir()
        out_path = os.path.join(temp_dir, uniq)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        return out_path


    # ### PATCH: stable I/O helpers ###

    def _ensure_dir(self, path: str):
        """Ensures that the folder for 'path' exists."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        except Exception:
            pass

    def _saga_grid_out(self, user_path: str, default_base: str):
        """
        Normalizes a SAGA GRID output path.
        Returns (sdat_path_for_saga, final_path_to_copy_a_tif_version_or_None).

        Rules:
        - If the user did not choose a path: creates .sdat in our temporary folder.
        - If the user chose .tif: SAGA writes to our temporary .sdat and,
        then we translate/copy it to the user's .tif.
        - If the chosen extension is .sdat (or any other): forces .sdat.
        """
        if not user_path:
            # no user selection -> our temporary sdat
            sdat_out = self._temp_path("sdat", default_base)
            return sdat_out, None

        user_path = os.path.abspath(user_path)
        self._ensure_dir(user_path)

        root, ext = os.path.splitext(user_path)
        ext = (ext or "").lower()

        if ext == ".tif":
            # user wants .tif, but SAGA writes grid -> we output .sdat and then translate/copy to .tif
            sdat_out = self._temp_path("sdat", default_base)
            return sdat_out, user_path

        # Any other case -> force .sdat in the user's path
        if ext != ".sdat":
            user_path = root + ".sdat"
        return user_path, None


    def estatistica_final(self, raster, poligono_dissolvido):
        """
        Calculates statistics by polygon:
        - Converts raster to points (pixelstopoints)
        - Adds field 'ha' with area in hectares
        - Removes auxiliary columns
        - Performs spatial join of point statistics into the polygons
        Returns a QgsVectorLayer ready to be used (e.g. for styling).
        """

        # --- normalize input: it can be a path (str) or QgsVectorLayer ---
        if isinstance(poligono_dissolvido, str):
            layer = QgsVectorLayer(poligono_dissolvido, "dissolvido", "ogr")
            if not layer.isValid():
                raise QgsProcessingException(
                    f"Could not load the dissolved layer: {poligono_dissolvido}"
                )
        else:
            layer = poligono_dissolvido

        # columns we want to remove later
        colunas_deletar = ['id', 'media_px', 'fid']
        colunas_deletar_presentes = [
            f.name() for f in layer.fields() if f.name() in colunas_deletar
        ]

        # raster -> points
        pix_2_pt = processing.run(
            "native:pixelstopoints",
            {
                'INPUT_RASTER': raster,
                'RASTER_BAND': 1,
                'FIELD_NAME': 'VALUE',
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
        )

        # --- adds field 'ha' if it does not exist ---
        if layer.fields().indexOf('ha') == -1:
            layer.dataProvider().addAttributes([
                QgsField('ha', QVariant.Double, 'double', 20, 4)
            ])
            layer.updateFields()

        # --- ellipsoidal area calculation in hectares ---
        d = QgsDistanceArea()
        d.setSourceCrs(layer.crs(), QgsProject.instance().transformContext())
        ellipsoid = QgsProject.instance().ellipsoid() or 'WGS84'
        d.setEllipsoid(ellipsoid)

        with edit(layer):
            idx_ha = layer.fields().indexOf('ha')
            for f in layer.getFeatures():
                area_m2 = d.measureArea(f.geometry())
                layer.changeAttributeValue(f.id(), idx_ha, round(area_m2 / 10000.0, 4))

        # removes auxiliary columns (id, media_px, fid) if they exist

        try:
            remover_id_media_px = processing.run(
                "native:deletecolumn",
                {
                    'INPUT': layer,
                    'COLUMN': colunas_deletar_presentes,
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                }
            )['OUTPUT']
        except:
            remover_id_media_px = layer

        # joins point statistics into the polygons
        gerar_stat = processing.run(
            "qgis:joinbylocationsummary",
            {
                'INPUT': remover_id_media_px,
                'JOIN': pix_2_pt['OUTPUT'],
                'PREDICATE': [0, 5],
                'JOIN_FIELDS': ['VALUE'],
                'SUMMARIES': [2, 3, 4, 6, 7, 8, 11, 12],
                'DISCARD_NONMATCHING': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
        )

        # joins point statistics into the polygons
        gerar_stat = processing.run(
            "qgis:joinbylocationsummary",
            {
                'INPUT': remover_id_media_px,
                'JOIN': pix_2_pt['OUTPUT'],
                'PREDICATE': [0, 5],
                'JOIN_FIELDS': ['VALUE'],
                'SUMMARIES': [2, 3, 4, 6, 7, 8, 11, 12],
                'DISCARD_NONMATCHING': False,
                'OUTPUT': 'TEMPORARY_OUTPUT'
            }
        )

        out_obj = gerar_stat['OUTPUT']

        # --- here we handle both scenarios: path or layer ---
        if isinstance(out_obj, QgsVectorLayer):
            out_layer = out_obj
        else:
            out_layer = QgsVectorLayer(out_obj, layer.name(), "ogr")

        if not out_layer.isValid():
            raise QgsProcessingException(
                "Failed to load the result of the final statistics join."
            )

        return out_layer

    
    def run(self):
        """Run method that performs all the real work"""

        # Create the dialog with elements (after translation) and keep reference
        # Only create GUI ONCE in callback, so that it will only load when the plugin is started
        if self.first_start == True:
            self.first_start = False
            self.dlg = PivoDialog()

        self.dlg.show()
        result = self.dlg.exec_()
        if result:
            self.pasta_trabalho = ""
            pontos_amostras = self.dlg.mMapLayerComboBox.currentLayer()
            poligono_circulo = self.dlg.mMapLayerComboBox_2.currentLayer()
            crs = pontos_amostras.crs()
            codigo_EPSG = crs.authid()
            pixel = self.dlg.spinBox_5.value()

            extent = poligono_circulo.extent()
            xmax = extent.xMaximum()
            ymax = extent.yMaximum()
            xmin = extent.xMinimum()
            ymin = extent.yMinimum()

            # Gets the polygon from the layer
            layer = poligono_circulo
            feature = next(layer.getFeatures())
            geom = feature.geometry()

            if self.dlg.comboBox.currentIndex() == 0:
                graus_fatias = 1
            elif self.dlg.comboBox.currentIndex() == 1:
                graus_fatias = 5
            fatias = self.dividir_em_fatias_pizza(geom, graus_fatias)  # 5 or 1

            # Creates a memory layer to display
            fatias_layer = QgsVectorLayer('Polygon?crs=' + layer.crs().authid(), 'Slices', 'memory')
            prov = fatias_layer.dataProvider()
            prov.addAttributes([QgsField('id', QVariant.Int)])
            fatias_layer.updateFields()

            for i, f in enumerate(fatias):
                feat = QgsFeature()
                feat.setGeometry(f)
                feat.setAttributes([i])
                prov.addFeature(feat)

            raster_interpol_path = self.dlg.mMapLayerComboBox_3.currentLayer().source()
            raster_interpol_path = self._ensure_gtiff(raster_interpol_path)

                    
            ### ----- Cluster ---------
            if self.dlg.checkBox_4.isChecked():
                pizza_rasterizada_path = self.raster_media_por_fatia_e_rasterizar_temporario(fatias_layer, raster_interpol_path)
                GRIDS = pizza_rasterizada_path 

                CLUSTER_sdat, CLUSTER_copy_to_tif = self._saga_grid_out(None, "kmeans_cluster")
                CLUSTER_nome_layer = "VRI Speed Control"  # or "VRI Zone Control" in the second block

                STATISTICS = self._temp_path("dbf", "kmeans_stats")
                STATISTICS_nome_layer = "Speed Control Statistics"


                METHOD = self.dlg.comboBox_2.currentIndex()
                NCLUSTER = self.dlg.spinBox.value()
                MAXITER = self.dlg.spinBox_2.value()
                NORMALISE = self.dlg.checkBox.isChecked()
                INITIALIZE = self.dlg.comboBox_3.currentIndex()

                cluster = self._run_saga_kmeans_rasters(
                    grids_path=GRIDS,
                    cluster_path=CLUSTER_sdat,
                    stats_path=STATISTICS,
                    method=METHOD,
                    ncluster=NCLUSTER,
                    maxiter=MAXITER,
                    normalise=NORMALISE,
                    initialize=INITIALIZE
                )

                cluster_tif = self._ensure_gtiff(cluster["CLUSTER"], tag=CLUSTER_nome_layer, force_copy=True)
                if CLUSTER_copy_to_tif:
                    self._ensure_dir(CLUSTER_copy_to_tif)
                    processing.run("gdal:translate", {
                        'INPUT': cluster_tif,
                        'TARGET_CRS': None, 'NODATA': None,
                        'COPY_SUBDATASETS': False,
                        'OPTIONS': 'TILED=YES COMPRESS=LZW',
                        'EXTRA': '',
                        'DATA_TYPE': 0,
                        'OUTPUT': CLUSTER_copy_to_tif
                    }, is_child_algorithm=True)

                cluster_raster_speed = QgsRasterLayer(cluster_tif, CLUSTER_nome_layer)
                QgsProject.instance().addMapLayer(cluster_raster_speed)
                
                if self.dlg.checkBox_7.isChecked():
                    cluster_speed_statistics = QgsVectorLayer(cluster["STATISTICS"], STATISTICS_nome_layer,"ogr")
                    QgsProject.instance().addMapLayer(cluster_speed_statistics)

                centroids_fatias = processing.run("native:centroids", {'INPUT':fatias_layer,
                                                                        'ALL_PARTS':False,
                                                                        'OUTPUT':'TEMPORARY_OUTPUT'})

                drape = processing.run("native:setzfromraster", {'INPUT':centroids_fatias['OUTPUT'],
                                                                'RASTER':cluster_raster_speed,
                                                                'BAND':1,
                                                                'NODATA':0,
                                                                'SCALE':1,
                                                                'OUTPUT':'TEMPORARY_OUTPUT'})

                z_value = processing.run("native:extractzvalues", {'INPUT':drape['OUTPUT'],
                                                                    'SUMMARIES':[0],
                                                                    'COLUMN_PREFIX':'SPEED',
                                                                    'OUTPUT':'TEMPORARY_OUTPUT'})

                self.transferir_valores_ponto_para_poligono(z_value['OUTPUT'], fatias_layer)

                QgsProject.instance().addMapLayer(fatias_layer)

                fatias_dissolvido = processing.run("native:dissolve", {'INPUT':fatias_layer,
                                                                'FIELD':['SPEED'],
                                                                'OUTPUT':'TEMPORARY_OUTPUT'})['OUTPUT']
                
                fatias_dissolvido = self.estatistica_final(raster_interpol_path, fatias_dissolvido)

                ## style
                field_name = "VALUE_mean"

                style = QgsStyle().defaultStyle()
                ramp = style.colorRamp("Blues")
                if ramp is None:
                    # fallback if the 'Blues' ramp does not exist
                    ramp = QgsGradientColorRamp(QColor("#f7fbff"), QColor("#08306b"))

                # Base symbol (to keep outline consistent)
                base_symbol = QgsFillSymbol.createSimple({
                    "outline_color": "#333333",
                    "outline_width": "0.26"
                })

                # Unique field values (sorted), ignoring nulls
                field_idx = fatias_dissolvido.fields().indexFromName(field_name)
                unique_vals = sorted(v for v in fatias_dissolvido.uniqueValues(field_idx) if v is not None)

                # Builds categories: one ramp color for each value
                n = max(1, len(unique_vals))
                categories = []
                for i, val in enumerate(unique_vals):
                    t = 0.5 if n == 1 else i / (n - 1)  # distributes colors from 0..1
                    color = ramp.color(t)

                    sym = base_symbol.clone()
                    sym.setColor(color)

                    # inside the loop that creates categories, replace the label line with:
                    if isinstance(val, (int, float)) and float(val).is_integer():
                        label = str(int(val))   # shows 1 instead of 1.0
                    else:
                        label = str(val)  # legend label
                    cat = QgsRendererCategory(val, sym, label)
                    categories.append(cat)

                renderer = QgsCategorizedSymbolRenderer(field_name, categories)

                # Applies to the layer
                fatias_dissolvido.setRenderer(renderer)
                fatias_dissolvido.triggerRepaint()
                fatias_dissolvido.setName(CLUSTER_nome_layer)
                QgsProject.instance().addMapLayer(fatias_dissolvido)

            if self.dlg.checkBox_5.isChecked():

                GRIDS = raster_interpol_path

                CLUSTER_sdat, CLUSTER_copy_to_tif = self._saga_grid_out(None, "kmeans_zone_cluster")
                CLUSTER_nome_layer = "VRI Zone Control"

                STATISTICS = self._temp_path("dbf", "kmeans_zone_stats")
                STATISTICS_nome_layer = "Zone Control Statistics"

                METHOD = self.dlg.comboBox_2.currentIndex()
                NCLUSTER = self.dlg.spinBox.value()
                MAXITER = self.dlg.spinBox_2.value()
                NORMALISE = self.dlg.checkBox.isChecked()
                INITIALIZE = self.dlg.comboBox_3.currentIndex()

                cluster = self._run_saga_kmeans_rasters(
                    grids_path=GRIDS,
                    cluster_path=CLUSTER_sdat,
                    stats_path=STATISTICS,
                    method=METHOD,
                    ncluster=NCLUSTER,
                    maxiter=MAXITER,
                    normalise=NORMALISE,
                    initialize=INITIALIZE
                )

                cluster_tif = self._ensure_gtiff(cluster["CLUSTER"], tag=CLUSTER_nome_layer, force_copy=True)
                if CLUSTER_copy_to_tif:
                    self._ensure_dir(CLUSTER_copy_to_tif)
                    processing.run("gdal:translate", {
                        'INPUT': cluster_tif,
                        'TARGET_CRS': None, 'NODATA': None,
                        'COPY_SUBDATASETS': False,
                        'OPTIONS': 'TILED=YES COMPRESS=LZW',
                        'EXTRA': '',
                        'DATA_TYPE': 0,
                        'OUTPUT': CLUSTER_copy_to_tif
                    }, is_child_algorithm=True)

                cluster_raster_zone = QgsRasterLayer(cluster_tif, CLUSTER_nome_layer)
                QgsProject.instance().addMapLayer(cluster_raster_zone)

                # --- Polygonizes zones using TEMPORARY_OUTPUT (lets Processing manage it) ---
                poly_res = processing.run("native:pixelstopolygons", {
                    'INPUT_RASTER':cluster_raster_zone,
                    'RASTER_BAND':1,
                    'FIELD_NAME':'zone',
                    'OUTPUT':'TEMPORARY_OUTPUT'})

                poligonizar_zonas = poly_res['OUTPUT']

                # --- Dissolves zones also into TEMPORARY_OUTPUT ---
                zonas_res = processing.run("native:dissolve", {
                    'INPUT': poligonizar_zonas,
                    'FIELD': ['zone'],
                    'OUTPUT': 'TEMPORARY_OUTPUT'
                })
                zonas_dissolvido = zonas_res['OUTPUT']

                zonas_dissolvido = self.estatistica_final(raster_interpol_path, zonas_dissolvido)

                ## style
                field_name = "VALUE_mean"

                style = QgsStyle().defaultStyle()
                ramp = style.colorRamp("Blues")
                if ramp is None:
                    # fallback if the 'Blues' ramp does not exist
                    ramp = QgsGradientColorRamp(QColor("#f7fbff"), QColor("#08306b"))

                # Base symbol (to keep outline consistent)
                base_symbol = QgsFillSymbol.createSimple({
                    "outline_color": "#333333",
                    "outline_width": "0.26"
                })

                # Unique field values (sorted), ignoring nulls
                field_idx = zonas_dissolvido.fields().indexFromName(field_name)
                unique_vals = sorted(v for v in zonas_dissolvido.uniqueValues(field_idx) if v is not None)

                # Builds categories: one ramp color for each value
                n = max(1, len(unique_vals))
                categories = []
                for i, val in enumerate(unique_vals):
                    t = 0.5 if n == 1 else i / (n - 1)  # distributes colors from 0..1
                    color = ramp.color(t)

                    sym = base_symbol.clone()
                    sym.setColor(color)

                    # inside the loop that creates categories, replace the label line with:
                    if isinstance(val, (int, float)) and float(val).is_integer():
                        label = str(int(val))   # shows 1 instead of 1.0
                    else:
                        label = str(val)  # legend label
                    cat = QgsRendererCategory(val, sym, label)
                    categories.append(cat)

                renderer = QgsCategorizedSymbolRenderer(field_name, categories)

                # Applies to the layer
                zonas_dissolvido.setRenderer(renderer)
                zonas_dissolvido.triggerRepaint()
                zonas_dissolvido.setName(CLUSTER_nome_layer)
                QgsProject.instance().addMapLayer(zonas_dissolvido)
                
                if self.dlg.checkBox_6.isChecked():
                    cluster_statistics = QgsVectorLayer(cluster["STATISTICS"],STATISTICS_nome_layer,"ogr")
                    QgsProject.instance().addMapLayer(cluster_statistics)
