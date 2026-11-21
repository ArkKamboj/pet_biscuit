# Desktop Pup — "Biscuit"

A transparent, always-on-top 2D comic desktop pet for Windows (PyQt6 + pywin32).
Biscuit is an original cream-and-caramel comic beagle pup. He's drawn procedurally
with QPainter in a flat ink-and-color comic-strip style, so the app works with no
image files. Any animation can be swapped for your own PNG sprites (see below).

## Run

```powershell
pip install -r requirements.txt
python main.py          # or: pythonw main.py  (no console)
```

Launching it by hand opens the **Settings window**. It has a live animated preview and two
tabs: **Dog & abilities** (size, proportions, walking style on four legs, two legs or a mix,
where he goes and whether he lands on top of a window or inside it, personality) and **House**.
App options (startup, sprites, reset, quit) are in the **App** button at the bottom. Launching from Windows startup (`--background`)
stays silent. Running the app again while it's already open brings the Settings window back.
Clicking the tray icon also opens Settings, and right-clicking the pup or the tray icon gives
the quick menu. Settings live in `%APPDATA%\DesktopPup\settings.json`.

When Biscuit is sent home, he sprints first. Partway through the run, the doghouse slides in from
the left or right edge of the screen, wobbling and kicking up dust. You choose the side (far
side, left, right or random) and where it parks (near that edge, or a spot you dragged it to).
When he leaves, it slides back out.

## Project layout

| File | Purpose |
|---|---|
| `main.py` | App bootstrap, high-DPI policy, single-instance lock, system-tray menu |
| `snoopy_pet.py` | `PupPet` widget: 60 FPS loop, mood/state machine, physics, clicks, drag, Ctrl+Wheel |
| `doghouse.py` | Conditional, draggable doghouse (front/left/right) with peeking occupant |
| `comic_renderer.py` | Vector comic renderer (pup, faces, bubbles, doghouse) and the `SpriteAnimator` |
| `window_monitor.py` | Win32: monitors/work areas, foreground window, fullscreen detection, `GetLastInputInfo` idle |
| `startup_manager.py` | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` toggle |
| `settings_manager.py` | JSON settings with change signals |

## Behaviour cheat-sheet

| Trigger | Reaction |
|---|---|
| Cursor anywhere | Head, eyes and body orientation track it |
| Slow / still cursor | Calm & curious: head tilts, gentle ear perk, slow wag |
| Medium speed (> 260 px/s) | Walks (or trots above 850 px/s) toward the cursor's X on his current surface |
| Fast / erratic (> 1600 px/s or rapid direction reversals) | Excited: hops, ear-flap dance, panting, ♪ / ♥ bubbles |
| Cursor still 15 s / 28 s | Sits bored → lies with chin on paws, yawns, looks around |
| System idle > 60 s | Drowsy (eyes droop, head nods) → curled-up sleep with Zzz + breathing |
| Mouse moves while asleep | **Stage 1:** ears shoot up, eyes still shut, `?` bubble. **Stage 2:** after ~1.6 s of continued movement he stretches (play-bow + yawn), shakes off and resumes |
| Clicks 1–9 (within 1.5 s of each other) | Alternates between a growl (angry brows, bared teeth, vibrating, `Grrr!`) and a mildly annoyed obedient sit |
| 10th click | `!` startle → doghouse fades in → gallops home → peeks out → comes back out after 18–38 s (or click the house) |
| Drag the pup | He dangles, then falls back to the taskbar |
| Ctrl + Mouse Wheel over him | Scale 0.5×–2.5× (default 0.6×) |
| Walking style setting | On four legs, upright on two legs, or a mix that switches now and then (the sprint home is always on four) |
| Every 18–40 s in a playful mood | Walks under the active window and jumps onto its title bar, or, with "Lands: inside the window", onto the window's inner bottom edge. He rides along if you drag the window. He drops back to the taskbar if it's maximized, fullscreen, minimized, loses focus, or has no head-room |
| Fullscreen app on his monitor | Drops to the taskbar and fades out (tray toggle "Hide During Fullscreen Apps") |

## Custom sprite drop-in guide

Put a folder named `assets` next to `main.py` (or next to `DesktopPup.exe`). Any
animation you provide replaces the vector drawing for that state. Anything missing keeps
using the vector renderer. After adding files, use the tray option **Reload Sprite Assets**.

```
assets/
├── sprites.json              (optional tuning)
├── idle/      idle_000.png, idle_001.png, ...
├── walk/      walk_000.png ...
├── trot/      ...
├── run/       ...            (sprint to the doghouse)
├── jump/      ...            (rising)
├── fall/      ...            (falling)
├── sit/       ...            (bored sit)
├── lie/       ...            (bored, chin on paws)
├── yawn/      ...
├── drowsy/    ...
├── sleep/     ...            (curled up; Zzz bubbles are still drawn on top)
├── wake_ears/ ...            (curled, ears up, eyes closed)
├── stretch/   ...            (wake-up stretch, ~1.3 s)
├── shake/     ...            (wake-up shake, ~1 s)
├── growl/     ...
├── obey_sit/  ...
├── excited/   ...
├── startled/  ...
├── dragged/   ...
├── beg/       ...            (sitting up on hind legs when idle)
├── idle_upright/ ...         (standing on two legs, "two legs" walking style)
├── walk_upright/ ...         (walking on two legs)
├── peek_front/ ...           (drawn clipped inside the front doorway)
├── peek_side/  ...           (drawn at the side doorway; facing right, auto-mirrored)
├── walk_strip.png            (alternative: one horizontal strip instead of a folder)
└── doghouse/
    ├── front.png
    ├── left.png
    └── right.png
```

Rules:
- **Frame order** is alphabetical, so zero-pad the numbers: `walk_000.png`, `walk_001.png`, …
- **Strip sheets** use the name `<animation>_strip.png`, with frames laid out left to right. Frames are
  square (width = image height) unless `frame_width` is set in `sprites.json`.
- **Face right.** Biscuit is mirrored automatically when walking left.
- **Anchor:** the bottom-centre of each frame sits on the surface he's standing on. Leave
  transparent padding around the character, and keep the paws on the bottom row.
- **Size:** by default a frame's height is drawn as 110 units, and units are multiplied by the user scale.
  The vector pup is about 100 units tall, so a 256×256 frame with the dog filling about 90% of it matches.
- **Doghouse PNGs** are drawn 122 units tall with the house's floor centre at the bottom-centre of the image.
  The doorway position the pup runs to is the built-in one: centred for `front`, about 38 units left or right of
  centre for the side views.

`assets/sprites.json` example:

```json
{
  "defaults":   { "fps": 10, "loop": true, "height_units": 110 },
  "animations": {
    "run":     { "fps": 16 },
    "stretch": { "fps": 8,  "loop": false },
    "shake":   { "fps": 18, "loop": false },
    "yawn":    { "fps": 8,  "loop": false },
    "walk":    { "frame_width": 128 }
  }
}
```

## Build a standalone background .exe

```powershell
pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name DesktopPup --icon icon.ico main.py
```

The result is `dist\DesktopPup.exe`. It has no console, so it's suitable for startup.
Put your optional `assets\` folder next to the exe. To bake the assets inside the exe
instead, add `--add-data "assets;assets"`.
Run the exe once and tick **Launch at Windows Startup** in the tray menu. The registry
entry points at the exe's current location. If you move the exe, launching it from the
new place updates the entry automatically.
