# 3Dstudio.co AI Render for Revit (pyRevit extension, v0.1.0)

Sends the active Revit view to 3Dstudio.co AI Render and shows the finished image. This is "send view", not
"render inside Revit".

**Status: not tested in Revit.** Written against the Revit API and pyRevit and syntax-checked only. See "Testing".

## What you need

- Revit 2019 or newer (Windows), with [pyRevit](https://github.com/pyrevitlabs/pyRevit) 4.8 or newer installed.
- A 3Dstudio.co account on a paid plan or with a bought credit pack, and an API key. Create the key at
  https://app.3dstudio.co/account/api (shown once, starts with `tds_live_`).

## Install

Option A, pyRevit Extensions manager (once the extension is listed, see PUBLISHING.md):
pyRevit tab > Extensions > search "AIRender" > Install.

Option B, copy the folder:
1. Copy the `AIRender.extension` folder to `%APPDATA%\pyRevit\Extensions\` (create the folder if it is missing).
2. In Revit: pyRevit tab > Reload (or restart Revit). A new "AIRender" tab with a "Render View" button appears.

Option C, any folder: pyRevit tab > Settings > Custom Extension Directories > add the folder that contains
`AIRender.extension`, then Save Settings and Reload.

## Use

1. Open a 3D, camera, plan, elevation or section view. Frame it the way you want the render.
2. Click AIRender > Render > Render View.
3. First time: paste your API key. Choose look, quality, model type (untextured or textured), image size and an
   optional note (up to 400 characters).
4. Click Render. The view is exported, uploaded, and the render comes back in a window (up to about 2 minutes).
   Save it as PNG, or open it in the studio to fix, relight or download.

Errors you may see: no or wrong key (you are asked for a new one), out of credits (link to pricing), plan does
not include API access (link to pricing), too many renders (limit is 20 per 10 minutes). A render that fails is
refunded on the server.

## What is sent

Only when you click Render, and only to `app.3dstudio.co` over https: the exported PNG of the view, the look,
quality, model type and note, and your API key in the `Authorization` header. No model, no geometry, no file
paths. The PNG stays in your Windows temp folder (`%TEMP%\3dstudio-revit-...`) after sending; delete it any time.
The API key is stored in your pyRevit user config (`%APPDATA%\pyRevit\pyRevit_config.ini`) in plain text.
Revoke keys at https://app.3dstudio.co/account/api if a computer is lost.

## API used

- `GET  https://app.3dstudio.co/api/v1/looks` (the look list, no key needed; a built-in list is used if offline)
- `POST https://app.3dstudio.co/api/v1/render` with multipart fields `image`, `look`, `quality`, `input`, `notes`
  and header `Authorization: Bearer tds_live_...`. The answer comes back when the render is done.
- `GET  https://app.3dstudio.co/api/v1/renders?limit=10` only if the POST connection times out, to find the
  finished render.
- User agent: `3Dstudio-AIRender-Revit/0.1.0 (Revit <version>)`.

## Files

- `AIRender.extension/AIRender.tab/Render.panel/Render View.pushbutton/script.py` the button.
- `AIRender.extension/lib/tds_api.py` the API client. It is a copy of `../rhino-plugin/AIRender/tds_api.py`;
  run `./sync_core.sh` after editing the master.

## Testing

Static checks only (Python syntax). Not run in Revit. First real test: install, open a 3D view, click Render
View with the pyRevit output window open (it shows errors). Things most likely to need a fix: the exported file
name (Revit appends the view name; the script takes the newest PNG in the temp folder), and the WinForms dialog
layout on high-DPI screens.
