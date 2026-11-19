from __future__ import annotations

import json
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings


@dataclass(frozen=True)
class CronSetupGuide:
    key: str
    label: str
    steps: list[str]


class CronjobService:
    """Botble-style cron helper for the platform scheduler command."""

    def __init__(self, heartbeat_path: Path | None = None) -> None:
        self.heartbeat_path = heartbeat_path or settings.STORAGE_DIR / "cron_heartbeat.json"
        self.log_path = settings.STORAGE_DIR / "logs" / "cron.log"

    def status(self) -> dict[str, Any]:
        heartbeat = self._read_heartbeat()
        last_run_at = heartbeat.get("lastRunAt")
        seconds_since_last_run = self._seconds_since(last_run_at)
        configured = last_run_at is not None
        healthy = configured and seconds_since_last_run is not None and seconds_since_last_run <= 120
        return {
            "configured": configured,
            "healthy": healthy,
            "status": "healthy" if healthy else "configured" if configured else "not_configured",
            "message": self._message(configured, healthy, seconds_since_last_run),
            "lastRunAt": last_run_at,
            "secondsSinceLastRun": seconds_since_last_run,
            "command": self.cron_command(),
            "manualCommand": self.run_command(),
            "projectPath": str(settings.BASE_DIR),
            "logPath": str(self.log_path),
            "frequency": "Every minute",
            "tasks": self.tasks(last_run_at),
            "setupGuides": [guide.__dict__ for guide in self.setup_guides()],
        }

    def cron_command(self) -> str:
        return f"* * * * * cd {self._shell_path(settings.BASE_DIR)} && {self.run_command()} >> {self._shell_path(self.log_path)} 2>&1"

    def run_command(self) -> str:
        return f"{self._shell_path(Path(self._python_binary()))} -m karpy_platform.core.support.cron run"

    def run_due_tasks(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "lastRunAt": now.isoformat(),
            "tasks": [
                {
                    "key": "system.heartbeat",
                    "name": "Scheduler heartbeat",
                    "status": "completed",
                    "ranAt": now.isoformat(),
                }
            ],
        }
        self.heartbeat_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def tasks(self, last_run_at: str | None) -> list[dict[str, Any]]:
        return [
            {
                "key": "system.heartbeat",
                "name": "Scheduler heartbeat",
                "frequency": "Every minute",
                "lastRunAt": last_run_at,
                "description": "Confirms that the server cron command is calling the KARPy scheduler.",
            },
            {
                "key": "plugins.scheduled_tasks",
                "name": "Plugin scheduled tasks",
                "frequency": "Plugin defined",
                "lastRunAt": last_run_at,
                "description": "Plugins can register queue, email, cleanup, report, and import/export jobs here.",
            },
        ]

    def setup_guides(self) -> list[CronSetupGuide]:
        return [
            CronSetupGuide(
                "cpanel",
                "cPanel",
                [
                    "Log in to your cPanel account.",
                    'Open "Cron Jobs" under the Advanced section.',
                    'Under "Add New Cron Job", select "Once Per Minute (* * * * *)".',
                    'Paste the command above into the "Command" field.',
                    'Click "Add New Cron Job" to save.',
                ],
            ),
            CronSetupGuide(
                "plesk",
                "Plesk",
                [
                    "Open Websites & Domains in Plesk.",
                    "Choose Scheduled Tasks for this domain.",
                    "Create a task with Run a command selected.",
                    "Set the schedule to every minute.",
                    "Paste the command above and save the task.",
                ],
            ),
            CronSetupGuide(
                "directadmin",
                "DirectAdmin",
                [
                    "Log in to DirectAdmin.",
                    "Open Advanced Features, then Cron Jobs.",
                    "Set minute to * and every other timing field to *.",
                    "Paste the command above into the command field.",
                    "Save and check this page again after one minute.",
                ],
            ),
            CronSetupGuide(
                "ssh",
                "SSH/Terminal",
                [
                    "Connect to your server over SSH.",
                    "Run crontab -e for the website user.",
                    "Add the command above on a new line.",
                    "Save the crontab and wait one minute.",
                    "Return to this screen to confirm the scheduler heartbeat.",
                ],
            ),
            CronSetupGuide(
                "windows",
                "Windows Task Scheduler",
                [
                    "Open Task Scheduler on the server.",
                    "Create a Basic Task named KARPy Scheduler.",
                    "Set the trigger to repeat every 1 minute indefinitely.",
                    f"Set the action program to {self._python_binary()}.",
                    "Set the arguments to -m karpy_platform.core.support.cron run and the start-in folder to your KARPy project path.",
                ],
            ),
            CronSetupGuide(
                "docker",
                "Docker/Supervisor",
                [
                    "Run the scheduler command in a small sidecar process or supervisor program.",
                    "Keep the working directory set to your KARPy project path.",
                    "Restart the scheduler process automatically if it exits.",
                    "Send stdout and stderr to your container or supervisor logs.",
                    "Verify this page after the process has run at least once.",
                ],
            ),
        ]

    def _read_heartbeat(self) -> dict[str, Any]:
        try:
            return json.loads(self.heartbeat_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _message(self, configured: bool, healthy: bool, seconds_since_last_run: int | None) -> str:
        if not configured:
            return "Cronjob is not configured yet"
        if healthy:
            return "Cronjob is configured and running"
        if seconds_since_last_run is None:
            return "Cronjob status cannot be checked"
        return "Cronjob has not run recently"

    def _seconds_since(self, value: str | None) -> int | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))

    def _python_binary(self) -> str:
        return sys.executable or "python"

    def _shell_path(self, path: Path | str) -> str:
        return shlex.quote(str(path))


cronjob_service = CronjobService()


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "run":
        cronjob_service.run_due_tasks()


if __name__ == "__main__":
    main()
