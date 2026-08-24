"""Actionable Windows environment checks for MiVibe Remote.

The checker intentionally does not change system state.  It reports what is
missing and leaves repair actions to the main application so users can inspect
the result before an administrator prompt appears.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import platform
from typing import Callable, Iterable, Mapping
import threading
import tkinter as tk


@dataclass(frozen=True)
class EnvironmentCheckItem:
    key: str
    title: str
    status: str
    detail: str
    action: str = ""


def _audio_endpoint_names(devices: Iterable[Mapping[str, object]]) -> tuple[set[str], set[str]]:
    render: set[str] = set()
    capture: set[str] = set()
    for device in devices:
        name = str(device.get("name", "")).strip()
        if not name:
            continue
        if int(device.get("max_output_channels", 0) or 0) > 0:
            render.add(name)
        if int(device.get("max_input_channels", 0) or 0) > 0:
            capture.add(name)
    return render, capture


def _contains_endpoint(names: Iterable[str], needle: str) -> bool:
    folded = needle.casefold()
    return any(folded in name.casefold() for name in names)


def _read_recent_log(path: Path, limit: int = 256_000) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            return stream.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def evaluate_environment(
    *,
    app_dir: Path,
    config_path: Path,
    log_dir: Path,
    worker_status: Mapping[str, object],
    audio_devices: Iterable[Mapping[str, object]],
    platform_name: str,
    platform_release: str,
) -> list[EnvironmentCheckItem]:
    results: list[EnvironmentCheckItem] = []

    is_windows = platform_name.casefold() == "windows"
    results.append(EnvironmentCheckItem(
        key="windows",
        title="Windows 系统",
        status="pass" if is_windows else "fail",
        detail=f"Windows {platform_release}" if is_windows else f"当前系统：{platform_name}",
        action="请在 Windows 10 或 Windows 11 上运行。" if not is_windows else "",
    ))

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config_ok = isinstance(config, dict)
    except (OSError, UnicodeError, json.JSONDecodeError):
        config = {}
        config_ok = False
    results.append(EnvironmentCheckItem(
        key="config",
        title="用户配置",
        status="pass" if config_ok else "fail",
        detail="按键映射和语音设置可读取" if config_ok else "配置文件缺失或损坏",
        action="打开按键与语音设置并保存一次。" if not config_ok else "",
    ))

    render, capture = _audio_endpoint_names(audio_devices)
    cable_input = _contains_endpoint(render, "CABLE Input")
    cable_output = _contains_endpoint(capture, "CABLE Output")
    cable_ready = cable_input and cable_output
    missing = []
    if not cable_input:
        missing.append("播放端 CABLE Input")
    if not cable_output:
        missing.append("录音端 CABLE Output")
    results.append(EnvironmentCheckItem(
        key="vb_cable",
        title="VB-CABLE 语音驱动",
        status="pass" if cable_ready else "fail",
        detail="CABLE Input 与 CABLE Output 均已识别" if cable_ready else "缺少：" + "、".join(missing),
        action="点击“安装/修复语音驱动”，完成官方安装窗口后重启 Windows。" if not cable_ready else "",
    ))

    bridge_alive = bool(worker_status.get("bridge_alive"))
    audio_alive = bool(worker_status.get("audio_alive"))
    workers_ready = bridge_alive and audio_alive
    results.append(EnvironmentCheckItem(
        key="workers",
        title="后台桥接",
        status="pass" if workers_ready else "fail",
        detail=(
            "按键桥接与音频路由均在运行"
            if workers_ready
            else f"按键桥接={'运行' if bridge_alive else '停止'}，音频路由={'运行' if audio_alive else '停止'}"
        ),
        action="点击“重启桥接”；若仍失败，请打开日志。" if not workers_ready else "",
    ))

    support_script = app_dir / "support" / "configure-xiaomi-audio.ps1"
    script_ready = support_script.is_file()
    results.append(EnvironmentCheckItem(
        key="repair_tool",
        title="修复工具",
        status="pass" if script_ready else "fail",
        detail="官方驱动检查脚本完整" if script_ready else "安装目录缺少修复脚本",
        action="重新安装完整的 MiVibe Remote 安装包。" if not script_ready else "",
    ))

    bridge_log = _read_recent_log(log_dir / "bridge.log")
    remote_ready = any(marker in bridge_log for marker in (
        "READY remote=",
        "CONNECTED remote=",
        "XIAOMI HID TAP READY",
        "XIAOMI HID TAP ATTACHED",
    ))
    results.append(EnvironmentCheckItem(
        key="remote",
        title="遥控器识别",
        status="pass" if remote_ready else "warn",
        detail="日志中已识别小米蓝牙遥控器 2" if remote_ready else "暂未在最近日志中看到遥控器就绪记录",
        action="确认系统蓝牙已连接遥控器，然后按一次方向键并刷新检查。" if not remote_ready else "",
    ))

    return results


def run_environment_check(
    *,
    app_dir: Path,
    config_path: Path,
    log_dir: Path,
    worker_status: Mapping[str, object],
    audio_query: Callable[[], Iterable[Mapping[str, object]]] | None = None,
) -> list[EnvironmentCheckItem]:
    if audio_query is None:
        import sounddevice as sd

        audio_query = sd.query_devices
    try:
        devices = list(audio_query())
    except Exception as exc:
        devices = []
        audio_error = EnvironmentCheckItem(
            key="audio_catalog",
            title="Windows 音频设备",
            status="fail",
            detail=f"无法读取音频设备：{exc}",
            action="重启 Windows；若仍失败，请重新安装声卡驱动。",
        )
    else:
        audio_error = None

    results = evaluate_environment(
        app_dir=app_dir,
        config_path=config_path,
        log_dir=log_dir,
        worker_status=worker_status,
        audio_devices=devices,
        platform_name=platform.system(),
        platform_release=platform.release(),
    )
    if audio_error is not None:
        results.insert(2, audio_error)
    return results


class EnvironmentCheckWindow:
    """Non-modal, refreshable health-check window owned by the main app."""

    COLORS = {
        "pass": ("#e8f8f0", "#118553", "通过"),
        "warn": ("#fff6df", "#b77900", "需确认"),
        "fail": ("#fff0f0", "#cf3333", "需修复"),
    }

    def __init__(
        self,
        parent: tk.Misc,
        check_provider: Callable[[], list[EnvironmentCheckItem]],
        on_repair: Callable[[], None],
        on_restart: Callable[[], None],
        on_open_logs: Callable[[], None],
    ) -> None:
        self.parent = parent
        self.check_provider = check_provider
        self.on_repair = on_repair
        self.on_restart = on_restart
        self.on_open_logs = on_open_logs
        self.window: tk.Toplevel | None = None
        self.results_frame: tk.Frame | None = None
        self.summary_var = tk.StringVar(value="正在检查…")
        self.refresh_button: tk.Button | None = None

    def show(self) -> None:
        if self.window is None or not self.window.winfo_exists():
            self._build()
        assert self.window is not None
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
        self.refresh()

    def _build(self) -> None:
        window = tk.Toplevel(self.parent)
        self.window = window
        window.title("MiVibe 环境检查")
        window.geometry("760x690")
        window.minsize(680, 560)
        window.configure(bg="#eef2f7")
        window.protocol("WM_DELETE_WINDOW", window.withdraw)

        header = tk.Frame(window, bg="#101b31", padx=26, pady=20)
        header.pack(fill="x")
        tk.Label(
            header,
            text="环境检查",
            bg="#101b31",
            fg="white",
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="只检查，不会自动修改系统；发现问题后由你决定是否修复。",
            bg="#101b31",
            fg="#aebbd0",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(4, 0))

        summary = tk.Frame(window, bg="white", padx=20, pady=14)
        summary.pack(fill="x", padx=18, pady=(16, 10))
        tk.Label(
            summary,
            textvariable=self.summary_var,
            bg="white",
            fg="#152033",
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(side="left")
        self.refresh_button = tk.Button(
            summary,
            text="重新检查",
            command=self.refresh,
            relief="flat",
            bg="#1677ff",
            fg="white",
            activebackground="#0d5fd4",
            activeforeground="white",
            padx=16,
            pady=7,
            cursor="hand2",
        )
        self.refresh_button.pack(side="right")

        canvas = tk.Canvas(window, bg="#eef2f7", highlightthickness=0)
        scrollbar = tk.Scrollbar(window, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=(18, 0))
        self.results_frame = tk.Frame(canvas, bg="#eef2f7")
        item_id = canvas.create_window((0, 0), window=self.results_frame, anchor="nw")
        self.results_frame.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(item_id, width=event.width),
        )

        actions = tk.Frame(window, bg="#eef2f7", padx=18, pady=14)
        actions.pack(fill="x")
        for label, command in (
            ("安装/修复语音驱动", self.on_repair),
            ("重启桥接", self.on_restart),
            ("打开日志", self.on_open_logs),
        ):
            tk.Button(
                actions,
                text=label,
                command=command,
                relief="flat",
                bg="white",
                fg="#152033",
                activebackground="#e5eaf1",
                padx=14,
                pady=8,
                cursor="hand2",
            ).pack(side="left", padx=(0, 8))

    def refresh(self) -> None:
        if self.refresh_button is not None:
            self.refresh_button.configure(state="disabled", text="检查中…")
        self.summary_var.set("正在检查系统、驱动、后台桥接和遥控器…")

        def work() -> None:
            try:
                results = self.check_provider()
            except Exception as exc:
                results = [EnvironmentCheckItem(
                    key="checker",
                    title="环境检查程序",
                    status="fail",
                    detail=f"检查未完成：{type(exc).__name__}: {exc}",
                    action="打开日志并把 host.log 发给开发者。",
                )]
            self.parent.after(0, lambda: self._render(results))

        threading.Thread(target=work, name="environment-check", daemon=True).start()

    def _render(self, results: list[EnvironmentCheckItem]) -> None:
        if self.results_frame is None:
            return
        for child in self.results_frame.winfo_children():
            child.destroy()

        failures = sum(item.status == "fail" for item in results)
        warnings = sum(item.status == "warn" for item in results)
        if failures:
            self.summary_var.set(f"发现 {failures} 项需要修复，{warnings} 项需要确认")
        elif warnings:
            self.summary_var.set(f"核心环境已就绪，还有 {warnings} 项需要确认")
        else:
            self.summary_var.set("全部检查通过，可以开始使用")

        for item in results:
            background, color, badge = self.COLORS.get(item.status, self.COLORS["warn"])
            card = tk.Frame(
                self.results_frame,
                bg="white",
                highlightbackground="#dce3ed",
                highlightthickness=1,
                padx=16,
                pady=13,
            )
            card.pack(fill="x", pady=(0, 9), padx=(0, 18))
            title_row = tk.Frame(card, bg="white")
            title_row.pack(fill="x")
            tk.Label(
                title_row,
                text=item.title,
                bg="white",
                fg="#152033",
                font=("Microsoft YaHei UI", 11, "bold"),
            ).pack(side="left")
            tk.Label(
                title_row,
                text=badge,
                bg=background,
                fg=color,
                font=("Microsoft YaHei UI", 8, "bold"),
                padx=9,
                pady=3,
            ).pack(side="right")
            tk.Label(
                card,
                text=item.detail,
                bg="white",
                fg="#64748b",
                font=("Microsoft YaHei UI", 9),
                justify="left",
                anchor="w",
                wraplength=630,
            ).pack(fill="x", pady=(6, 0))
            if item.action:
                tk.Label(
                    card,
                    text="建议：" + item.action,
                    bg="white",
                    fg=color,
                    font=("Microsoft YaHei UI", 9),
                    justify="left",
                    anchor="w",
                    wraplength=630,
                ).pack(fill="x", pady=(5, 0))

        if self.refresh_button is not None:
            self.refresh_button.configure(state="normal", text="重新检查")
