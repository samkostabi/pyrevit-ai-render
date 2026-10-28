# -*- coding: utf-8 -*-
"""Render View: send the active Revit view to 3Dstudio.co AI Render (v0.1.0).

pyRevit pushbutton. Exports the active view to a PNG (ImageExportOptions) in a temp folder,
asks for look, quality and an optional note, uploads it with your API key, waits for the
render and opens it. Works with IronPython 2.7 and CPython 3 engines in pyRevit.
"""
__title__ = "Render\nView"
__author__ = "3Dstudio.co"
__doc__ = "Send the active view to 3Dstudio.co AI Render and get a finished image back."

import os
import time
import glob
import shutil
import tempfile
import webbrowser

import clr
clr.AddReference("System.Windows.Forms")
clr.AddReference("System.Drawing")
import System
from System.Windows import Forms
from System import Drawing

from Autodesk.Revit.DB import (ImageExportOptions, ExportRange, ImageFileType, ZoomFitType,
                               ImageResolution, ElementId, FitDirectionType)
from System.Collections.Generic import List
from pyrevit import revit, script

import tds_api as api

HOST = "Revit"
SRC = "revit"
CFG_SECTION = "tds_ai_render"
PIXEL_SIZES = [("1536 px (fast)", 1536), ("2048 px (recommended)", 2048), ("3072 px (large)", 3072)]
# ViewType names that cannot be exported as a picture (compared by name, so a missing enum value cannot break loading).
NOT_EXPORTABLE = ("Schedule", "DrawingSheet", "Legend", "ProjectBrowser", "SystemBrowser", "Report",
                  "CostReport", "LoadsReport", "PressureLossReport", "PanelSchedule", "ColumnSchedule", "Internal")


def ua():
    try:
        v = str(revit.doc.Application.VersionNumber)
    except Exception:
        v = ""
    return api.user_agent(HOST, v)


# ------------------------------------------------------------------ settings (pyRevit user config)

def get_settings():
    """pyRevit user config first; falls back to the shared ~/.3dstudio/ai-render.json file."""
    shared = api.load_config()
    out = {}
    try:
        cfg = script.get_config(CFG_SECTION)
        for name in ("api_key", "look", "quality", "input", "pixels"):
            val = cfg.get_option(name, "")
            out[name] = val if val else shared.get(name, "")
    except Exception:
        out = shared
    return out


def save_settings(values):
    try:
        cfg = script.get_config(CFG_SECTION)
        for k, v in values.items():
            cfg.set_option(k, str(v))
        script.save_config()
    except Exception:
        shared = api.load_config()
        shared.update(values)
        api.save_config(shared)


def clear_key():
    save_settings({"api_key": ""})


# ------------------------------------------------------------------ export

