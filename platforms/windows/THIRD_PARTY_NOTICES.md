# 第三方组件说明

本文件记录官方构建会下载或打包的第三方组件。它们不受本项目 GPL-3.0 重新授权，仍适用各自条款。

## Frida Gadget 17.15.3

- 用途：读取 RC003 返回键对应的 HID 报告；Windows 的普通键盘和 Raw Input 路径会丢弃该报告。
- 官方文件：[frida-gadget-17.15.3-windows-x86_64.dll.xz](https://github.com/frida/frida/releases/download/17.15.3/frida-gadget-17.15.3-windows-x86_64.dll.xz)
- SHA-256：`B566D70189B6D551AD8F4E0BEA24DE08A3D4C0F559BB35B2BDB67D45182240C2`
- 协议：Frida core 的 [wxWindows Library Licence 3.1 / LGPL exception](https://github.com/frida/frida-core/blob/main/COPYING)。构建脚本同时获取该协议文本，并放入小米安装目录。

Frida Gadget 在这里是硬件输入兼容层，不参与软件授权、加密或防破译。

## VB-CABLE Driver Pack 4.5

- 用途：把小米遥控器的 ATVV 蓝牙音频输出为 Windows 可用的虚拟麦克风。
- 官方页面：[VB-CABLE Virtual Audio Device](https://vb-audio.com/Cable/)
- 官方文件：[VBCABLE_Driver_Pack45.zip](https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip)
- SHA-256：`B950E39F01AF1D04EA623C8F6D8EB9B6EA5C477C637295FABF20631C85116BFB`
- 模式：Donationware。安装说明明确标注 VB-Audio 来源。

MiVibe Remote 安装包不内嵌或再分发 VB-CABLE。首次安装时，用户机器从上述 VB-Audio 官方地址下载固定文件并校验 SHA-256 与发布者签名。专业、批量、集成或再分发场景应依据 [VB-Audio 当前许可](https://vb-audio.com/Services/licensing.htm)另行取得适用授权。

只有小米安装流程会按需下载 VB-CABLE；T1 和 V60 不使用虚拟音频驱动。

## Python 依赖

运行和构建依赖包括 hidapi、NumPy、python-sounddevice、Pillow、psutil、pystray、WinRT Python projections 与 PyInstaller。准确版本见 `requirements.txt` 和 `requirements-dev.txt`；再分发时应保留这些软件各自要求的许可证与通知。

## 产品图与应用图标

当前 `MiVibeRemote.ico` 由 MiVibe Remote 项目维护者提供并授权用于本项目，不是从上游仓库导入的资产。图中出现的第三方产品外观、名称和标志仍归各自权利人所有，其出现不表示相关权利人对本项目的认可或合作。
