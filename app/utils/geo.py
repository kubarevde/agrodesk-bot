"""Geo helpers for status / who-is-working messages."""


def build_geo_block(row: dict) -> str:
    lat = row.get('latitude')
    lon = row.get('longitude')
    if lat in (None, '') or lon in (None, ''):
        return '📌 Геометка: нет'
    lat_s = str(lat).strip()
    lon_s = str(lon).strip()
    if not lat_s or not lon_s:
        return '📌 Геометка: нет'
    maps_url = f'https://www.google.com/maps?q={lat_s},{lon_s}'
    return (
        f'📌 Геометка: есть\n'
        f'🧭 Координаты: {lat_s}, {lon_s}\n'
        f'🗺 Карта: {maps_url}'
    )


def build_geo_lines(row: dict) -> str:
    return build_geo_block(row)
