# -*- coding: utf-8 -*-
"""3Dstudio.co AI Render API client, shared by the Rhino and Revit plugins.

Written for IronPython 2.7 (Rhino 7, pyRevit) and Python 3 (Rhino 8). Uses only the
standard library and .NET (System.Net, System.IO). No pip packages.

The master copy lives in 3dstudio/rhino-plugin/AIRender/tds_api.py and is copied into
the Revit plugin by 3dstudio/revit-plugin/sync_core.sh. Edit the master only.

API (https://app.3dstudio.co/docs/api):
  GET  /api/v1/looks            public list of looks
  POST /api/v1/render           multipart: image, look, quality, input, notes. Bearer key.
                                Returns when the render is done (up to about 2 minutes).
  GET  /api/v1/renders?limit=N  newest renders of the key owner (used if the POST times out)
"""
import os
import json
import time

import clr  # noqa: F401  (IronPython / pythonnet)
clr.AddReference("System")
from System import Array, Byte, Uri
from System.IO import File, MemoryStream, StreamReader
from System.Net import (WebRequest, WebException, WebExceptionStatus,
                        ServicePointManager, SecurityProtocolType)
from System.Text import Encoding

VERSION = "0.1.0"
APP_URL = "https://app.3dstudio.co"
KEYS_URL = APP_URL + "/account/api"          # sign in here to create an API key
ACCOUNT_URL = APP_URL + "/account"
PRICING_URL = APP_URL + "/pricing"
MAX_BYTES = 10 * 1024 * 1024                 # the API rejects images over 10 MB
NOTE_MAX = 400
RENDER_TIMEOUT_MS = 330000                   # the server allows up to 300 s

QUALITIES = [("standard", "Standard"), ("hd", "HD")]
INPUTS = [("untextured", "Untextured model (white or grey)"), ("textured", "Textured model")]
DEFAULT_LOOK = "ext-daylight"

# Used only if GET /api/v1/looks cannot be reached. Same ids and labels as the API.
FALLBACK_LOOKS = [
    {"id": "scandi", "label": "Scandinavian", "group": "Interior"},
    {"id": "warm-contemporary", "label": "Warm contemporary", "group": "Interior"},
    {"id": "industrial", "label": "Industrial loft", "group": "Interior"},
    {"id": "minimal-gallery", "label": "Minimal gallery", "group": "Interior"},
    {"id": "hospitality", "label": "Hotel and restaurant", "group": "Interior"},
    {"id": "retail", "label": "Retail and showroom", "group": "Interior"},
    {"id": "office", "label": "Modern office", "group": "Interior"},
    {"id": "ext-daylight", "label": "Daylight", "group": "Exterior"},
    {"id": "ext-evening", "label": "Evening sun", "group": "Exterior"},
    {"id": "ext-dusk", "label": "Dusk", "group": "Exterior"},
    {"id": "ext-overcast", "label": "Overcast", "group": "Exterior"},
    {"id": "ext-brick-stone", "label": "Brick and stone", "group": "Exterior"},
    {"id": "ext-timber-render", "label": "Timber and render", "group": "Exterior"},
    {"id": "ext-concrete-metal", "label": "Concrete and metal", "group": "Exterior"},
    {"id": "ext-winter", "label": "Winter", "group": "Exterior"},
    {"id": "ext-night", "label": "Night", "group": "Exterior"},
    {"id": "land-garden", "label": "Garden and landscape", "group": "Landscape"},
    {"id": "aerial-day", "label": "Aerial daylight", "group": "Landscape"},
    {"id": "aerial-golden", "label": "Aerial golden hour", "group": "Landscape"},
]


class TdsError(Exception):
    """An error with a message that is safe to show to the user."""
    def __init__(self, message, kind="error"):
        Exception.__init__(self, message)
        self.message = message
        self.kind = kind     # key, credits, upgrade, rate, network, timeout, failed, input, error


def user_agent(host, host_version=""):
    """e.g. 3Dstudio-AIRender-Rhino/0.1.0 (Rhino 8.4)"""
    return "3Dstudio-AIRender-%s/%s (%s %s)" % (host, VERSION, host, host_version)


