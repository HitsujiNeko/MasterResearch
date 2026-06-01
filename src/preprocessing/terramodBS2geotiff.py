# coding: utf-8
# Description: This is a file format convertion program from BS-Horizon ascii to GeoTIFF.
#
# Usage: python hori2geotiff.py input output epsg
#   input: BS-Horizon grid data (Terramod-BS output available)
#   output: GeoTIFF
#   epsg: EPSG code
#
# Example:  python terramodBS2geotiff.py ./sample.grd ./sample.tif 5897
#

import sys
import numpy as np
from osgeo import gdal, osr


def readDEM(demfile):
    #open dem
    f = open(demfile,'r')
    
    #read header part
    head = f.readline().strip().split()
    nx = int(head[0])
    ny = int(head[1])
    xmin = float(head[2])
    ymin = float(head[3])
    dx = float(head[4])
    dy = float(head[5])
    
    #read data part
    dem = []
    for i in range(nx):
        d = f.readline().strip().split()
        dem.append(d)
    Z = np.array(dem, dtype=float)
    Z = np.flipud(Z.T)
    #close dem
    f.close()
    
    return nx, ny, xmin, ymin, dx, dy, Z

if __name__ == '__main__':

    #input parameters
    dem = sys.argv[1]
    geotiff = sys.argv[2]
    epsg = int(sys.argv[3])

    nx, ny, xmin, ymin, dx, dy, Z = readDEM(dem)
    xmax = xmin + float(nx - 1) * dx
    ymax = ymin + float(ny - 1) * dy

    #data type
    dtype = gdal.GDT_Float32
    #number of bands
    band = 1
    #Output file
    output = gdal.GetDriverByName('GTiff').Create(geotiff, nx, ny, band, dtype)
    xmin = xmin - 0.5 * dx
    ymax = ymax + 0.5 * dy
    output.SetGeoTransform((xmin, dx, 0, ymax, 0, -dy))
    #Spatial Reference System
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(epsg)
    output.SetProjection(srs.ExportToWkt())

    #NULL value = -9999
    band = output.GetRasterBand(1).WriteArray(Z)
    NoData_value = -9999
    output.GetRasterBand(1).SetNoDataValue(NoData_value)
    #
    output.FlushCache()
    output = None 