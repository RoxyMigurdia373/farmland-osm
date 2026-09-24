"""Isolated, bounded GEE trial. Credentials are per-session, never cached globally."""
import base64
import hashlib
import json
import secrets
import threading
from urllib.parse import urlencode

import requests

SCOPES = ['https://www.googleapis.com/auth/earthengine',
          'https://www.googleapis.com/auth/cloud-platform']
LOCK = threading.Lock()


def authorization(config):
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
        'client_id': config['client_id'], 'redirect_uri': config['redirect_uri'],
        'response_type': 'code', 'scope': ' '.join(SCOPES), 'state': state,
        'code_challenge': challenge, 'code_challenge_method': 'S256',
        'access_type': 'online', 'prompt': 'select_account consent',
    })
    return url, state, verifier


def exchange(config, code, verifier):
    response = requests.post('https://oauth2.googleapis.com/token', data={
        'client_id': config['client_id'], 'client_secret': config['client_secret'],
        'redirect_uri': config['redirect_uri'], 'code': code,
        'code_verifier': verifier, 'grant_type': 'authorization_code',
    }, timeout=30)
    if not response.ok:
        raise ValueError('Google授权交换失败，请重新登录并核对回调网址。')
    return response.json()['access_token']


def extract(frame, project, token, year, progress):
    import ee
    from google.oauth2.credentials import Credentials
    if len(frame) > 100:
        raise ValueError('试验版每次最多100块，请选择小范围测试。')
    payload = json.loads(frame.to_crs(4326).to_json(drop_id=True))
    if len(json.dumps(payload).encode()) > 4_000_000:
        raise ValueError('矢量几何过大，请缩小试验范围。')
    # ee.Initialize uses process globals: keep initialization, evaluation and reset under one lock.
    if not LOCK.acquire(blocking=False):
        raise ValueError('另一项GEE试验正在运行，请稍后再试。')
    try:
        ee.Initialize(credentials=Credentials(token=token), project=project)
        ee.data.setDeadline(120000)
        plots = ee.FeatureCollection(payload)
        start, end = ee.Date.fromYMD(year, 1, 1), ee.Date.fromYMD(year+1, 1, 1)
        def ndvi(image):
            scl = image.select('SCL')
            mask = scl.neq(0).And(scl.neq(1)).And(scl.neq(3)).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
            nir, red = image.select('B8').multiply(.0001), image.select('B4').multiply(.0001)
            return nir.subtract(red).divide(nir.add(red)).updateMask(mask.And(nir.add(red).neq(0))).rename('NDVI').copyProperties(image, ['system:time_start'])
        images = ee.ImageCollection('COPERNICUS/S2_SR_HARMONIZED').filterBounds(plots.geometry()).filterDate(start, end).filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 60)).map(ndvi)
        import datetime
        days = (datetime.date(year+1,1,1)-datetime.date(year,1,1)).days
        records = []
        for day in range(0, days, 10):
            date = start.advance(day, 'day')
            subset = images.filterDate(date, ee.Date(date.advance(10, 'day').millis().min(end.millis())))
            blank = ee.Image.constant(0).rename('NDVI').updateMask(ee.Image.constant(0))
            composite = ee.Image(ee.Algorithms.If(subset.size().gt(0), subset.median(), blank))
            reducer = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
            output = composite.reduceRegions(collection=plots, reducer=reducer, scale=10, crs='EPSG:6933', tileScale=4)
            output = output.map(lambda f: ee.Feature(None, {'plot_id': f.get('plot_id'), 'date': date.format('YYYY-MM-dd'), 'NDVI': f.get('mean'), 'valid_pixels': f.get('count')}))
            records.extend(f['properties'] for f in output.getInfo()['features'])
            progress(min((day+10)/days, 1))
        return records
    finally:
        try:
            ee.Reset()
        finally:
            LOCK.release()
