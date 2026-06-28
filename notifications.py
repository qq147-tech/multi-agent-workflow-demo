from __future__ import annotations

import subprocess
import sys

from workflow_models import WorkflowState


class NotificationService:
    def notify_human_review(self, state: WorkflowState, title: str, body: str) -> None:
        state.log("notification", f"{title}: {body}")
        if sys.platform != "win32":
            return
        try:
            safe_title = title.replace("'", "''")
            safe_body = body.replace("'", "''")
            script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "Add-Type -AssemblyName System.Drawing; "
                "$notify = New-Object System.Windows.Forms.NotifyIcon; "
                "$notify.Icon = [System.Drawing.SystemIcons]::Information; "
                "$notify.Visible = $true; "
                f"$notify.BalloonTipTitle = '{safe_title}'; "
                f"$notify.BalloonTipText = '{safe_body}'; "
                "$notify.ShowBalloonTip(7000); "
                "Start-Sleep -Seconds 8; "
                "$notify.Dispose();"
            )
            subprocess.Popen(
                ["powershell", "-NoProfile", "-Command", script],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            state.log("notification", f"desktop popup skipped: {exc}")