def _net_setup():
    try:
        ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12
    except Exception:
        pass
    try:
        ServicePointManager.Expect100Continue = False
    except Exception:
        pass


# ------------------------------------------------------------------ config file

def config_path():
    d = os.path.join(os.path.expanduser("~"), ".3dstudio")
    return os.path.join(d, "ai-render.json")


def load_config():
    try:
        with open(config_path(), "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(cfg):
    p = config_path()
    d = os.path.dirname(p)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(p, "w") as f:
        json.dump(cfg, f, indent=2)
    try:
        os.chmod(p, 0o600)   # no effect on Windows, fine
    except Exception:
        pass


def key_looks_valid(key):
    return bool(key) and key.strip().startswith("tds_live_")


# ------------------------------------------------------------------ http

def _read_stream(stream):
    if stream is None:
        return ""
    r = StreamReader(stream, Encoding.UTF8)
    try:
        return r.ReadToEnd()
    finally:
        r.Close()


def _request(method, url, ua, key=None, body=None, content_type=None, timeout=30000):
    """Returns (status_code, text). Raises TdsError for network problems and timeouts."""
    _net_setup()
    req = WebRequest.Create(url)
    req.Method = method
    req.UserAgent = ua
    req.Accept = "application/json"
    req.Timeout = timeout
    try:
        req.ReadWriteTimeout = timeout
    except Exception:
        pass
    if key:
        req.Headers.Add("Authorization", "Bearer " + key)
    if body is not None:
        req.ContentType = content_type
        req.ContentLength = body.Length
        s = req.GetRequestStream()
        try:
            s.Write(body, 0, body.Length)
        finally:
            s.Close()
    try:
        resp = req.GetResponse()
    except WebException as e:
        if e.Response is not None:
            resp = e.Response
        elif e.Status == WebExceptionStatus.Timeout:
            raise TdsError("No answer from 3Dstudio.co in time.", "timeout")
        else:
            raise TdsError("Could not reach 3Dstudio.co. Check your internet connection.", "network")
    try:
        status = int(resp.StatusCode)
        text = _read_stream(resp.GetResponseStream())
    finally:
        resp.Close()
    return status, text


def _json(text):
    try:
        d = json.loads(text)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ------------------------------------------------------------------ looks

def get_looks(ua):
    """Looks from the live API, or the built-in list if the API cannot be reached."""
    try:
        status, text = _request("GET", APP_URL + "/api/v1/looks", ua, timeout=8000)
        looks = _json(text).get("looks")
        if status == 200 and isinstance(looks, list) and looks:
            return [{"id": str(l["id"]), "label": str(l.get("label", l["id"])), "group": str(l.get("group", ""))}
                    for l in looks if "id" in l]
    except Exception:
        pass
    return list(FALLBACK_LOOKS)


# ------------------------------------------------------------------ image

def prepare_image(path):
    """Returns a path to a PNG or JPEG under 10 MB (re-encodes as JPEG if needed)."""
    if os.path.getsize(path) <= MAX_BYTES:
        return path
    try:
        clr.AddReference("System.Drawing")
        from System.Drawing import Bitmap
        from System.Drawing.Imaging import ImageFormat
        out = os.path.splitext(path)[0] + "-small.jpg"
        bmp = Bitmap(path)
        try:
            bmp.Save(out, ImageFormat.Jpeg)
        finally:
            bmp.Dispose()
        if os.path.getsize(out) <= MAX_BYTES:
            return out
    except Exception:
        pass
    raise TdsError("The image is larger than 10 MB. Use a smaller image size and try again.", "input")


def _multipart(path, fields):
    boundary = "----tds%d" % int(time.time() * 1000)
    ms = MemoryStream()

    def w(text):
        b = Encoding.UTF8.GetBytes(text)
        ms.Write(b, 0, b.Length)

    for name, value in fields:
        w("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, name, value))
    ctype = "image/jpeg" if path.lower().endswith((".jpg", ".jpeg")) else "image/png"
    w("--%s\r\nContent-Disposition: form-data; name=\"image\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
      % (boundary, os.path.basename(path), ctype))
    data = File.ReadAllBytes(path)
    ms.Write(data, 0, data.Length)
    w("\r\n--%s--\r\n" % boundary)
    body = ms.ToArray()
    ms.Close()
    return "multipart/form-data; boundary=" + boundary, body


# ------------------------------------------------------------------ render

def _raise_for_status(status, data, raw):
    msg = str(data.get("error", "")).strip()
    if status == 401:
        raise TdsError("3Dstudio.co did not accept your API key. %s\nCreate a new key at %s" % (msg, KEYS_URL), "key")
    if status == 402:
        raise TdsError("You are out of credits. %s\nAdd credits at %s" % (msg, PRICING_URL), "credits")
    if status == 403:
        raise TdsError("API access is part of the paid plans. %s\nSee %s, then create a key at %s"
                       % (msg, PRICING_URL, KEYS_URL), "upgrade")
    if status == 429:
        raise TdsError("Too many renders in a short time (20 per 10 minutes). Wait a few minutes and try again. %s" % msg, "rate")
    if status in (400, 415):
        raise TdsError("3Dstudio.co could not use that request. %s" % (msg or raw[:200]), "input")
    raise TdsError("The render failed (HTTP %d). %s\nCredits for a failed render are refunded."
                   % (status, msg or raw[:200]), "failed")


def _recent_ids(key, ua):
    try:
        status, text = _request("GET", APP_URL + "/api/v1/renders?limit=10", ua, key=key, timeout=15000)
        if status == 200:
            return [r for r in (_json(text).get("renders") or []) if isinstance(r, dict)]
    except TdsError:
        pass
    return []


def render(path, key, ua, look=DEFAULT_LOOK, quality="standard", input_kind="untextured", note=""):
    """Uploads the image and waits for the render. Returns a dict with id and image_url.

    The API answers when the render is done. If the connection times out first, the render
    may still finish on the server, so we poll GET /api/v1/renders for a new entry.
    """
    if not key_looks_valid(key):
        raise TdsError("No API key yet. Create one at %s and paste it in." % KEYS_URL, "key")
    path = prepare_image(path)
    fields = [("look", look or DEFAULT_LOOK), ("quality", quality or "standard"), ("input", input_kind or "untextured")]
    note = (note or "").strip()[:NOTE_MAX]
    if note:
        fields.append(("notes", note))
    ctype, body = _multipart(path, fields)

    before = set(str(r.get("id")) for r in _recent_ids(key, ua))
    try:
        status, text = _request("POST", APP_URL + "/api/v1/render", ua, key=key, body=body,
                                content_type=ctype, timeout=RENDER_TIMEOUT_MS)
    except TdsError as e:
        if e.kind != "timeout":
            raise
        return _poll_for_new(key, ua, before)
    data = _json(text)
    if status == 200 and (data.get("id") or data.get("image_url")):
        return data
    _raise_for_status(status, data, text)


def _poll_for_new(key, ua, before, seconds=240, every=10):
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(every)
        for r in _recent_ids(key, ua):
            if str(r.get("id")) not in before and r.get("image_url"):
                return r
    raise TdsError("No answer in time. The render may still have finished: check %s/renders. "
                   "Failed renders are refunded." % APP_URL, "timeout")


# ------------------------------------------------------------------ result

def studio_url(render_id, src):
    return "%s/?from=%s&src=%s" % (APP_URL, render_id, src) if render_id else APP_URL


def download(url, dest, ua, key=None):
    """Downloads the finished image. The key is only sent to app.3dstudio.co."""
    _net_setup()
    send_key = key if (key and Uri(url).Host.lower() == Uri(APP_URL).Host.lower()) else None
    req = WebRequest.Create(url)
    req.UserAgent = ua
    req.Timeout = 60000
    if send_key:
        req.Headers.Add("Authorization", "Bearer " + send_key)
    try:
        resp = req.GetResponse()
    except WebException:
        raise TdsError("Could not download the render. Open it from %s/renders instead." % APP_URL, "network")
    try:
        s = resp.GetResponseStream()
        ms = MemoryStream()
        buf = Array.CreateInstance(Byte, 65536)
        while True:
            n = s.Read(buf, 0, buf.Length)
            if n <= 0:
                break
            ms.Write(buf, 0, n)
        File.WriteAllBytes(dest, ms.ToArray())
    finally:
        resp.Close()
    return dest
