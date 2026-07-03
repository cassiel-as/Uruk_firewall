"""
URUK custom tool: capture_screenshot (視覺 — vision)
"""
from services.computer_tools import ToolSpec, ArgSpec

SPEC = ToolSpec(
    name='capture_screenshot',
    description='Capture a screenshot of the full screen or a region. Returns path, dimensions, and format. Uses mss (preferred), PIL.ImageGrab, or PowerShell as fallback.',
    args=[
        ArgSpec('region', 'str', False, default='full',
                description='Region to capture: "full", "active_window", or "x,y,w,h" pixel coords.'),
        ArgSpec('save_path', 'str', False, default=None,
                description='Optional file path to save the screenshot. Defaults to a temp PNG file.'),
    ],
    needs_visual=False,
    category='screen',
)


def execute(args: dict) -> dict:
    try:
        import os
        import tempfile
        import time
        args = args or {}
        region_arg = str(args.get('region') or 'full').strip()
        save_path = args.get('save_path') or None

        if save_path:
            save_path = os.path.abspath(os.path.expanduser(str(save_path)))
        else:
            ts = int(time.time())
            save_path = os.path.join(tempfile.gettempdir(), f'uruk_screenshot_{ts}.png')

        def parse_region(s):
            if s in ('full', '', 'active_window'):
                return None
            parts = [x.strip() for x in s.split(',')]
            if len(parts) == 4:
                return tuple(int(p) for p in parts)
            return None

        region = parse_region(region_arg)

        # Try mss first (fastest, no PIL dependency)
        try:
            import mss
            import mss.tools
            with mss.mss() as sct:
                if region is None:
                    monitor = sct.monitors[0]
                else:
                    x, y, w, h = region
                    monitor = {'left': x, 'top': y, 'width': w, 'height': h}
                shot = sct.grab(monitor)
                mss.tools.to_png(shot.rgb, shot.size, output=save_path)
                return {'ok': True, 'path': save_path, 'width': shot.width, 'height': shot.height, 'format': 'png', 'method': 'mss'}
        except ImportError:
            pass

        # Try PIL.ImageGrab
        try:
            from PIL import ImageGrab
            if region is None:
                img = ImageGrab.grab()
            else:
                x, y, w, h = region
                img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.save(save_path)
            return {'ok': True, 'path': save_path, 'width': img.width, 'height': img.height, 'format': 'png', 'method': 'PIL'}
        except ImportError:
            pass

        # PowerShell fallback (Windows only)
        import subprocess
        ps = (
            'Add-Type -AssemblyName System.Windows.Forms,System.Drawing;'
            '$s=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;'
            '$b=New-Object System.Drawing.Bitmap($s.Width,$s.Height);'
            '$g=[System.Drawing.Graphics]::FromImage($b);'
            '$g.CopyFromScreen($s.Location,[System.Drawing.Point]::Empty,$s.Size);'
            f'$b.Save("{save_path.replace(chr(92), chr(47))}")'
        )
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, timeout=20
        )
        if result.returncode == 0 and os.path.exists(save_path):
            return {'ok': True, 'path': save_path, 'width': None, 'height': None, 'format': 'png', 'method': 'powershell'}

        return {'ok': False, 'error': 'no_screenshot_backend',
                'install_hint': 'pip install mss  OR  pip install Pillow'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}
