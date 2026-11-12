"""Read MODIS HDF4 and VIIRS NetCDF4/HDF5 swaths without loading unused rows."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from vela.geo import in_bbox, local_hour

FIRE_NAMES = ("fire mask", "firemask", "fire_mask")
LAT_NAMES = ("latitude", "lat")
LON_NAMES = ("longitude", "lon")
ZENITH_NAMES = ("solarzenith", "solar_zenith", "solar zenith")


def _normal_name(name: str) -> str:
    return " ".join(name.lower().replace("_", " ").split())


def _scalar(value, default: float) -> float:
    if value is None:
        return default
    array = np.asarray(value, dtype=np.float64).reshape(-1)
    if array.size == 0 or not np.isfinite(array[0]):
        return default
    return float(array[0])


def _apply_scale(array: np.ndarray, scale: float, offset: float, fill) -> np.ndarray:
    values = np.array(array, dtype=np.float32, copy=True)
    if fill is not None:
        fill_value = _scalar(fill, np.nan)
        if np.isfinite(fill_value):
            values[values == np.float32(fill_value)] = np.nan
    if scale != 1.0 or offset != 0.0:
        values = values * np.float32(scale) + np.float32(offset)
    return values


class _Hdf4Var:
    def __init__(self, dataset, scale: float, offset: float, fill):
        info = dataset.info()
        self.shape = tuple(int(item) for item in info[2])
        self._dataset = dataset
        self.scale = scale
        self.offset = offset
        self.fill = fill

    def read_raw(self, start: int, stop: int) -> np.ndarray:
        count = stop - start
        return np.asarray(self._dataset.get(start=(start, 0), count=(count, self.shape[1])))

    def read_scaled(self, start: int, stop: int) -> np.ndarray:
        return _apply_scale(self.read_raw(start, stop), self.scale, self.offset, self.fill)


class _Hdf4File:
    def __init__(self, path: Path):
        from pyhdf.SD import SD, SDC

        self.path = path
        self._sd = SD(str(path), SDC.READ)
        self.format = "HDF4"
        self.attributes = {str(key): value for key, value in self._sd.attributes().items()}
        self._open = []

    def close(self) -> None:
        for dataset in self._open:
            dataset.endaccess()
        self._sd.end()

    def _select(self, candidates: tuple[str, ...]):
        datasets = self._sd.datasets()
        lookup = {_normal_name(name): name for name in datasets}
        for candidate in candidates:
            actual = lookup.get(_normal_name(candidate))
            if actual:
                dataset = self._sd.select(actual)
                self._open.append(dataset)
                attrs = {str(key).lower(): value for key, value in dataset.attributes().items()}
                return _Hdf4Var(
                    dataset,
                    _scalar(attrs.get("scale_factor"), 1.0),
                    _scalar(attrs.get("add_offset"), 0.0),
                    attrs.get("_fillvalue", attrs.get("fillvalue")),
                )
        return None

    def fire(self):
        return self._select(FIRE_NAMES)

    def latitude(self):
        return self._select(LAT_NAMES)

    def longitude(self):
        return self._select(LON_NAMES)

    def zenith(self):
        return self._select(ZENITH_NAMES)


class _NetcdfVar:
    def __init__(self, variable):
        self.shape = tuple(int(item) for item in variable.shape)
        self._variable = variable
        # netCDF4 applies scale_factor on read by default. Turn that off so Vela
        # scales packed integers exactly once.
        if hasattr(variable, "set_auto_scale"):
            variable.set_auto_scale(False)
        self.scale = _scalar(getattr(variable, "scale_factor", 1.0), 1.0)
        self.offset = _scalar(getattr(variable, "add_offset", 0.0), 0.0)
        self.fill = getattr(variable, "_FillValue", None)

    def _slice(self, start: int, stop: int):
        return self._variable[start:stop, :]

    def read_raw(self, start: int, stop: int) -> np.ndarray:
        raw = self._slice(start, stop)
        if np.ma.isMaskedArray(raw):
            raw = np.ma.filled(raw, 0)
        return np.asarray(raw)

    def read_scaled(self, start: int, stop: int) -> np.ndarray:
        raw = self._slice(start, stop)
        if np.ma.isMaskedArray(raw):
            raw = np.ma.filled(raw, np.nan)
        return _apply_scale(raw, self.scale, self.offset, self.fill)


class _NetcdfFile:
    def __init__(self, path: Path):
        import netCDF4

        self.path = path
        self._dataset = netCDF4.Dataset(path)
        self.format = "NetCDF4/HDF5"
        self.attributes = {name: getattr(self._dataset, name) for name in self._dataset.ncattrs()}
        self._index = self._walk(self._dataset)

    def close(self) -> None:
        self._dataset.close()

    def _walk(self, group, prefix: str = "") -> dict[str, object]:
        found = {}
        for name, variable in group.variables.items():
            found[_normal_name(f"{prefix}{name}")] = variable
            found[_normal_name(name)] = variable
        for group_name, child in group.groups.items():
            found.update(self._walk(child, f"{prefix}{group_name}/"))
        return found

    def _select(self, candidates: tuple[str, ...]):
        for candidate in candidates:
            variable = self._index.get(_normal_name(candidate))
            if variable is not None and len(getattr(variable, "shape", ())) == 2:
                return _NetcdfVar(variable)
        return None

    def fire(self):
        return self._select(FIRE_NAMES)

    def latitude(self):
        return self._select(LAT_NAMES)

    def longitude(self):
        return self._select(LON_NAMES)

    def zenith(self):
        return self._select(ZENITH_NAMES)


def open_science(path: str | Path):
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    errors = []
    suffix = file_path.suffix.lower()
    if suffix in {".hdf", ".hdf4"}:
        try:
            return _Hdf4File(file_path)
        except Exception as exc:  # noqa: BLE001 - report the reader that failed
            errors.append(f"HDF4: {exc}")
    try:
        return _NetcdfFile(file_path)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"NetCDF4/HDF5: {exc}")
    detail = "; ".join(errors) if errors else "unrecognized file"
    raise RuntimeError(f"Could not open {file_path.name}: {detail}")


def fire_histogram(path: str | Path) -> dict:
    science = open_science(path)
    try:
        mask = science.fire()
        if mask is None:
            names = "unavailable"
            raise RuntimeError(f"{Path(path).name} does not contain a fire-mask array ({names})")
        histogram: dict[int, int] = {}
        corner = None
        for start in range(0, mask.shape[0], 400):
            stop = min(mask.shape[0], start + 400)
            chunk = np.asarray(mask.read_raw(start, stop))
            if corner is None and chunk.size:
                corner = chunk.reshape(-1)[0]
            codes, frequencies = np.unique(chunk.astype(np.int16), return_counts=True)
            for code, frequency in zip(codes.tolist(), frequencies.tolist()):
                histogram[int(code)] = histogram.get(int(code), 0) + int(frequency)
        if not histogram:
            raise RuntimeError(f"{Path(path).name} opened but the fire mask was empty")
        return {
            "path": str(path),
            "file_name": Path(path).name,
            "format": science.format,
            "shape": list(mask.shape),
            "histogram": {str(key): value for key, value in sorted(histogram.items())},
            "pixels": int(sum(histogram.values())),
            "corner_value": None if corner is None else int(corner),
            "opened_array": True,
        }
    finally:
        science.close()


def _attribute_daynight(attributes: dict) -> str | None:
    for key, value in attributes.items():
        if str(key).lower() in {"daynightflag", "day_night_flag", "daynight"}:
            text = str(value).strip().lower()
            if text.startswith("d"):
                return "day"
            if text.startswith("n"):
                return "night"
    return None


def _daytime(zenith_values: list[np.ndarray], daynight: str | None, when, center_lon: float, config: dict):
    if zenith_values:
        joined = np.concatenate([np.asarray(item, dtype=np.float64).ravel() for item in zenith_values])
        finite = joined[np.isfinite(joined)]
        if finite.size:
            median = float(np.median(finite))
            limit = float(config["daytime_solar_zenith_max_deg"])
            return median < limit, "solar_zenith", median
    if daynight == "day":
        return True, "granule_daynight_flag", None
    if daynight == "night":
        return False, "granule_daynight_flag", None
    if when is not None:
        hour = local_hour(when, center_lon)
        low = float(config["daytime_local_hour_min"])
        high = float(config["daytime_local_hour_max"])
        return low <= hour <= high, "local_hour", hour
    return False, "unknown", None


def read_pass(fire_path, geo_path, bbox, when, config: dict) -> dict:
    """Read one fire/geolocation pair and keep only pixels inside the area."""

    fire = open_science(fire_path)
    geo = open_science(geo_path)
    try:
        mask = fire.fire()
        latitude = geo.latitude()
        longitude = geo.longitude()
        if mask is None:
            return {"ok": False, "reason": "missing_fire_mask", "fire_file": str(fire_path)}
        if latitude is None or longitude is None:
            return {"ok": False, "reason": "missing_geolocation", "geo_file": str(geo_path)}
        if tuple(mask.shape) != tuple(latitude.shape) or tuple(mask.shape) != tuple(longitude.shape):
            return {
                "ok": False,
                "reason": "shape_mismatch",
                "fire_shape": list(mask.shape),
                "latitude_shape": list(latitude.shape),
                "longitude_shape": list(longitude.shape),
            }
        zenith = geo.zenith()
        if zenith is not None and tuple(zenith.shape) != tuple(mask.shape):
            zenith = None
        west, south, east, north = bbox
        longitudes = []
        latitudes = []
        classes = []
        zeniths = []
        for start in range(0, mask.shape[0], 400):
            stop = min(mask.shape[0], start + 400)
            lat_chunk = latitude.read_scaled(start, stop)
            lon_chunk = longitude.read_scaled(start, stop)
            selected = in_bbox(lon_chunk, lat_chunk, west, south, east, north)
            if not np.any(selected):
                continue
            class_chunk = np.asarray(mask.read_raw(start, stop), dtype=np.int16)
            longitudes.append(np.asarray(lon_chunk)[selected].astype(np.float32, copy=False))
            latitudes.append(np.asarray(lat_chunk)[selected].astype(np.float32, copy=False))
            classes.append(class_chunk[selected])
            if zenith is not None:
                zeniths.append(np.asarray(zenith.read_scaled(start, stop))[selected])
        if not classes:
            return {"ok": False, "reason": "no_aoi_pixels", "shape": list(mask.shape)}
        center_lon = (west + east) / 2 if west <= east else ((west + east + 360) / 2)
        if center_lon > 180:
            center_lon -= 360
        is_day, how, measure = _daytime(
            zeniths,
            _attribute_daynight({**fire.attributes, **geo.attributes}),
            when,
            center_lon,
            config,
        )
        if not is_day:
            return {
                "ok": False,
                "reason": "nighttime",
                "daytime_check": how,
                "daytime_value": measure,
                "shape": list(mask.shape),
            }
        return {
            "ok": True,
            "reason": None,
            "lon": np.concatenate(longitudes),
            "lat": np.concatenate(latitudes),
            "classes": np.concatenate(classes),
            "shape": list(mask.shape),
            "daytime_check": how,
            "daytime_value": measure,
            "format_fire": fire.format,
            "format_geo": geo.format,
        }
    finally:
        fire.close()
        geo.close()
