"""Tests for scripts/smartchime-update, run against a real git origin with the system commands stubbed."""

import subprocess
import textwrap
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "smartchime-update"

STUBS = {
    # Drop sudo's options (-u USER -H --) and run the command as the test user.
    "sudo": """
        while [ "$1" != "--" ]; do shift; done
        shift
        exec "$@"
    """,
    "id": 'echo "${FAKE_UID:-0}"',
    "sleep": "exit 0",
    "curl": """
        cat <<EOF
        mkdir -p "\\$UV_INSTALL_DIR"
        cp "$STUBS_DIR/uv-impl" "\\$UV_INSTALL_DIR/uv"
        EOF
    """,
    "systemctl": """
        tag() { git -C "$SMARTCHIME_DIR" describe --tags --exact-match 2>/dev/null; }
        listed() { [ -f "$STATE/$1" ] && grep -qx "$(tag)" "$STATE/$1"; }
        case "$1" in
            daemon-reload) ;;
            is-enabled) [ -f "$STATE/enabled" ] && { echo enabled; exit 0; }; echo disabled; exit 1 ;;
            restart) echo "restart $(tag)" >> "$STATE/restarts" ;;
            is-active) listed broken_tags && { echo failed; exit 3; }; echo active ;;
            show)
                n=$(cat "$STATE/nrestarts" 2>/dev/null || echo 0)
                listed flapping_tags && n=$((n + 1)) && echo "$n" > "$STATE/nrestarts"
                echo "$n" ;;
        esac
    """,
    "apt-mark": """
        cmd=$1; shift
        touch "$STATE/held"
        for p in "$@"; do
            grep -vx "$p" "$STATE/held" > "$STATE/held.tmp"; mv "$STATE/held.tmp" "$STATE/held"
            [ "$cmd" = hold ] && echo "$p" >> "$STATE/held"
        done
        exit 0
    """,
    "apt-get": """
        if [ "$1" = install ] && [ -f "$STATE/os_upgrades" ]; then
            [ -s "$STATE/held" ] && { echo "held packages were not unheld" >&2; exit 1; }
            cp "$STATE/os_upgrades" "$STATE/versions"
        fi
        exit 0
    """,
    "dpkg-query": """
        for pkg; do :; done
        grep "^$pkg " "$STATE/versions" | cut -d' ' -f2
    """,
}

UV_IMPL = """
    echo "$*" >> "$STATE/uv_calls"
    if [ "$1" = sync ]; then
        tag=$(git describe --tags --exact-match 2>/dev/null)
        [ -f "$STATE/sync_fail_tags" ] && grep -qx "$tag" "$STATE/sync_fail_tags" && exit 1
        mkdir -p .venv
        printf 'home = /usr/bin\\nuv = 0.9.0\\n' > .venv/pyvenv.cfg
    fi
    exit 0
"""


def _write_stub(path: Path, body: str) -> None:
    path.write_text("#!/bin/bash\n" + textwrap.dedent(body))
    path.chmod(0o755)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Host:
    """A fake Pi: a Smartchime checkout, a git origin with release tags, and stubbed system commands."""

    def __init__(self, root: Path, tags: list[str]):
        self.root = root
        self.origin = root / "origin"
        self.home = root / "home"
        self.app = self.home / "smartchime"
        self.state = root / "state"
        self.bin = root / "bin"
        self.stubs = root / "stubs"
        self.unit = root / "etc" / "smartchime.service"
        self.dietpi_txt = root / "boot" / "dietpi.txt"
        self.bin_link = root / "usr" / "local" / "bin" / "smartchime-update"
        for d in (self.origin, self.home, self.state, self.bin, self.stubs, self.unit.parent, self.dietpi_txt.parent):
            d.mkdir(parents=True)
        self.bin_link.parent.mkdir(parents=True)
        self.env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "STATE": str(self.state),
            "STUBS_DIR": str(self.stubs),
            "SMARTCHIME_DIR": str(self.app),
            "SMARTCHIME_USER": "dietpi",
            "SMARTCHIME_HOME": str(self.home),
            "SMARTCHIME_UNIT": str(self.unit),
            "SMARTCHIME_DIETPI_TXT": str(self.dietpi_txt),
            "SMARTCHIME_BIN_LINK": str(self.bin_link),
            "SMARTCHIME_REBOOT_REQUIRED": str(root / "run" / "reboot-required"),
        }
        for name, body in STUBS.items():
            _write_stub(self.bin / name, body)
        _write_stub(self.stubs / "uv-impl", UV_IMPL)
        self.dietpi_txt.write_text(
            "AUTO_SETUP_AUTOMATED=1\nCONFIG_CHECK_DIETPI_UPDATES=0\nCONFIG_CHECK_APT_UPDATES=0\nCONFIG_NTP_MODE=2\n"
        )
        (self.state / "versions").write_text("linux-image-rpi-v8 1\nraspi-firmware 1\nrpi-eeprom 1\n")
        (self.state / "enabled").touch()

        subprocess.run(["git", "init", "-q", "-b", "main", str(self.origin)], check=True, env=self.env)
        for tag in tags:
            (self.origin / "VERSION").write_text(tag)
            _git("add", "VERSION", cwd=self.origin)
            _git("commit", "-q", "-m", tag, cwd=self.origin)
            _git("tag", tag, cwd=self.origin)
        subprocess.run(["git", "clone", "-q", str(self.origin), str(self.app)], check=True, env=self.env)

    def checkout(self, ref: str) -> None:
        _git("-c", "advice.detachedHead=false", "checkout", "-q", ref, cwd=self.app)

    def release(self, tag: str) -> None:
        (self.origin / "VERSION").write_text(tag)
        _git("commit", "-q", "-am", tag, cwd=self.origin)
        _git("tag", tag, cwd=self.origin)

    def mark(self, name: str, *lines: str) -> None:
        (self.state / name).write_text("".join(f"{line}\n" for line in lines))

    def read(self, name: str) -> str:
        path = self.state / name
        return path.read_text() if path.exists() else ""

    def install_uv(self) -> None:
        uv = self.home / ".local" / "bin" / "uv"
        uv.parent.mkdir(parents=True, exist_ok=True)
        _write_stub(uv, UV_IMPL)

    @property
    def deployed(self) -> str:
        return _git("describe", "--tags", "--always", cwd=self.app)

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["bash", str(SCRIPT), *args], env=self.env, capture_output=True, text=True, timeout=60)