def export_view(view, pixels):
    """Exports the view to PNG. Revit adds its own name parts to the file name, so we take the newest png."""
    folder = os.path.join(tempfile.gettempdir(), "3dstudio-revit-" + time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(folder)
    opts = ImageExportOptions()
    opts.ExportRange = ExportRange.SetOfViews
    ids = List[ElementId]()
    ids.Add(view.Id)
    opts.SetViewsAndSheets(ids)
    opts.FilePath = os.path.join(folder, "view")
    opts.HLRandWFViewsFileType = ImageFileType.PNG
    opts.ShadowViewsFileType = ImageFileType.PNG
    opts.ZoomType = ZoomFitType.FitToPage
    opts.PixelSize = int(pixels)
    opts.ImageResolution = ImageResolution.DPI_150
    opts.FitDirection = FitDirectionType.Horizontal
    revit.doc.ExportImage(opts)
    files = glob.glob(os.path.join(folder, "*.png")) + glob.glob(os.path.join(folder, "*.PNG"))
    if not files:
        raise api.TdsError("Revit did not write an image for this view. Try a 3D or camera view.", "error")
    return max(files, key=os.path.getmtime)


# ------------------------------------------------------------------ dialogs

def options_form(settings, looks, view_name):
    """WinForms dialog. Returns a dict or None if cancelled."""
    need_key = not api.key_looks_valid(settings.get("api_key", ""))
    form = Forms.Form()
    form.Text = "3Dstudio.co AI Render"
    form.FormBorderStyle = Forms.FormBorderStyle.FixedDialog
    form.StartPosition = Forms.FormStartPosition.CenterScreen
    form.MaximizeBox = False
    form.MinimizeBox = False
    form.ClientSize = Drawing.Size(460, 400 if need_key else 330)

    y = [14]

    def label(text, h=18):
        l = Forms.Label()
        l.Text = text
        l.Location = Drawing.Point(14, y[0])
        l.Size = Drawing.Size(432, h)
        form.Controls.Add(l)
        y[0] += h + 2
        return l

    def combo(items, selected_index):
        c = Forms.ComboBox()
        c.DropDownStyle = Forms.ComboBoxStyle.DropDownList
        for it in items:
            c.Items.Add(it)
        c.SelectedIndex = selected_index
        c.Location = Drawing.Point(14, y[0])
        c.Size = Drawing.Size(432, 24)
        form.Controls.Add(c)
        y[0] += 32
        return c

    label("View: %s" % view_name)
    y[0] += 4

    key_box = None
    if need_key:
        label("API key (paid accounts)")
        key_box = Forms.TextBox()
        key_box.UseSystemPasswordChar = True
        key_box.Location = Drawing.Point(14, y[0])
        key_box.Size = Drawing.Size(432, 24)
        form.Controls.Add(key_box)
        y[0] += 28
        link = Forms.LinkLabel()
        link.Text = "Create a key at app.3dstudio.co/account/api"
        link.Location = Drawing.Point(14, y[0])
        link.Size = Drawing.Size(432, 18)
        link.LinkClicked += lambda s, e: webbrowser.open(api.KEYS_URL)
        form.Controls.Add(link)
        y[0] += 28

    label("Look")
    look_ids = [l["id"] for l in looks]
    look_cb = combo([("%s: %s" % (l["group"], l["label"])) if l["group"] else l["label"] for l in looks],
                    look_ids.index(settings.get("look")) if settings.get("look") in look_ids else
                    (look_ids.index(api.DEFAULT_LOOK) if api.DEFAULT_LOOK in look_ids else 0))

    label("Quality")
    q_keys = [k for k, _ in api.QUALITIES]
    q_cb = combo([n for _, n in api.QUALITIES], q_keys.index(settings.get("quality")) if settings.get("quality") in q_keys else 0)

    label("Model")
    i_keys = [k for k, _ in api.INPUTS]
    i_cb = combo([n for _, n in api.INPUTS], i_keys.index(settings.get("input")) if settings.get("input") in i_keys else 0)

    label("Image size sent")
    px_vals = [v for _, v in PIXEL_SIZES]
    try:
        px_sel = px_vals.index(int(settings.get("pixels") or 2048))
    except ValueError:
        px_sel = 1
    px_cb = combo([n for n, _ in PIXEL_SIZES], px_sel)

    label("Note (optional, up to %d characters)" % api.NOTE_MAX)
    note = Forms.TextBox()
    note.Multiline = True
    note.MaxLength = api.NOTE_MAX
    note.Location = Drawing.Point(14, y[0])
    note.Size = Drawing.Size(432, 52)
    form.Controls.Add(note)
    y[0] += 62

    ok = Forms.Button()
    ok.Text = "Render"
    ok.Location = Drawing.Point(280, y[0])
    ok.Size = Drawing.Size(80, 28)
    cancel = Forms.Button()
    cancel.Text = "Cancel"
    cancel.Location = Drawing.Point(366, y[0])
    cancel.Size = Drawing.Size(80, 28)
    cancel.DialogResult = Forms.DialogResult.Cancel
    form.Controls.Add(ok)
    form.Controls.Add(cancel)
    form.CancelButton = cancel
    form.AcceptButton = ok
    hint = Forms.Label()
    hint.Text = "Uses credits. Failed renders are refunded."
    hint.Location = Drawing.Point(14, y[0] + 6)
    hint.Size = Drawing.Size(260, 18)
    form.Controls.Add(hint)

    result = {"ok": False}

    def on_ok(sender, e):
        if key_box is not None:
            k = key_box.Text.strip()
            if not api.key_looks_valid(k):
                Forms.MessageBox.Show("That does not look like a 3Dstudio.co API key. Keys start with tds_live_.\n\nCreate one at "
                                      + api.KEYS_URL, "3Dstudio.co AI Render")
                return
            result["api_key"] = k
        result["look"] = look_ids[look_cb.SelectedIndex]
        result["quality"] = q_keys[q_cb.SelectedIndex]
        result["input"] = i_keys[i_cb.SelectedIndex]
        result["pixels"] = px_vals[px_cb.SelectedIndex]
        result["note"] = note.Text.strip()[:api.NOTE_MAX]
        result["ok"] = True
        form.DialogResult = Forms.DialogResult.OK
        form.Close()

    ok.Click += on_ok
    form.ShowDialog()
    return result if result["ok"] else None


def result_form(local_path, render_id):
    form = Forms.Form()
    form.Text = "3Dstudio.co AI Render - done"
    form.StartPosition = Forms.FormStartPosition.CenterScreen
    img = Drawing.Image.FromFile(local_path)
    scale = min(1.0, 960.0 / max(img.Width, 1), 640.0 / max(img.Height, 1))
    w, h = int(img.Width * scale), int(img.Height * scale)
    form.ClientSize = Drawing.Size(max(w + 24, 520), h + 70)
    pb = Forms.PictureBox()
    pb.Image = img
    pb.SizeMode = Forms.PictureBoxSizeMode.Zoom
    pb.Location = Drawing.Point(12, 12)
    pb.Size = Drawing.Size(w, h)
    form.Controls.Add(pb)

    def mk(text, x, w_, handler):
        b = Forms.Button()
        b.Text = text
        b.Location = Drawing.Point(x, h + 26)
        b.Size = Drawing.Size(w_, 28)
        b.Click += handler
        form.Controls.Add(b)

    def on_save(s, e):
        d = Forms.SaveFileDialog()
        d.Filter = "PNG image (*.png)|*.png"
        d.FileName = "3dstudio-render-%s.png" % time.strftime("%Y%m%d-%H%M%S")
        if d.ShowDialog() == Forms.DialogResult.OK:
            shutil.copyfile(local_path, d.FileName)

    mk("Save as...", 12, 90, on_save)
    mk("Open in studio (fix, relight, download)", 110, 260, lambda s, e: webbrowser.open(api.studio_url(render_id, SRC)))
    mk("Close", 378, 80, lambda s, e: form.Close())
    form.ShowDialog()
    img.Dispose()


def alert(text):
    Forms.MessageBox.Show(text, "3Dstudio.co AI Render", Forms.MessageBoxButtons.OK, Forms.MessageBoxIcon.Warning)


# ------------------------------------------------------------------ run

def main():
    view = revit.active_view
    if view is None or str(view.ViewType) in NOT_EXPORTABLE or getattr(view, "IsTemplate", False):
        alert("Open a 3D, camera, plan, elevation or section view first. Schedules, sheets and legends cannot be sent.")
        return
    settings = get_settings()
    agent = ua()
    try:
        looks = api.get_looks(agent)
        opts = options_form(settings, looks, view.Name)
        if opts is None:
            return
        key = opts.get("api_key") or settings.get("api_key", "")
        to_save = {"look": opts["look"], "quality": opts["quality"], "input": opts["input"], "pixels": opts["pixels"]}
        if opts.get("api_key"):
            to_save["api_key"] = opts["api_key"]
        save_settings(to_save)

        shot = export_view(view, opts["pixels"])
        output = script.get_output()
        output.print_md("**3Dstudio.co AI Render:** view sent. Waiting for the render, this can take up to 2 minutes...")
        res = api.render(shot, key, agent, look=opts["look"], quality=opts["quality"],
                         input_kind=opts["input"], note=opts["note"])
        url = res.get("image_url")
        if not url:
            raise api.TdsError("The render finished but no image link came back. Open %s/renders" % api.APP_URL, "failed")
        out = os.path.join(os.path.dirname(shot), "render.png")
        api.download(url, out, agent, key)
        output.print_md("Done. Credits left: %s" % res.get("credits", "?"))
        result_form(out, res.get("id"))
    except api.TdsError as e:
        if e.kind == "key":
            clear_key()
        alert(e.message)
    except Exception as e:
        alert("Something went wrong: %s" % e)


main()
