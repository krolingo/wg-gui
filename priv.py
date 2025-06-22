# priv.py
import os
import platform
import shutil
import subprocess

IS_MACOS = (platform.system() == "Darwin")
PRIV_ESC = "sudo"        # or “doas” if you prefer
ASKPASS = shutil.which("ssh-askpass") or shutil.which("ssh-askpass-gui") or ""
SUDO_FLAG = "-A" if (ASKPASS and IS_MACOS) else ""

# If we have an askpass helper, tell sudo where to find it
if ASKPASS:
    os.environ["SUDO_ASKPASS"] = ASKPASS

# Detect passwordless escalation for doas and sudo
DOAS_BIN = shutil.which("doas")
SUDO_BIN = shutil.which("sudo")
DOAS_NOPASS = False
SUDO_NOPASS = False
if DOAS_BIN:
    try:
        # Test doas for no-password mode
        res = subprocess.run([DOAS_BIN, "-n", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        DOAS_NOPASS = (res.returncode == 0)
    except Exception:
        pass
if SUDO_BIN:
    try:
        # Test sudo for no-password mode
        res = subprocess.run([SUDO_BIN, "-n", "true"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        SUDO_NOPASS = (res.returncode == 0)
    except Exception:
        pass

def run_priv(cmd_args, **kwargs):
    """
    Run a command with elevated privileges in a blocking fashion.

    On macOS, use AppleScript to prompt for admin privileges.
    On other systems, use sudo/doas with askpass if configured.
    cmd_args: list of strings (e.g. ["mkdir","-p","/some/dir"])
    kwargs: passed to subprocess.run
    """
    import shlex
    # If doas is passwordless, use it directly
    if DOAS_NOPASS:
        return subprocess.run([DOAS_BIN] + cmd_args, **kwargs)
    # If sudo is passwordless, use it with -n (no prompt)
    if SUDO_NOPASS:
        return subprocess.run([SUDO_BIN, "-n"] + cmd_args, **kwargs)
    # Otherwise escalate as needed
    if IS_MACOS:
        # AppleScript elevation
        cmd_str = " ".join(shlex.quote(arg) for arg in cmd_args)
        return subprocess.run(
            ["osascript", "-e", f'do shell script "{cmd_str}" with administrator privileges'],
            **kwargs
        )
    # Fallback to sudo/doas with askpass or default sudo
    prefix = [PRIV_ESC] + ([SUDO_FLAG] if SUDO_FLAG else [])
    full_cmd = prefix + cmd_args
    return subprocess.run(full_cmd, **kwargs)

def build_qprocess_args(cmd_args):
    """
    Return (program, args_list) for QProcess.start().

    On macOS, wrap the command in AppleScript for elevation.
    On other systems, use sudo/doas with askpass if configured.
    cmd_args: list of strings (e.g. [WG_MULTI_SCRIPT, "up", "my.conf"])
    """
    import shlex
    # If doas is passwordless, call it directly
    if DOAS_NOPASS:
        return DOAS_BIN, cmd_args
    # If sudo is passwordless, call it with -n
    if SUDO_NOPASS:
        return SUDO_BIN, ["-n"] + cmd_args
    # Otherwise escalate as needed
    if IS_MACOS:
        cmd_str = " ".join(shlex.quote(arg) for arg in cmd_args)
        return "osascript", ["-e", f'do shell script "{cmd_str}" with administrator privileges']
    # Default to sudo/doas with askpass or default sudo
    prefix = [PRIV_ESC] + ([SUDO_FLAG] if SUDO_FLAG else [])
    prog = prefix[0]
    args = prefix[1:] + cmd_args
    return prog, args