@pytest.fixture
def host(tmp_path: Path) -> Host:
    h = Host(tmp_path, ["v2.0.0", "v2.5.0", "v2.6.0"])
    h.checkout("v2.5.0")
    h.install_uv()
    return h


def test_deploys_the_latest_release_tag(host: Host):
    host.release("v2.7.0")

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert host.deployed == "v2.7.0"
    assert host.read("restarts") == "restart v2.7.0\n"
    assert "sync --frozen --extra hw --no-dev --python /usr/bin/python3 --no-python-downloads" in host.read("uv_calls")


def test_picks_the_highest_version_not_the_newest_or_prerelease_tag(host: Host):
    host.release("v10.0.0")
    host.release("v9.10.0")
    host.release("v9.9.0")
    host.release("v11.0.0-rc1")

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert host.deployed == "v10.0.0"


def test_rolls_back_to_the_previous_tag_when_the_service_does_not_stay_active(host: Host):
    host.release("v2.7.0")
    host.mark("broken_tags", "v2.7.0")

    result = host.run()

    assert result.returncode == 1
    assert host.deployed == "v2.5.0"
    assert host.read("restarts") == "restart v2.7.0\nrestart v2.5.0\n"
    assert "v2.7.0 failed" in result.stderr
    assert "rolled back to v2.5.0" in result.stderr


def test_a_crash_loop_that_is_momentarily_active_still_rolls_back(host: Host):
    host.release("v2.7.0")
    host.mark("flapping_tags", "v2.7.0")

    result = host.run()

    assert result.returncode == 1
    assert host.deployed == "v2.5.0"


def test_rolls_back_when_the_new_tag_does_not_sync(host: Host):
    host.release("v2.7.0")
    host.mark("sync_fail_tags", "v2.7.0")

    result = host.run()

    assert result.returncode == 1
    assert host.deployed == "v2.5.0"
    assert host.read("restarts") == "restart v2.5.0\n"


@pytest.mark.parametrize("untagged", [False, True], ids=["pre-uv-tag", "untagged"])
def test_reports_failure_without_rolling_back_below_the_first_uv_release(host: Host, untagged: bool):
    host.checkout("v2.0.0")
    if untagged:
        _git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "wip", cwd=host.app)
    host.mark("broken_tags", "v2.6.0")

    result = host.run()

    assert result.returncode == 1
    assert host.deployed == "v2.6.0"
    assert host.read("restarts") == "restart v2.6.0\n"
    assert "v2.6.0 failed" in result.stderr
    assert "no release at or after v2.5.0 to roll back to" in result.stderr


def test_does_not_restart_when_already_on_the_latest_tag(host: Host):
    host.checkout("v2.6.0")
    host.run()
    (host.state / "restarts").unlink(missing_ok=True)

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert host.deployed == "v2.6.0"
    assert host.read("restarts") == ""
    assert "already running v2.6.0" in result.stdout


def test_installs_but_does_not_start_a_service_that_is_not_enabled(host: Host):
    (host.state / "enabled").unlink()

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert host.deployed == "v2.6.0"
    assert (host.app / ".venv" / "pyvenv.cfg").exists()
    assert host.read("restarts") == ""
    assert "systemctl enable --now smartchime.service" in result.stdout


def test_installs_uv_for_the_app_user_when_missing(host: Host):
    (host.home / ".local" / "bin" / "uv").unlink()

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert (host.home / ".local" / "bin" / "uv").exists()
    assert host.deployed == "v2.6.0"


def test_self_updates_an_installed_uv(host: Host):
    result = host.run()

    assert result.returncode == 0, result.stderr
    assert "self update" in host.read("uv_calls")


