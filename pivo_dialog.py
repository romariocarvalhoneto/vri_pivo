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

from qgis.PyQt import uic
from qgis.PyQt import QtWidgets
from qgis.core import (QgsMapLayerProxyModel, QgsMessageLog, Qgis,
                       QgsRectangle, QgsMapLayer, QgsProcessingException,
                       QgsProject, QgsVectorLayer, QgsRasterLayer)
from qgis import processing
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QTableWidgetItem, QDialogButtonBox

import tempfile
import os, re, uuid, time

from osgeo import gdal

FORM_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'pivo_dialog_base.ui'))

class PivoDialog(QtWidgets.QDialog, FORM_CLASS):
    def __init__(self, parent=None):
        """Constructor."""
        super(PivoDialog, self).__init__(parent)
        self.setupUi(self)
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        ok_button.setText("Execute")
        cancel_button = self.button_box.button(QDialogButtonBox.Cancel)
        cancel_button.setText("Cancel")
        self.tab_2.setEnabled(False)
        self.mMapLayerComboBox.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.mMapLayerComboBox_2.setFilters(QgsMapLayerProxyModel.PolygonLayer)
        self.mMapLayerComboBox_3.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.mMapLayerComboBox.layerChanged.connect(self.atualizarCampos)
        self.checkBox_4.stateChanged.connect(self.alternarFileWidget)
        self.checkBox_5.stateChanged.connect(self.alternarFileWidget_2)

        self.checkBox_8.stateChanged.connect(self.alterarTab2)
        self.checkBox_6.setEnabled(False)
        self.checkBox_7.setEnabled(False)

        self.pushButton.clicked.connect(self.load_statistic_table)
        self.pushButton_2.clicked.connect(self.interpolation)

    def atualizarCampos(self):
        layer = self.mMapLayerComboBox.currentLayer()
        self.mFieldComboBox.setLayer(layer)

    def alternarFileWidget(self):
        self.comboBox.setEnabled(self.checkBox_4.isChecked())
        self.checkBox_7.setEnabled(self.checkBox_4.isChecked())

    def alternarFileWidget_2(self):
        self.checkBox_6.setEnabled(self.checkBox_5.isChecked())

    def alterarTab2(self):
        self.mMapLayerComboBox.setEnabled(self.checkBox_8.isChecked())
        self.mFieldComboBox.setEnabled(self.checkBox_8.isChecked())
        self.pushButton.setEnabled(self.checkBox_8.isChecked())
        self.tableWidget.setEnabled(self.checkBox_8.isChecked())
        self.tab_2.setEnabled(self.checkBox_8.isChecked())

    def load_statistic_table(self):
        layer = self.mMapLayerComboBox.currentLayer()
        field_name = self.mFieldComboBox.currentText()

        if layer is None or not field_name:
            QgsMessageLog.logMessage("Select a layer and a field.", "Plugin", level=Qgis.Warning)
            return

        # Runs the algorithm
        res = processing.run("qgis:basicstatisticsforfields", {
            'INPUT_LAYER': layer,
            'FIELD_NAME': field_name,
            'OUTPUT_HTML_FILE': 'TEMPORARY_OUTPUT'
        })

        # Order and user-friendly labels
        ordered_labels = [
            ("MIN", "Minimum value"),
            ("MAX", "Maximum value"),
            ("RANGE", "Range"),
            ("MEAN", "Mean value"),
            ("MEDIAN", "Median value"),
            ("STD_DEV", "Standard deviation"),
            ("FIRSTQUARTILE", "First quartile"),
            ("THIRDQUARTILE", "Third quartile"),
        ]

        # Builds rows present in the result
        rows = [(label, res[key]) for key, label in ordered_labels if key in res]

        # Formats numbers (without trailing .0 and with reasonable precision)
        def fmt(v):
            try:
                fv = float(v)
                return f"{fv:.4f}"  # always 4 decimal places, with zeros if needed
            except Exception:
                return str(v)

        # Populates the QTableWidget
        tw = self.tableWidget
        tw.clear()
        tw.setColumnCount(2)
        tw.setRowCount(len(rows))
        tw.setHorizontalHeaderLabels(["Statistics", "Value"])

        for i, (k, v) in enumerate(rows):
            item_k = QTableWidgetItem(k)
            item_v = QTableWidgetItem(fmt(v))
            item_v.setTextAlignment(Qt.AlignCenter)
            item_k.setFlags(item_k.flags() & ~Qt.ItemIsEditable)
            item_v.setFlags(item_v.flags() & ~Qt.ItemIsEditable)
            tw.setItem(i, 0, item_k)
            tw.setItem(i, 1, item_v)

        tw.resizeColumnsToContents()
        tw.horizontalHeader().setSectionResizeMode(1, tw.horizontalHeader().Stretch)
        tw.horizontalHeader().setStretchLastSection(True)

        if 'OUTPUT_HTML_FILE' in res:
            QgsMessageLog.logMessage(f"HTML: {res['OUTPUT_HTML_FILE']}", "Plugin", level=Qgis.Info)

    def interpolation(self):
        pontos_amostras = self.mMapLayerComboBox.currentLayer()
        poligono_circulo = self.mMapLayerComboBox_2.currentLayer()
        pixel = self.spinBox_5.value()

        FIELD = self.mFieldComboBox.currentText()
        TARGET_USER_SIZE = self.spinBox_5.value()
        TARGET_USER_FITS = self.comboBox_7.currentIndex()

        PREDICTION_sdat, PREDICTION_copy_to_tif = self._saga_grid_out(None, "prediction")
        PREDICTION_nome_layer = "Prediction"

        VARIANCE_sdat, VARIANCE_copy_to_tif = self._saga_grid_out(None, "prediction_error")
        VARIANCE_nome_layer = "Prediction Error"

        TQUALITY = self.comboBox_8.currentIndex()
        CV_METHOD = self.comboBox_9.currentIndex()

        CV_SUMMARY = self._temp_path("dbf", "cv_summary")
        CV_SUMMARY_nome_layer = 'Cross Validation Summary'

        CV_RESIDUALS = self._temp_path("shp", "cv_residuals")
        CV_RESIDUALS_nome_layer = 'Cross Validation Residuals'

        CV_SAMPLES = self.spinBox_8.value()
        SEARCH_POINTS_MIN = self.spinBox_6.value()
        SEARCH_POINTS_MAX = self.spinBox_7.value()

        # === NEW: ensures a physical file and projected CRS (does not reproject by default) ===
        points_path = self._to_physical_projected(pontos_amostras, suffix="krig_points_proj", target_crs=None)

        # Robust extent/GRID: uses the polygon as reference (also validating projected CRS)
        poly_path = self._to_physical_projected(poligono_circulo, suffix="krig_extent_proj", target_crs=None)
        poly_layer_proj = QgsVectorLayer(poly_path, "krig_extent_proj", "ogr")
        if not poly_layer_proj.isValid():
            raise Exception("Failed to prepare the extent layer for kriging.")

        # Generates TARGET_USER_* parameters (uses the provided pixel size; applies slight padding)
        grid_params = self._build_kriging_grid_params(
            poly_layer_proj,
            cellsize=TARGET_USER_SIZE,
            pad_cells=2
        )

        krig_params = {
            'POINTS': points_path,
            'FIELD': FIELD,  # helper duplicates into ATTRIBUTE for compatibility
            'TARGET_DEFINITION': grid_params['TARGET_DEFINITION'],
            'TARGET_USER_XMIN': grid_params['TARGET_USER_XMIN'],
            'TARGET_USER_XMAX': grid_params['TARGET_USER_XMAX'],
            'TARGET_USER_YMIN': grid_params['TARGET_USER_YMIN'],
            'TARGET_USER_YMAX': grid_params['TARGET_USER_YMAX'],
            'TARGET_USER_SIZE': grid_params['TARGET_USER_SIZE'],
            'TARGET_USER_FITS': TARGET_USER_FITS,
            'PREDICTION': PREDICTION_sdat,
            'VARIANCE': VARIANCE_sdat,
            'TQUALITY': TQUALITY,
            'VAR_MAXDIST': 0,
            'VAR_NCLASSES': 100,
            'VAR_NSKIP': 1,
            'VAR_MODEL': 'a + b * x',
            'LOG': False,
            'BLOCK': False,
            'DBLOCK': 100,
            'CV_METHOD': CV_METHOD,
            'CV_SUMMARY': CV_SUMMARY,
            'CV_RESIDUALS': CV_RESIDUALS,
            'CV_SAMPLES': CV_SAMPLES,
            'SEARCH_RANGE': 1,
            'SEARCH_RADIUS': 1000,
            'SEARCH_POINTS_ALL': 0,
            'SEARCH_POINTS_MIN': SEARCH_POINTS_MIN,
            'SEARCH_POINTS_MAX': SEARCH_POINTS_MAX,
        }
        interpol = self._run_saga_ordinary_kriging(krig_params)

        # ### PATCH: ensure GeoTIFF and honor "Save as" ###
        pred_grid_path = PREDICTION_sdat
        pred_tif_path  = self._ensure_gtiff(pred_grid_path, tag=PREDICTION_nome_layer, force_copy=True)

        # If the user requested .tif at a specific path, also copy/translate it there
        if PREDICTION_copy_to_tif:
            self._ensure_dir(PREDICTION_copy_to_tif)
            processing.run("gdal:translate", {
                'INPUT': pred_tif_path,
                'TARGET_CRS': None,
                'NODATA': None,
                'COPY_SUBDATASETS': False,
                'OPTIONS': 'TILED=YES COMPRESS=LZW',
                'EXTRA': '',
                'DATA_TYPE': 0,
                'OUTPUT': PREDICTION_copy_to_tif
            }, is_child_algorithm=True)

        # Now proceed with clipping to the polygon
        pred_layer = processing.run("gdal:cliprasterbymasklayer", {
            'INPUT': pred_tif_path,
            'MASK': poligono_circulo,
            'SOURCE_CRS': None,
            'TARGET_CRS': None,
            'NODATA': -9999,
            'ALPHA_BAND': False,
            'CROP_TO_CUTLINE': True,
            'KEEP_RESOLUTION': False,
            'SET_RESOLUTION': False,
            'X_RESOLUTION': pixel,
            'Y_RESOLUTION': pixel,
            'MULTITHREADING': False,
            'OPTIONS': '',
            'DATA_TYPE': 0,
            'EXTRA': '',
            'OUTPUT': self._temp_tif("pred_clip")   # avoid TEMPORARY_OUTPUT here as well
        })['OUTPUT']

        pred_tif_path  = self._ensure_gtiff(pred_layer, tag=PREDICTION_nome_layer, force_copy=False)
        QgsProject.instance().addMapLayer(QgsRasterLayer(pred_tif_path, PREDICTION_nome_layer))

        # --- Variance ---
        # Same logic: use the stable path passed to SAGA.
        var_grid_path = VARIANCE_sdat
        var_tif_path  = self._ensure_gtiff(var_grid_path, tag=VARIANCE_nome_layer, force_copy=True)

        if VARIANCE_copy_to_tif:
            self._ensure_dir(VARIANCE_copy_to_tif)
            processing.run("gdal:translate", {
                'INPUT': var_tif_path,
                'TARGET_CRS': None,
                'NODATA': None,
                'COPY_SUBDATASETS': False,
                'OPTIONS': 'TILED=YES COMPRESS=LZW',
                'EXTRA': '',
                'DATA_TYPE': 0,
                'OUTPUT': VARIANCE_copy_to_tif
            }, is_child_algorithm=True)

        var_layer = processing.run("gdal:cliprasterbymasklayer", {
            'INPUT': var_tif_path,
            'MASK': poligono_circulo,
            'SOURCE_CRS': None,
            'TARGET_CRS': None,
            'NODATA': -9999,
            'ALPHA_BAND': False,
            'CROP_TO_CUTLINE': True,
            'KEEP_RESOLUTION': False,
            'SET_RESOLUTION': False,
            'X_RESOLUTION': pixel,
            'Y_RESOLUTION': pixel,
            'MULTITHREADING': False,
            'OPTIONS': '',
            'DATA_TYPE': 0,
            'EXTRA': '',
            'OUTPUT': self._temp_tif("var_clip")
        })['OUTPUT']

        var_tif_path  = self._ensure_gtiff(var_layer, tag=VARIANCE_nome_layer, force_copy=False)
        QgsProject.instance().addMapLayer(QgsRasterLayer(var_tif_path, VARIANCE_nome_layer))


        if CV_METHOD != 0:
            # paths returned by SAGA (they should be the same as the ones we passed)
            cv_summary_path   = interpol.get('CV_SUMMARY')
            cv_residuals_path = interpol.get('CV_RESIDUALS')

            # --- CV_SUMMARY (table, e.g. .dbf) ---
            if cv_summary_path and os.path.exists(cv_summary_path):
                cv_summary_lyr = QgsVectorLayer(cv_summary_path, CV_SUMMARY_nome_layer, 'ogr')
                if cv_summary_lyr.isValid():
                    QgsProject.instance().addMapLayer(cv_summary_lyr)
                else:
                    self.iface.messageBar().pushWarning("Pivo", f"Invalid CV Summary: {cv_summary_path}")
            else:
                self.iface.messageBar().pushWarning("Pivo", "CV Summary was not generated by SAGA")

            # --- CV_RESIDUALS (points, e.g. .shp) ---
            if cv_residuals_path and os.path.exists(cv_residuals_path):
                cv_residuals_lyr = QgsVectorLayer(cv_residuals_path, CV_RESIDUALS_nome_layer, 'ogr')
                if cv_residuals_lyr.isValid():
                    QgsProject.instance().addMapLayer(cv_residuals_lyr)
                else:
                    self.iface.messageBar().pushWarning("Pivo", f"Invalid CV Residuals: {cv_residuals_path}")
            else:
                self.iface.messageBar().pushWarning("Pivo", "CV Residuals were not generated by SAGA.")


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
    
    def _to_physical_projected(self, layer, suffix="krig_points_proj", target_crs=None):
        """
        Ensures a physical file and projected CRS (in meters).
        - If the layer is in degrees: raises an exception asking the user to reproject it first.
        - If target_crs is None: does not reproject; only validates that it is projected.
        - If target_crs is provided and different: reprojects to target_crs.
        Returns a physical .gpkg path (projected if applicable).
        """
        # 1) Always forces a physical file (uses the helper from patch #1 already implemented)
        tmp_gpkg = self._to_physical_gpkg(layer, suffix=f"{suffix}_raw")

        src = QgsVectorLayer(tmp_gpkg, "src", "ogr")
        if not src.isValid():
            raise Exception("Failed to reopen the saved temporary layer.")

        if not src.crs().isValid() or src.crs().isGeographic():
            raise QgsProcessingException(
                "The point layer is in geographic coordinates (degrees)."
                "Reproject it to a projected CRS (in meters), for example UTM/SIRGAS 2000, and try again."
            )

        # 2) Reproject only if explicitly requested and different
        if target_crs and target_crs.isValid() and (src.crs() != target_crs):
            out_gpkg = self._temp_path("gpkg", suffix)
            processing.run(
                "native:reprojectlayer",
                {"INPUT": tmp_gpkg, "TARGET_CRS": target_crs, "OPERATION": "", "OUTPUT": out_gpkg},
                is_child_algorithm=True,
            )
            return out_gpkg

        # 3) It is already projected and no change was requested
        return tmp_gpkg
    
    def _build_kriging_grid_params(self, ref_layer, cellsize=None, pad_cells=2):
        """
        Builds TARGET_USER_* parameters for sagang:ordinarykriging in a robust way.
        - ref_layer: layer ALREADY in a projected CRS (meters).
        - cellsize: pixel size (m). If None, it is estimated from the extent/size.
        - pad_cells: expands the extent by N cells to avoid a "cropped" edge.
        Returns: dict with TARGET_DEFINITION, TARGET_USER_XMIN/XMAX/YMIN/YMAX, TARGET_USER_SIZE, TARGET_USER_FITS.
        """
        if not hasattr(ref_layer, "extent"):
            raise Exception("Reference layer has no valid extent to define the grid.")

        ext = ref_layer.extent()

        # Estimates cellsize if not provided
        if cellsize is None:
            if ref_layer.type() == QgsMapLayer.RasterLayer:
                try:
                    prov = ref_layer.dataProvider()
                    if prov and prov.xSize() > 0 and prov.ySize() > 0:
                        cellsize = max(
                            abs(ext.width() / prov.xSize()),
                            abs(ext.height() / prov.ySize()),
                        )
                except Exception:
                    cellsize = None
            if cellsize is None or cellsize <= 0:
                cellsize = max(ext.width(), ext.height()) / 500.0  # safe heuristic

        cell = self._format_float(cellsize)

        # Padding in meters
        if pad_cells and pad_cells > 0:
            grow = float(pad_cells) * cell
            ext_g = QgsRectangle(ext)
            ext_g.grow(grow)
        else:
            ext_g = ext

        return {
            "TARGET_DEFINITION": 1,  # User Defined
            "TARGET_USER_XMIN": self._format_float(ext_g.xMinimum()),
            "TARGET_USER_XMAX": self._format_float(ext_g.xMaximum()),
            "TARGET_USER_YMIN": self._format_float(ext_g.yMinimum()),
            "TARGET_USER_YMAX": self._format_float(ext_g.yMaximum()),
            "TARGET_USER_SIZE": cell,
            "TARGET_USER_FITS": 0,   # 0 = cell centers (stable)
        }
    
    def _run_saga_ordinary_kriging(self, params: dict):
        """
        Runs kriging with provider fallback (sagang -> saga).
        Duplicates the attribute in FIELD/ATTRIBUTE for compatibility.
        """
        p = dict(params)
        # compat: some versions use ATTRIBUTE instead of FIELD
        if 'FIELD' in p and 'ATTRIBUTE' not in p:
            p['ATTRIBUTE'] = p['FIELD']

        try:
            return processing.run("sagang:ordinarykriging", p)
        except Exception:
            return processing.run("saga:ordinarykriging", p)
        
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
    
    def _ensure_dir(self, path: str):
        """Ensures that the folder for 'path' exists."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        except Exception:
            pass

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
    
    def _to_physical_gpkg(self, layer, suffix="krig_points"):
        """Exports any layer (memory/virtual/WFS etc.) to a temporary .gpkg file
        and returns the physical file path (avoids SAGA failures)."""
        tmp_path = self._temp_path("gpkg", suffix)
        res = processing.run(
            "native:savefeatures",
            {"INPUT": layer, "OUTPUT": tmp_path},
            is_child_algorithm=True,
        )
        return res["OUTPUT"]
    
    def _format_float(self, v, nd=6):
        """Normalizes float with decimal point and limits digits to avoid huge strings."""
        return float(f"{float(v):.{nd}f}")