def _pip_venv(host: Host) -> Path:
    venv = host.app / ".venv"
    (venv / "lib").mkdir(parents=True)
    (venv / "lib" / "pip-installed").touch()
    (venv / "pyvenv.cfg").write_text("home = /usr/bin\nversion = 3.13.5\n")
    return venv


def test_replaces_a_pip_venv_with_a_uv_one_and_restarts(host: Host):
    host.checkout("v2.6.0")
    venv = _pip_venv(host)

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert "uv = " in (venv / "pyvenv.cfg").read_text()
    assert not (venv / "lib" / "pip-installed").exists()
    assert host.read("restarts") == "restart v2.6.0\n"


def test_keeps_an_existing_uv_venv(host: Host):
    host.checkout("v2.6.0")
    host.run()
    marker = host.app / ".venv" / "kept"
    marker.touch()

    host.run()

    assert marker.exists()


HELD = {"linux-image-rpi-v8", "raspi-firmware", "rpi-eeprom"}


def test_holds_the_kernel_and_firmware_packages(host: Host):
    result = host.run()

    assert result.returncode == 0, result.stderr
    assert set(host.read("held").split()) == HELD


def test_sets_dietpi_to_auto_apply_apt_and_only_notify_of_dietpi_updates(host: Host):
    host.run()

    assert host.dietpi_txt.read_text() == (
        "AUTO_SETUP_AUTOMATED=1\nCONFIG_CHECK_DIETPI_UPDATES=1\nCONFIG_CHECK_APT_UPDATES=2\nCONFIG_NTP_MODE=2\n"
    )


def _expected_unit(host: Host) -> str:
    return textwrap.dedent(f"""\
        [Unit]
        Description=Smartchime
        Wants=network-online.target
        After=network-online.target

        [Service]
        Type=exec
        WorkingDirectory={host.app}
        ExecStart={host.app}/.venv/bin/python -m smartchime
        Restart=always
        User=dietpi
        Group=dietpi

        [Install]
        WantedBy=multi-user.target
        """)


def test_replaces_an_outdated_unit_and_restarts_onto_it(host: Host):
    host.checkout("v2.6.0")
    host.unit.write_text("[Service]\nExecStart=/home/dietpi/smartchime/.venv/bin/python src/smartchime/main.py\n")

    result = host.run()

    assert result.returncode == 0, result.stderr
    assert host.unit.read_text() == _expected_unit(host)
    assert host.read("restarts") == "restart v2.6.0\n"


def test_installs_the_unit_and_the_smartchime_update_command(host: Host):
    host.run()

    assert host.unit.read_text() == _expected_unit(host)
    assert host.bin_link.resolve() == (host.app / "scripts" / "smartchime-update").resolve()


def test_os_upgrades_the_held_packages_rehold_them_and_reports_a_reboot(host: Host):
    host.mark("os_upgrades", "linux-image-rpi-v8 2", "raspi-firmware 2", "rpi-eeprom 1")

    result = host.run("--os")

    assert result.returncode == 0, result.stderr
    assert host.read("versions") == "linux-image-rpi-v8 2\nraspi-firmware 2\nrpi-eeprom 1\n"
    assert set(host.read("held").split()) == HELD
    assert "Reboot required" in result.stdout
    assert "linux-image-rpi-v8 1 -> 2" in result.stdout
    assert host.deployed == "v2.5.0"
    assert host.read("restarts") == ""


def test_os_without_upgrades_reports_no_reboot_needed(host: Host):
    result = host.run("--os")

    assert result.returncode == 0, result.stderr
    assert "No reboot required" in result.stdout
    assert set(host.read("held").split()) == HELD


def test_os_reholds_the_packages_when_the_upgrade_fails(host: Host):
    _write_stub(host.bin / "apt-get", '[ "$1" = install ] && exit 100; exit 0')

    result = host.run("--os")

    assert result.returncode != 0
    assert set(host.read("held").split()) == HELD


def test_os_reports_a_reboot_that_debian_already_asked_for(host: Host):
    reboot_required = host.root / "run" / "reboot-required"
    reboot_required.parent.mkdir()
    reboot_required.touch()

    result = host.run("--os")

    assert "Reboot required" in result.stdout


def test_refuses_to_run_without_root(host: Host):
    host.env["FAKE_UID"] = "1000"

    result = host.run()

    assert result.returncode == 1
    assert "must run as root" in result.stderr
    assert host.deployed == "v2.5.0"


def test_rejects_unknown_arguments(host: Host):
    result = host.run("--bogus")

    assert result.returncode == 64
    assert "Usage:" in result.stderr
    assert host.deployed == "v2.5.0"


def test_a_failing_current_release_is_reported_not_rolled_back_onto_itself(host: Host):
    host.checkout("v2.6.0")
    host.mark("broken_tags", "v2.6.0")

    result = host.run()

    assert result.returncode == 1
    assert host.read("restarts") == "restart v2.6.0\n"
    assert "v2.6.0 failed" in result.stderr
    assert "rolled back" not in result.stderr
